# M1a 설계 — SSE 변환 인프라 (`POST /convert`)

> mdflow Phase **M1**의 첫 sub-project. M1 전체(사무 포맷 + SSE)를 "SSE 인프라(M1a) → 컨버터(M1b)"로 분해한 결과의 앞단.
> 기준 문서: `docs/specs/2026-05-21-mdflow-design.md` (PRD §5 데이터 흐름, §5.1 SSE 스키마), `PROCESS_STATE.md`.

**작성일**: 2026-05-22
**대상 phase**: M1a (M0 `v0.0.1-m0` 위)

---

## 1. 목적 / 배경

M0에서 골격(core types, registry, sha256 캐시, URL fetch helper, txt/md/csv passthrough, `ConversionService`, FastAPI `/healthz` + admin)이 완성됐다. M1a는 그 위에 **단일 호출로 진행 상황과 결과를 함께 받는 `POST /convert` SSE 스트리밍 경로**를 올린다.

핵심 제약: 변환 라이브러리는 대부분 **동기**(mammoth, python-pptx 등 M1b)이므로, async FastAPI 핸들러가 동기 변환을 스레드 풀에서 구동하면서 진행률을 SSE로 흘려야 한다. M1a는 이 **async↔sync 오케스트레이션 골격**을 기존 TextConverter 위에서 먼저 검증한다.

## 2. 범위

### 2.1 In scope (M1a)

