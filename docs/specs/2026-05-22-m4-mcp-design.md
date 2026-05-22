# M4 — MCP 서버 (FastMCP) 설계

**작성일**: 2026-05-22
**상태**: 설계 (writing-plans 입력 대기)
**선행**: M0\~M3b. `ConversionService`(bytes-in/response-out), `convert_from_url`(URL 경로), `Registry.list_formats()`, `Cache.read()`가 이미 존재하고 검증됨. M4는 이들을 FastMCP tool로 노출만 한다(변환 로직 신규 없음).
**정본 상태**: `PROCESS_STATE.md` §10 (M4)
**검증된 환경**: `fastmcp 3.3.1`(+ `mcp 1.27.1`) 설치됨. `FastMCP.tool` 데코레이터 / `Context.report_progress(progress, total, message)`(async) / `FastMCP.run(transport=...)` / `FastMCP.http_app(path=...)` 모두 확인.

---

## 1. 목표 / 범위

### 1.1 목표

PRD §7의 **MCP 표면**을 구현한다. 동일 `ConversionService`를 두 transport(stdio + Streamable HTTP)로 노출하고, 4개 tool을 제공한다. SSE 진행 이벤트와 동등한 진행 신호를 `Context.report_progress`로 전달한다.

### 1.2 In Scope (M4)

- **`src/mdflow/mcp/server.py`** — `build_mcp(settings=None) -> FastMCP` (composition root) + `main()` (stdio entrypoint).
- **`src/mdflow/mcp/tools.py`** — 4 tool 등록 함수 `register_tools(mcp, runtime)`.
- **4개 tool** (PRD §7):
  | tool | 입력 | 출력 |
  |---|---|---|
  | `convert_file` | `filename: str`, `content_base64: str\|None`, `path: str\|None`, `options?: dict` (content_base64 / path 중 정확히 하나) | `{markdown, metadata, sha256}` |
  | `convert_url` | `url: str`, `options?: dict` | `{markdown, metadata, sha256}` |
  | `list_formats` | — | `[{ext, converter, requires_gpu}]` |
  | `get_cached` | `sha256: str` | `{markdown, metadata}` 또는 `None` |
- **stdio entrypoint** `mdflow-mcp` (`[project.scripts]` → `mdflow.mcp.server:main`).
- **Streamable HTTP 마운트**: `create_app()`가 `build_mcp().http_app(path="/mcp")`를 FastAPI에 마운트(lifespan 결합).
- **진행 알림**: 변환의 동기 progress 콜백을 `asyncio.run_coroutine_threadsafe(ctx.report_progress(...), loop)`로 이벤트 루프에 마샬링(SSE 핸들러의 `call_soon_threadsafe` 패턴과 동형).
- **공유 composition**: 컨버터 등록을 `build_registry(settings)`로 추출해 HTTP lifespan(`api/app.py`)과 MCP가 **동일 레지스트리 구성**을 공유(드리프트 방지).
- **신규 core 의존**: `fastmcp`.

### 1.3 Out of Scope (M4 비목표)

- **GPU 직렬화(`gpu_semaphore`)의 MCP 적용**: 현재 `requires_gpu=True` 컨버터가 등록돼 있지 않다(M2b Marker 보류). MCP tool은 `service.convert`를 직접 호출(내부 lookup+run)하며 GPU 게이팅을 하지 않는다. **M2b가 GPU 컨버터를 추가할 때 SSE(`api/convert.py`)와 MCP의 GPU 직렬화를 함께 재설계**한다. (지금 MCP에 GPU 오케스트레이션을 넣는 것은 직렬화할 대상이 없는 과설계 — YAGNI.)
- **인증/권한**: v1 비목표(PRD §1.3). MCP HTTP도 무인증.
- **MCP resources / prompts**: v1은 tool만.
- **stdio `path` 입력의 샌드박싱**: stdio 모드에서 `path`는 mdflow 프로세스 파일시스템을 읽는다(PRD §7: stdio는 클라이언트 로컬 실행 가정). 경로 제한/allowlist는 비목표(무인증 v1 가정과 일관). HTTP 모드에서는 `content_base64`/`convert_url` 권장, `path`는 서버 파일시스템 접근이므로 호출자 책임.

---

