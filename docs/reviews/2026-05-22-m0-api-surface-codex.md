# mdflow M0 API surface 리뷰 - Codex

작성일: 2026-05-22
대상:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py`
- `/media/restful3/data/workspace/mdflow/tests/api/test_app.py`
- `/media/restful3/data/workspace/mdflow/tests/api/test_admin.py`
- `/media/restful3/data/workspace/mdflow/tests/api/conftest.py`
- `/media/restful3/data/workspace/mdflow/tests/test_m0_smoke.py`

검증:
- `.venv/bin/python -m pytest -q tests/api tests/test_m0_smoke.py` -> 13 passed
- `.venv/bin/ruff check src/mdflow/api/app.py src/mdflow/api/admin.py tests/api/test_app.py tests/api/test_admin.py tests/api/conftest.py tests/test_m0_smoke.py` -> All checks passed
- PRD/API 표면, URL handling 합의안, 의존 모듈(`settings`, `concurrency`, `capabilities`, `service`, `cache`, `url_pipeline`)을 실제 파일 기준으로 확인

## 차단

없음. 현재 묶음은 M0 완료 태그(`v0.0.1-m0`)를 막을 수준의 결함은 보이지 않습니다. composition root, admin surface, URL policy helper, 테스트 격리는 M0 골격 기준에 부합합니다.

## 권고

### 1. admin cache route에서 `MdflowError(CACHE_IO_ERROR)`가 구조화되지 않고 500으로 누출됩니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:27`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:41`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:50`

문제:
- `GET /cache/{sha256}`는 `ValueError`만 400으로 매핑합니다.
- `Cache.read()`는 오염된 `meta.json` 또는 읽기 I/O 실패를 `MdflowError(ErrorCode.CACHE_IO_ERROR)`로 올리지만, admin route에서는 catch하지 않습니다.
- 실제로 corrupt cache entry를 만든 뒤 `TestClient(..., raise_server_exceptions=False)`로 호출하면 HTTP 500 `Internal Server Error`가 됩니다. 응답에 mdflow error code/retryable 정보가 없습니다.
- `DELETE /cache/{sha256}`와 `POST /cache/purge`도 `shutil.rmtree()`/`iterdir()` 계열 `OSError`가 생기면 현재는 raw 500 경로입니다. 이 둘은 `Cache` 계층에서 아직 `CACHE_IO_ERROR`로 정규화하지 않으므로 admin에서 처리하려면 `OSError`도 별도 정책이 필요합니다.

권고:
- admin 전용 helper를 두고 `MdflowError`를 JSON HTTP 응답으로 변환하세요. 예: `{"code": e.code.value, "message": e.message, "retryable": e.retryable}`.
- `CACHE_IO_ERROR`는 admin 조회/삭제/정리 작업에서 보통 `503 Service Unavailable` 또는 `500` 중 하나로 명시 정책을 정하면 됩니다. PRD의 retryable 의미를 살리려면 503이 더 자연스럽습니다.
- 회귀 테스트를 추가하세요: corrupt `meta.json`을 심은 뒤 `/cache/{sha}`가 raw 500이 아니라 선택한 status와 `CACHE_IO_ERROR` body를 반환하는지 확인.

### 2. unknown-sha 404 테스트는 body까지 확인하면 route 부재와 더 잘 구분됩니다

위치:
- `/media/restful3/data/workspace/mdflow/tests/api/test_admin.py:23`
- `/media/restful3/data/workspace/mdflow/tests/api/test_admin.py:65`

현재 suite에는 `test_cache_write_then_get_returns_payload()`와 delete happy path가 있어 `/cache/{sha256}` route 자체가 사라지는 큰 회귀는 잡힙니다. 다만 unknown 404 테스트만 놓고 보면 FastAPI의 route-not-found 404로도 통과할 수 있습니다.

권고:
- unknown get/delete 테스트에서 `r.json()["detail"] == "cache miss"`까지 assert하면 "라우트는 존재했고, cache miss 분기까지 실행됐다"를 더 직접적으로 보장합니다.

### 3. `ConcurrencyPool`은 lifespan에 잘 놓였지만 아직 `ConversionService`와 연결되지는 않았습니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:58`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:67`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:37`

