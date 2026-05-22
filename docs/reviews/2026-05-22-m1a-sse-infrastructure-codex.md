# mdflow M1a SSE 인프라 리뷰 - Codex

작성일: 2026-05-22
대상 diff: `git diff v0.0.1-m0..HEAD`

검증:
- `.venv/bin/python -m pytest -q tests/api/test_convert.py tests/test_service.py tests/test_cache.py` -> 37 passed
- `.venv/bin/ruff check src/mdflow/api/convert.py src/mdflow/core/service.py src/mdflow/core/cache.py tests/api/test_convert.py tests/test_service.py tests/test_cache.py` -> All checks passed
- `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`, M0 PRD, 관련 core/api 파일을 실제 코드 기준으로 확인

## 차단

### 1. 비-`MdflowError`가 SSE terminal event 없이 스트림을 끊습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:90`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:121`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:145`

판정:
- 알려진 제약 #1에 대해서는 **M1a에 catch-all을 넣는 쪽**이 맞다고 봅니다.
- 이유는 이 코드가 "TextConverter 전용 route"가 아니라 M1b 컨버터들이 올라탈 SSE error envelope입니다. 설계 문서 §6도 "변환/fetch 중 MdflowError/예외 → event: error"라고 되어 있는데, 현재 구현은 `MdflowError`만 만족합니다.

문제:
- `fetch_url`, `service.lookup`, `service.run_conversion`에서 `ValueError`, `TypeError`, 컨버터 라이브러리 예외, `AssertionError`, `pydantic.ValidationError` 등이 나오면 async generator 밖으로 전파됩니다.
- 특히 `run_conversion`은 `started` 또는 일부 `progress`를 보낸 뒤 `task.result()`에서 raw exception을 다시 raise할 수 있습니다. 이 경우 HTTP status는 이미 200이고, 클라이언트는 `done`/`error` 없는 절단 스트림을 받습니다.
- 로컬 재현도 가능합니다. fake converter가 `progress("half", 50)` 후 `ValueError("boom")`을 던지면 `TestClient(..., raise_server_exceptions=False)` 기준 응답은 `200 text/event-stream`이지만 terminal event가 없습니다.

권고 조치:
- `ConversionService.run_conversion()`에서 `converter.convert()`의 raw exception을 `MdflowError(ErrorCode.CONVERSION_FAILED, ...)`로 wrap하는 편이 가장 의미가 정확합니다. `cache.write()`의 `CACHE_IO_ERROR`는 이미 `MdflowError`로 유지됩니다.
- route boundary에도 마지막 방어선으로 broad `except Exception`을 두고 `ErrorCode.INTERNAL` error event를 합성하세요. 이때 `logger.exception(...)`으로 서버 로그에는 traceback을 남기는 것이 좋습니다.
- 회귀 테스트: fake converter가 `ValueError`를 던질 때 마지막 SSE event가 `error`이고, code가 정한 정책(`CONVERSION_FAILED` 또는 `INTERNAL`)과 일치하는지 확인하세요.

### 2. file upload 경로가 `MDFLOW_MAX_INPUT_MB`를 적용하지 않고 전체 파일을 읽습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:64`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:68`
- `/home/restful3/workspace/mdflow/src/mdflow/settings.py:25`

문제:
- URL 입력은 `UrlPolicy.max_bytes`로 `MDFLOW_MAX_URL_INPUT_MB`가 적용되지만, multipart file 입력은 `await upload.read()`로 전체 파일을 제한 없이 bytes화합니다.
- PRD의 `INPUT_TOO_LARGE` 및 `MDFLOW_MAX_INPUT_MB` 정책과 맞지 않고, `/convert`가 처음 생긴 시점부터 큰 업로드가 메모리 압박으로 이어질 수 있습니다.

권고 조치:
- `request.app.state.settings.max_input_mb * 1024 * 1024`를 기준으로 file path에도 cap을 적용하세요.
- 구현은 최소한 `await upload.read(max_bytes + 1)` 후 초과 시 stream 시작 전 `HTTPException(413, ...)` 또는 정책상 `INPUT_TOO_LARGE` error event를 반환하는 방식이 가능합니다. 현재 입력 검증이 stream 생성 전 400을 내므로, file-size reject도 pre-stream 413이 자연스럽습니다.
- 회귀 테스트: `MDFLOW_MAX_INPUT_MB=1` 등으로 낮춘 뒤 초과 파일이 변환/캐시 write 없이 거부되는지 확인하세요.

## 권고

### 1. JSON/multipart 입력 검증을 더 좁혀야 합니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:64`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:70`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:74`

현재 `application/json` body가 invalid JSON이거나 list/string이면 `request.json()` 또는 `body.get()`에서 raw 500이 됩니다. `{"url": 123}`도 `fetch_url`까지 흘러 raw exception 경로를 만들 수 있습니다.

또한 multipart form 안에 `file`과 `url` field를 같이 보내면 `url` field를 읽지 않기 때문에 "exactly one" 검증을 우회하고 file 변환으로 처리됩니다. API가 "JSON url만 지원"이라고 해석할 수도 있지만, error message와 설계 문서의 "둘 다 있음" 정책을 기준으로 보면 테스트가 빠진 상태입니다.