## 2. 아키텍처 / 모듈

```text
src/mdflow/mcp/__init__.py        신규 (빈 패키지)
src/mdflow/mcp/server.py          신규: build_mcp(), main() (stdio)
src/mdflow/mcp/tools.py           신규: register_tools(mcp, runtime)
src/mdflow/runtime/composition.py 신규: build_registry(settings) -> Registry
src/mdflow/api/app.py             수정: lifespan이 build_registry 사용 + /mcp 마운트
pyproject.toml                    수정: dependencies += fastmcp; [project.scripts] mdflow-mcp
```

### 2.1 공유 composition (`runtime/composition.py`)

```python
def build_registry(settings: Settings) -> Registry:
    registry = Registry()
    registry.register(TextConverter())
    registry.register(DocxConverter())
    registry.register(PptxConverter())
    registry.register(XlsxConverter())
    registry.register(HtmlConverter())
    registry.register(PdfConverter())
    registry.register(LibreOfficeConverter(timeout_s=settings.soffice_timeout_s))
    registry.register(HwpConverter())
    return registry
```

`api/app.py`의 `_lifespan`은 인라인 7줄 등록을 `registry = build_registry(settings)` 한 줄로 대체한다. **이유**: 새 컨버터(M3a/M3b가 그랬듯)를 추가할 때 HTTP와 MCP 두 곳을 동기화하지 않으면 레지스트리가 갈라진다. 단일 소스로 묶어 회귀를 막는다. 이것은 수술적 추출(동작 불변, 등록 순서 동일)이다.

### 2.2 MCP runtime (`Runtime` 번들)

`build_mcp`는 lifespan과 동일하게 런타임 싱글톤을 만든다:

```python
@dataclass
class Runtime:
    settings: Settings
    service: ConversionService
    cache: Cache
    registry: Registry
    url_policy: UrlPolicy

def build_mcp(settings: Settings | None = None) -> FastMCP:
    settings = settings or Settings()
    registry = build_registry(settings)
    cache = Cache(settings.cache_dir)
    runtime = Runtime(
        settings=settings,
        registry=registry,
        cache=cache,
        service=ConversionService(registry=registry, cache=cache),
        url_policy=url_policy_from_settings(settings),
    )
    mcp = FastMCP("mdflow")
    register_tools(mcp, runtime)
    return mcp
```

`url_policy_from_settings`는 `api/app.py`에 이미 있다 → `runtime/composition.py`로 함께 이동하거나 import. (드리프트 방지 차원에서 composition.py로 이동하고 app.py가 import하는 편이 일관 — 계획에서 결정.)

---

## 3. Tool 동작 (`mcp/tools.py`)

모든 tool은 async. 동기 `ConversionService`는 `loop.run_in_executor(None, ...)`로 오프로드(이벤트 루프 비블로킹). 진행은 §4 브리지로 전달.

### 3.1 `convert_file`

```python
@mcp.tool
async def convert_file(filename: str, content_base64: str | None = None,
                       path: str | None = None, options: dict | None = None,
                       ctx: Context = None) -> dict:
    if (content_base64 is None) == (path is None):
        raise ToolError("provide exactly one of: content_base64 or path")
    if content_base64 is not None:
        data = base64.b64decode(content_base64)
    else:
        data = Path(path).read_bytes()
    max_bytes = runtime.settings.max_input_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ToolError(f"input exceeds MDFLOW_MAX_INPUT_MB ({runtime.settings.max_input_mb} MB)")
    req = ConvertRequest(data=data, filename_hint=filename, options=options or {})
    resp = await _run(ctx, lambda p: runtime.service.convert(req, p))
    return {"markdown": resp.result.markdown, "metadata": resp.result.metadata, "sha256": resp.sha256}
```

- `content_base64`/`path` 정확히 하나 — 아니면 `ToolError`(MCP 표준 에러).
- 크기 cap은 HTTP `/convert`와 동일(`MDFLOW_MAX_INPUT_MB`).
- `MdflowError`는 `_run`에서 `ToolError`로 변환(§5).

### 3.2 `convert_url`