- `POST /convert` SSE 핸들러 (`text/event-stream`)
- async 핸들러 ↔ 동기 `ConversionService` 오케스트레이션 (event pump)
- `ConcurrencyPool.cpu_executor` 연결 (M0 API 리뷰 권고 #3 흡수)
- url 입력 통합 (JSON `{url}` → 핸들러가 `fetch_url`을 executor에서 직접 호출 후 공통 변환 경로)
- 기존 TextConverter(txt/md/csv) 위에서 전 경로 end-to-end 검증

### 2.2 Out of scope (M1a)

- docx/pptx/xlsx/html 컨버터 → **M1b**
- GPU 세마포어 + `event: queued` 경로 → **M2** (Marker 도착 시. M1a엔 GPU 컨버터가 없음)
- `content_base64` 입력 → **M4** (MCP `convert_file`)
- Cache `delete`/`purge`의 raw `OSError` 정규화 (M0 리뷰 권고 #1 잔여) → 별도
- shutdown graceful drain → **후속** (M1a는 현행 `wait=False, cancel_futures=True` 유지)

## 3. 컴포넌트

| 파일 | 변경 | 책임 |
|---|---|---|
| `src/mdflow/api/convert.py` | **신규** | `register_convert_route(app)` — `POST /convert` SSE 핸들러, 입력 파싱, event pump |
| `src/mdflow/core/service.py` | 수정 (additive) | `convert()`를 `lookup()` + `run_conversion()`으로 분리, `convert()`는 thin wrapper로 존치 |
| `src/mdflow/api/app.py` | 수정 | `create_app()`에서 `register_convert_route(app)` 호출 |
| `tests/api/test_convert.py` | 신규 | SSE 라인 파싱 + event pump 단위 + 회귀 |

`core/events.py`의 6종 이벤트 모델(Started/Queued/Progress/Cached/Done/Error)은 **재사용**한다. M1a에서 `Queued`는 발행하지 않는다(GPU 경로 부재).

## 4. service 리팩토링 (additive)

기존 `ConversionService.convert(req, progress)`는 캐시 체크·감지·변환을 한 번에 처리하고 `cached` 플래그만 반환한다. SSE는 변환 *전에* "started(miss)"인지 "cached(hit)"인지 알아야 하므로, 내부 단계를 노출한다.

```text
lookup(req) -> (sha: str, detected_format: str, cached_result: ConversionResult | None)
    detect_format → compute_cache_key → cache.read

run_conversion(req, sha, detected_format, progress) -> ConvertResponse
    registry.select → converter.convert(progress) → metadata enrich → cache.write

convert(req, progress) -> ConvertResponse            # 기존 시그니처 불변
    lookup → hit이면 cached 응답 / miss면 run_conversion
```

**불변 조건**: 기존 `tests/test_service.py` 전부 그대로 통과 (회귀 0). `convert()`는 비-SSE 호출자(테스트, 향후 MCP)를 위해 존치한다.

## 5. 데이터 흐름 (`POST /convert`)

```text
1. 입력 파싱
   - multipart file → ConvertRequest(data, filename_hint)
   - JSON {url}     → url 보관 (convert_from_url 경로)
   - 둘 다 없음/둘 다 있음 → 스트림 시작 전 400

2. event pump 준비
   - q = asyncio.Queue()
   - loop = get_running_loop()
   - on_progress(stage, pct) = loop.call_soon_threadsafe(q.put_nowait, ProgressEvent(...))

3. 파일 입력:
   sha, fmt, cached = await run_in_executor(cpu_executor, service.lookup, req)
   ├ cached  → yield event: cached → yield event: done(cached 결과) → close
   └ miss    → yield event: started(converter, sha)
              → fut = run_in_executor(cpu_executor, service.run_conversion, req, sha, fmt, on_progress)
              → fut 완료까지 q를 drain하며 yield event: progress
              → yield event: done(결과 + conversion metadata) → close

4. url 입력 (핸들러가 직접 오케스트레이션 — 파일 경로와 동일 lifecycle):
   - fetched = await run_in_executor(cpu_executor, fetch_url, url, app.state.url_policy)
     (blocking httpx를 executor에서. fetch 단계는 yield event: progress("stage": "fetch"))
   - req = ConvertRequest(data=fetched.data, filename_hint=fetched.filename_hint,
                          content_type_hint=fetched.content_type)
   - 이후 3단계의 lookup/run_conversion 경로 그대로 (started/cached 구분 동일하게 동작)
   - done.metadata.fetch에 fetched의 request별 metadata 합성. 캐시 적중 시에도 현재 요청의
     source_url/effective_url 기준으로 합성 (PRD §5.1)
   - `url_pipeline.convert_from_url`은 SSE 경로에서 쓰지 않는다 (내부적으로 all-in-one convert()를
     호출해 started-first 구분 불가). 비-SSE/프로그램 호출자·테스트용으로 존치

5. 실패:
   - 변환/fetch 중 MdflowError/예외 → yield event: error{code, message, retryable} → close
   - HTTP status는 200 유지 (PRD §5 step 7). 클라이언트는 마지막 이벤트로 성공/실패 판단
```

`app.state.pool.cpu_executor`, `app.state.service`, `app.state.url_policy`는 M0 lifespan이 이미 구성해 둔 싱글톤을 사용한다.

## 6. 에러 처리

| 상황 | 처리 |
|---|---|
| 입력 없음 / 파일+url 동시 | 스트림 시작 전 → HTTP 400 |
| 포맷 감지 실패 | `event: error` (`FORMAT_DETECT_FAILED`) |
| 미지원 포맷 | `event: error` (`UNSUPPORTED_FORMAT`) |
| 변환 실패 | `event: error` (`CONVERSION_FAILED` 등) |
| URL fetch 실패 | `event: error` (`URL_*`) |
| 스트림 시작 후 모든 실패 | HTTP 200 유지, 스트림 내 `event: error` |

`MdflowError`는 `.code.value` / `.message` / `.retryable`을 error 이벤트 페이로드로 매핑한다.

## 7. 테스트 전략

- **SSE 라인 파싱** (httpx + TestClient):
  - txt 파일 업로드 → `started` → `done`, markdown 일치
  - 동일 입력 재요청 → `cached` → `done`
  - url 입력(mock transport, 실제 네트워크 없음) → fetch `progress` → `done`, `done.metadata.fetch` 존재
  - 미지원/실패 입력 → `error` 이벤트 + code 확인
  - 입력 없음 / 파일+url 동시 → 400
- **event pump 단위**: 스레드 콜백 → `call_soon_threadsafe` → queue → 이벤트 순서 보존
- **service 분리 회귀**: 기존 `test_service.py` 전부 통과 + `lookup`/`run_conversion` 직접 단위 테스트
- **전체 스위트 회귀 0**, ruff + format clean
- url 경로 테스트는 `mdflow.api.convert.fetch_url`을 monkeypatch해 canned `FetchResult`를 반환(실제 네트워크 없음). 라우트에 test 전용 transport seam을 추가하지 않는다 (불필요한 유연성 회피)

## 8. 미해결 / 후속 (M1a 밖)

- GPU 세마포어 + `event: queued` (M2)
- shutdown graceful drain — 진행 중 변환을 끝까지 기다릴지 정책 (후속)
- `content_base64` 입력 (M4)
- Cache `delete`/`purge` OSError 정규화 (별도)
- 사무 포맷 컨버터 docx/pptx/xlsx/html + 골든 출력 (M1b)