권고:
- JSON body는 `dict`인지, `url`은 non-empty `str`인지 검증하고 아니면 400을 반환하세요.
- multipart form에서도 `url` field가 있으면 400으로 거부하거나, 명시적으로 "multipart url field는 지원하지 않음" 정책을 테스트로 고정하세요.

### 2. client disconnect 후 executor 작업 방치는 후속 처리로 두어도 됩니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:138`
- `/home/restful3/workspace/mdflow/src/mdflow/runtime/concurrency.py:37`

알려진 제약 #2에는 **동의**합니다. M1a의 TextConverter 경로에서는 영향이 작고, Python `ThreadPoolExecutor`에서 이미 실행 중인 동기 작업은 취소가 실질적으로 어렵습니다.

다만 M1b/M2에서 docx/pptx/pdf처럼 긴 변환이 붙으면 orphan compute와 cache write가 운영 비용 문제가 됩니다. 후속으로 `request.is_disconnected()` 체크, generator `CancelledError` 처리, 변환별 cooperative cancellation token을 설계하는 정도가 현실적입니다.

### 3. form upload resource close를 명시하면 좋습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:65`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:68`

`request.form()`에서 받은 `UploadFile`은 spooled temp file을 가질 수 있습니다. 지금은 전체 read 후 request lifecycle/GC에 맡기는 형태입니다. 누수가 명확히 재현되는 수준은 아니지만, `async with request.form() as form:` 패턴을 쓰면 업로드 리소스 close 정책이 코드에 명확히 남습니다.

### 4. 테스트 보강 포인트

현재 happy path와 기본 error path는 잘 덮여 있습니다. 추가하면 좋은 회귀는 다음입니다.

- fake converter raw `ValueError` -> terminal `error` event
- fake `fetch_url` raw exception 또는 `MdflowError(URL_*)` -> terminal `error` event
- invalid JSON / JSON list / non-string url -> 400
- multipart `file` + `url` field -> 400 또는 명시 정책
- file size cap 초과 -> 413 또는 `INPUT_TOO_LARGE`
- URL cache hit에서도 현재 요청의 fetch metadata가 `done.metadata.fetch`에 합성되는지

## 메모

### 1. 이벤트 펌프 race 판단은 조건부로 맞습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:38`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:85`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:138`

알려진 제약 #3의 추론에는 **동의**합니다. 현재 converter contract처럼 progress callback이 worker 함수 안에서 동기 호출되고, worker가 반환한 뒤 executor future completion이 loop에 schedule되는 구조라면, 같은 worker thread에서 `call_soon_threadsafe(q.put_nowait, ...)`가 future completion callback보다 먼저 loop ready queue에 들어갑니다. 따라서 `task.done()`이 true가 되는 시점에는 선행 progress put이 이미 실행됐거나 실행 순서를 앞에 확보한 상태라 `task.done() and q.empty()`가 마지막 progress를 누락하기 어렵습니다.

반례는 converter가 별도 thread를 띄워 `convert()` 반환 후 progress callback을 호출하는 경우입니다. 그건 현재 converter contract 밖으로 보는 게 맞습니다. 이 invariant는 `ProgressCallback` 문서나 converter authoring guide에 "synchronous, in-call only"로 명시해두면 좋습니다.

### 2. `UploadFile` import 결정은 맞습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:17`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:67`

`request.form()`이 반환하는 file object는 Starlette의 `starlette.datastructures.UploadFile`이므로, `isinstance(upload, UploadFile)`에 쓰는 import는 현재처럼 Starlette 쪽이 맞습니다. FastAPI의 parameter-injection용 `UploadFile`을 import하는 것보다 이 코드 경로와 더 정확히 맞습니다.

### 3. service split 방향은 좋습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/core/service.py:65`
- `/home/restful3/workspace/mdflow/src/mdflow/core/service.py:106`
- `/home/restful3/workspace/mdflow/src/mdflow/core/service.py:143`

`lookup()`으로 detect/cache/converter select를 분리한 덕분에 SSE route가 `cached`와 `started`를 올바른 시점에 낼 수 있습니다. 기존 `convert()` wrapper도 유지되어 비-SSE 호출자와 기존 테스트 호환성이 보존됩니다.

### 4. URL metadata 합성은 요구사항과 맞습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:31`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:100`
- `/home/restful3/workspace/mdflow/src/mdflow/api/convert.py:129`

URL fetch 결과를 cache key에 넣지 않고, `done.metadata.fetch`에 현재 요청별 metadata를 합성하는 방향은 PRD/URL 합의안과 맞습니다. cache hit에서도 `_done_event(lr.cached, fetch_meta)`를 거치므로 provenance가 현재 요청 기준으로 붙습니다.

## 결론

전체 구조는 M1a의 방향과 잘 맞습니다. async route가 동기 service를 executor로 넘기고, progress를 loop-safe queue로 마샬링하며, service split으로 `cached`/`started`를 구분한 설계는 타당합니다.

다만 SSE endpoint의 핵심 계약은 "HTTP 200 stream이 시작된 뒤에는 반드시 terminal `done` 또는 `error`로 끝난다"입니다. raw exception 절단 스트림은 이 계약을 깨므로 M1a에서 고치는 편이 맞습니다. file size cap도 `/convert`가 public upload surface가 된 순간 적용되어야 하는 기본 안전장치입니다. 이 두 가지를 보완하면 M1b 컨버터 작업으로 넘어가기 좋은 상태입니다.