```python
@mcp.tool
async def convert_url(url: str, options: dict | None = None, ctx: Context = None) -> dict:
    out = await _run(ctx, lambda p: convert_from_url(
        url, policy=runtime.url_policy, service=runtime.service, options=options or {}, progress=p))
    resp, fetch = out.response, out.fetch
    meta = {**resp.result.metadata, "fetch": fetch, "input_kind": "url"}
    return {"markdown": resp.result.markdown, "metadata": meta, "sha256": resp.sha256}
```

- 동일 URL 검증·SSRF 정책(`url_policy`)을 HTTP와 공유(PRD §7: 두 transport 동일 정책).
- fetch metadata를 응답 metadata에 합성(합의안 §3.7, `_done_event`와 동일 규칙).

### 3.3 `list_formats`

```python
@mcp.tool
async def list_formats() -> list[dict]:
    return runtime.registry.list_formats()
```

`Registry.list_formats()`가 이미 `[{ext, converter, requires_gpu}]`를 반환 → 그대로.

### 3.4 `get_cached`

```python
@mcp.tool
async def get_cached(sha256: str) -> dict | None:
    if not _is_sha256(sha256):
        raise ToolError("sha256 must be 64 hex chars")
    cached = runtime.cache.read(sha256)
    if cached is None:
        return None
    return {"markdown": cached.markdown, "metadata": cached.metadata}
```

- `_is_sha256`: 64 hex 검증(admin `GET /cache/{sha}`의 검증과 동일 규칙).
- `cache.read`의 `CACHE_IO_ERROR`(오염 meta) → `_run` 밖이지만 동일하게 `ToolError`로 매핑(§5).

---

## 4. 진행 알림 브리지 (`_run` 헬퍼)

```python
async def _run(ctx, call):
    loop = asyncio.get_running_loop()

    def on_progress(stage: str, pct: int) -> None:
        if ctx is not None:
            # fire-and-forget; report_progress no-ops if client sent no progressToken
            asyncio.run_coroutine_threadsafe(ctx.report_progress(pct, 100, stage), loop)

    try:
        return await loop.run_in_executor(None, lambda: call(on_progress))
    except MdflowError as e:
        raise ToolError(f"[{e.code.value}] {e.message}") from e
```

- 컨버터의 동기 progress 콜백을 `run_coroutine_threadsafe`로 루프에 마샬링(SSE의 `call_soon_threadsafe`와 동형, thread→loop 안전).
- `report_progress`는 클라이언트가 `progressToken`을 안 보냈으면 FastMCP가 안전하게 무시 → 콜백은 항상 호출 가능.
- fire-and-forget: 워커 스레드가 progress 보고 완료를 기다리지 않음(진행은 best-effort, 변환 결과가 정본).

---

## 5. 에러 처리

| 상황 | MCP 표면 |
|---|---|
| 입력 검증(둘 다/둘 다 아님, bad sha, 크기 초과) | `ToolError`(설명 메시지) |
| 변환/fetch `MdflowError`(CONVERSION_FAILED, HWP_UNAVAILABLE, URL_*, FORMAT_DETECT_FAILED, …) | `_run`이 `ToolError("[CODE] message")`로 변환 |
| 캐시 오염(`CACHE_IO_ERROR`) | `ToolError` |

- MCP는 SSE처럼 스트리밍 error 이벤트가 아니라 tool 호출 예외(`ToolError`)로 실패를 표면화. `MdflowError`의 구조화 코드를 메시지 prefix `[CODE]`로 보존.
- `ConversionService.run_conversion`이 이미 비-`MdflowError`를 `CONVERSION_FAILED`로 wrap하므로 tool 레벨에서 추가 broad except 불요(§6 계약 재사용).

---

## 6. Transport 배선

### 6.1 stdio (`mdflow-mcp`)

```python
def main() -> None:
    build_mcp().run()  # 기본 transport=stdio
```

`[project.scripts]` `mdflow-mcp = "mdflow.mcp.server:main"`. 별도 프로세스로 동일 `ConversionService`를 stdio 위에 노출(PRD §3).

### 6.2 Streamable HTTP (`/mcp`)

`create_app()`이 `build_mcp().http_app(path="/mcp")`를 마운트. FastMCP http_app은 자체 lifespan을 가지므로 **FastAPI lifespan과 결합**해야 한다(FastMCP 권장 패턴: `app = FastAPI(lifespan=combined)` 또는 `app.mount` + `app.router.lifespan_context` 결합). 계획에서 정확한 결합 코드를 검증한다.