R3 대응 자체는 맞습니다. `ConcurrencyPool`이 async lifespan 내부에서 생성되어 semaphore loop-binding 위험을 피하고, `app.state.pool`로 노출됩니다.

다만 현재 `ConversionService`는 pool을 받지 않으므로 M0에서는 pool이 "준비된 singleton"일 뿐 변환 실행에 쓰이지 않습니다. 이는 M0 skeleton으로는 괜찮지만, M1 `/convert` SSE 구현 때 `app.state.pool`을 handler에서 직접 쓰거나 `ConversionService` 생성자에 명시적으로 주입하는 결정을 해야 합니다. 그렇지 않으면 CPU executor/GPU semaphore가 우회될 수 있습니다.

### 4. shutdown 정책은 M0에는 충분하지만 변환 실행이 붙으면 재검토가 필요합니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:70`
- `/media/restful3/data/workspace/mdflow/src/mdflow/runtime/concurrency.py:37`

`pool.shutdown()` 호출 자체는 누락 없이 들어가 있습니다. M0에서는 pool을 사용하는 요청 경로가 없어서 충분합니다.

M1 이후 CPU 변환 작업이 executor에서 돌게 되면 `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)`는 이미 실행 중인 작업을 기다리지 않습니다. FastAPI/Uvicorn shutdown lifecycle과 함께 "진행 중 변환을 끝까지 기다릴지, 중단할지" 정책을 정하고 테스트하는 것이 좋습니다.

## 메모

### 1. lifespan composition root는 M0 기준으로 적절합니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:49`

와이어 순서는 자연스럽습니다.

1. `Settings()`
2. `detect()` + boot log
3. `Registry()` + `TextConverter()`
4. `Cache(settings.cache_dir)`
5. `ConcurrencyPool(cpu_workers=capabilities.cpu_workers)`
6. `ConversionService(registry=registry, cache=cache)`
7. `url_policy_from_settings(settings)`
8. `app.state.*` 저장

`app.state.settings/capabilities/registry/cache/pool/service/url_policy` 노출도 후속 API/MCP route에서 공유 singleton을 꺼내 쓰기 좋은 형태입니다.

### 2. `url_policy_from_settings()` 매핑은 정확합니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:33`
- `/media/restful3/data/workspace/mdflow/tests/api/test_app.py:34`

6개 URL 설정 매핑은 맞습니다.

- `allow_private_urls` -> `UrlPolicy.allow_private_urls`
- `url_max_redirects` -> `max_redirects`
- `max_url_input_mb * 1024 * 1024` -> `max_bytes`
- `url_connect_timeout_s` -> `connect_timeout_s`
- `url_read_timeout_s` -> `read_timeout_s`
- `url_user_agent` -> `user_agent`

boot 시 한 번 구성해 `app.state.url_policy`에 저장하는 패턴도 적절합니다. URL fetch 정책이 request option이 아니라 서버 환경변수 기반이라는 합의안과도 일치합니다.

### 3. 테스트 격리는 충분합니다

위치:
- `/media/restful3/data/workspace/mdflow/tests/api/conftest.py:13`
- `/media/restful3/data/workspace/mdflow/tests/test_m0_smoke.py:40`

`tests/api/*`는 package-local autouse fixture로 `MDFLOW_CACHE_DIR`가 per-test tmp cache로 격리됩니다. `test_app.py`도 `tests/api` 아래라 적용됩니다. `tests/test_m0_smoke.py`는 별도 autouse fixture를 두고 있어 실제 `~/.cache/mdflow`를 건드리지 않습니다.

### 4. admin의 400/404 분기는 일관적입니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:25`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:39`

invalid sha는 `Cache._entry_dir()`의 `ValueError`를 400으로 바꾸고, well-formed sha의 cache miss는 404로 바꾸는 정책이 GET/DELETE에서 일관됩니다. `/cache/purge`는 sha 입력이 없으므로 해당 분기가 필요 없습니다.

### 5. M0 태그 적합성

M0 범위가 "골격 + txt/md/csv passthrough + `/healthz` + admin/cache visibility"라면 태그해도 되는 상태입니다. 단, 위 권고 1의 admin `MdflowError` 매핑은 작고 국소적인 보완이라 태그 직전에 처리하면 API 표면의 완성도가 더 좋아집니다.