- v1에서 HTTP `/mcp`는 in-memory 클라이언트 테스트로 커버되는 tool 로직 위의 **배선**이다. 마운트가 복잡하면 stdio + tool(in-memory) 우선, HTTP 마운트는 동일 milestone 내 후속 슬라이스로 분리 가능.

---

## 7. 의존성

- **신규 core 의존**: `fastmcp`(`pyproject.toml [project.dependencies]`). `mcp`를 transitive로 끌어옴(검증: fastmcp 3.3.1 + mcp 1.27.1).
- `[project.scripts]` 추가: `mdflow-mcp = "mdflow.mcp.server:main"`.
- 시스템 의존 없음.

---

## 8. 테스트 전략

- **FastMCP in-memory client** (PRD §10): `from fastmcp import Client`; `async with Client(build_mcp(settings)) as client: await client.call_tool("convert_file", {...})`. 실제 transport 없이 tool round-trip 검증.
- **캐시 격리**: MCP 테스트도 `MDFLOW_CACHE_DIR`을 per-test tmp로 리다이렉트(기존 `tests/api/conftest.py` autouse fixture 패턴 재사용 — `tests/mcp/conftest.py` 신설 또는 공유).
- 테스트 케이스:
  - `convert_file` content_base64(txt) → `{markdown, metadata, sha256}`, markdown 일치.
  - `convert_file` path(임시파일) → 동일.
  - `convert_file` 둘 다/둘 다 아님 → `ToolError`.
  - `convert_file` 크기 초과 → `ToolError`.
  - `convert_url` → `fetch_url` monkeypatch(또는 httpx MockTransport)로 bytes 주입 → markdown + metadata.fetch 합성 확인.
  - `convert_url` SSRF 차단(`URL_BLOCKED`) → `ToolError`.
  - `list_formats` → hwp/doc/ppt/pdf/docx/... 행 포함.
  - `get_cached` 히트(먼저 convert로 채움) / 미스(None) / bad sha(`ToolError`).
  - 변환 실패(monkeypatch converter raise) → `ToolError("[CONVERSION_FAILED] ...")`.
  - `build_registry` 등록 완전성(HTTP lifespan과 동일 컨버터 집합).
- **HTTP 마운트 스모크**: `create_app()`에 `/mcp` route 존재 + lifespan 기동(TestClient). (in-memory가 tool 로직을 커버하므로 스모크 수준.)
- 전체 `pytest` + `ruff` clean 유지(현재 262 passed/2 skipped 기준 증가).

---

## 9. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | `fastmcp` 의존 + `[project.scripts]` mdflow-mcp | `pyproject.toml` |
| 1 | `build_registry` 추출(+`url_policy_from_settings` 이동) + app.py lifespan 사용 + 등록 완전성 회귀 | `runtime/composition.py`, `api/app.py` |
| 2 | `build_mcp` + Runtime + `_run` 진행 브리지 + `list_formats`/`get_cached` tool | `mcp/server.py`, `mcp/tools.py` |
| 3 | `convert_file`(base64/path/검증/크기) tool + in-memory 테스트 | `mcp/tools.py`, 테스트 |
| 4 | `convert_url` tool(+SSRF) + 에러 매핑(`ToolError`) 테스트 | `mcp/tools.py`, 테스트 |
| 5 | `/mcp` HTTP 마운트(lifespan 결합) + 스모크 + stdio `main` | `api/app.py`, `mcp/server.py` |
| 6 | PROCESS_STATE 갱신 + M4 Codex 묶음 리뷰 + `v0.5.0-m4` 태그 | `PROCESS_STATE.md` |

---

## 10. 비범위 / 후속 (기록)

- **MCP GPU 직렬화**: M2b(Marker) 합류 시 SSE+MCP 공통 GPU 게이팅 재설계.
- **MCP resources/prompts, 인증**: v1 비목표.
- **stdio `path` 샌드박싱**: 무인증 v1 가정. HTTP는 content_base64/convert_url 권장.
- **진행 세분화**: report_progress는 best-effort(progressToken 없으면 no-op). 결과가 정본.
