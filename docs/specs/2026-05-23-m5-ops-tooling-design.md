# M5 — 운영 도구 (CLI / 메트릭 / Dockerfile / 테스트 매트릭스) 설계

**작성일**: 2026-05-23
**상태**: 설계 (writing-plans 입력 대기)
**선행**: M0\~M4(`v0.5.0-m4`). `create_app()`, `ConversionService`, `convert_from_url`, `build_registry`, `Cache.stats()`가 존재. M5는 이들 위의 운영 표면(CLI/메트릭/패키징/테스트 문서)을 추가한다.
**정본 상태**: `PROCESS_STATE.md` §11 (M5)

---

## 1. 목표 / 범위

PRD §12 + 마일스톤 M5의 운영 도구 4종을 구현한다. **M2b(Marker GPU) 보류**이므로 GPU 관련 부분(Dockerfile GPU 분기, 테스트 매트릭스 GPU 차원)은 **CPU 한정 + M2b 후속**으로 둔다.

### 1.1 In Scope (M5)

| 영역 | 내용 |
|---|---|
| **CLI** | `src/mdflow/cli.py` (Typer). `mdflow convert <file\|--url>` (단일 변환, stdout 또는 `-o`), `mdflow serve` (uvicorn). `[project.scripts] mdflow`. `mdflow-mcp`는 M4에서 이미 존재. |
| **메트릭** | in-process 카운터를 `/capabilities`의 `metrics` 키로 노출(요청 수·실패 수·실패율·평균 지연 + 캐시 적중률). `Metrics` 객체를 lifespan에서 생성, `/convert` 스트림을 감싸는 `_metered` 래퍼가 terminal SSE 이벤트(done/error)를 관찰해 단일 지점 기록. |
| **Dockerfile** | CPU 전용 이미지(`python:3.12-slim` + LibreOffice + `fonts-noto-cjk` + `pip install '.[hwp]'`). `CMD mdflow serve`. GPU/Marker 분기는 M2b 후속. |
| **테스트 매트릭스** | `docs/test-matrix.md` — 포맷 × (CPU) × OS deps × pytest marker × 테스트 위치 표. GPU(Marker) 차원은 M2b 보류 명시. |

### 1.2 Out of Scope (M5 비목표)

- **GPU Docker 분기 / Marker 이미지**: M2b 후속.
- **Prometheus/OpenTelemetry 메트릭**: v2(PRD §12). v1은 in-process counter만.
- **MCP 경로 메트릭**: `/capabilities` 메트릭은 HTTP `/convert` 경로만 집계. MCP(별도 runtime/stdio)는 v1 비집계(문서화). 
- **CLI 배치/병렬·watch 모드**: v1은 단일 파일/URL 변환 + serve. 배치는 후속.
- **Docker compose / 멀티 이미지 / CI 파이프라인 작성**: 테스트 매트릭스는 문서 + 기존 마커 정합성까지. CI YAML은 비목표(인프라 미지정).

---

## 2. 모듈 / 파일

```text
src/mdflow/cli.py                 신규: Typer 앱 (convert, serve)
src/mdflow/core/metrics.py        신규: Metrics (요청/실패/지연 카운터)
src/mdflow/api/convert.py         수정: stream()을 _metered로 감싸 terminal 이벤트 기록
src/mdflow/api/app.py             수정: lifespan에 app.state.metrics = Metrics()
src/mdflow/api/admin.py           수정: /capabilities에 "metrics" 키
Dockerfile                        신규: CPU 전용 이미지
.dockerignore                     신규
docs/test-matrix.md               신규: 포맷×deps×marker 매트릭스
pyproject.toml                    수정: typer 의존 + [project.scripts] mdflow
```

---

## 3. CLI (`mdflow`)

Typer 앱. composition(`build_registry`, `url_policy_from_settings`)을 재사용해 자체 runtime 구성(서버 불필요, 동기 변환).

```python
app = typer.Typer(help="mdflow — document to Markdown gateway")

@app.command()
def convert(
    file: Optional[Path] = typer.Argument(None, help="input file path"),
    url: Optional[str] = typer.Option(None, "--url", help="fetch & convert a URL"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="write markdown here (default: stdout)"),
):
    # exactly one of file/url
    settings = Settings(); registry = build_registry(settings); cache = Cache(settings.cache_dir)
    service = ConversionService(registry=registry, cache=cache)
    try:
        if url:
            out = convert_from_url(url, policy=url_policy_from_settings(settings), service=service)
            md = out.response.result.markdown
        else:
            data = file.read_bytes()
            md = service.convert(ConvertRequest(data=data, filename_hint=file.name)).result.markdown
    except MdflowError as e:
        typer.secho(f"[{e.code.value}] {e.message}", err=True, fg="red"); raise typer.Exit(1)
    if output: output.write_text(md, encoding="utf-8")
    else: typer.echo(md)

@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(create_app(), host=host, port=port)
```

- **입력 검증**: file/url 정확히 하나 아니면 `typer.BadParameter`/`Exit(2)`.
- **에러**: `MdflowError` → stderr `[CODE] message` + exit 1. file read `OSError` → exit 1.
- `[project.scripts]`: `mdflow = "mdflow.cli:app"` (Typer 앱은 호출 가능). `mdflow-mcp`는 유지.
- **CLI는 메트릭/풀 불필요**: 동기 1회 변환. ConcurrencyPool/Metrics 미사용.

---

## 4. 메트릭 (`/capabilities` counters)

### 4.1 `Metrics` (`core/metrics.py`)

```python
class Metrics:
    def __init__(self) -> None:
        self.requests = 0
        self.failures = 0
        self._latency_sum_s = 0.0
        self._latency_count = 0

    def record(self, *, success: bool, latency_s: float) -> None:
        self.requests += 1
        if not success:
            self.failures += 1
        self._latency_sum_s += latency_s
        self._latency_count += 1

    def snapshot(self) -> dict:
        avg_ms = (self._latency_sum_s / self._latency_count * 1000) if self._latency_count else 0.0
        return {
            "requests": self.requests,
            "failures": self.failures,
            "failure_rate": round(self.failures / self.requests, 4) if self.requests else 0.0,
            "avg_latency_ms": round(avg_ms, 2),
        }
```

- 단일 이벤트 루프에서 갱신되므로 락 불요(SSE 핸들러는 같은 루프). 정수/실수 증분만.

### 4.2 `_metered` 래퍼 (`api/convert.py`)

기존 `stream()` 내부 로직을 **건드리지 않고** 라우트에서 감싼다. SSE 청크는 `_sse()`가 `event: <name>\n...` 형태로 만들므로 terminal 이벤트를 prefix로 식별:

```python
async def _metered(gen, metrics):
    t0 = time.monotonic()
    outcome = "error"  # generator가 terminal 없이 닫히면(클라 disconnect) 실패로 집계
    try:
        async for chunk in gen:
            if chunk.startswith("event: done"):
                outcome = "done"
            elif chunk.startswith("event: error"):
                outcome = "error"
            yield chunk
    finally:
        metrics.record(success=(outcome == "done"), latency_s=time.monotonic() - t0)
```

라우트: `return StreamingResponse(_metered(stream(), request.app.state.metrics), media_type="text/event-stream")`.

- **단일 기록 지점**: terminal 이벤트가 stream()/_run_conversion_stream 어디서 나오든 청크 관찰로 일원화. 내부 5개 return 분기를 안 건드림(수술적).
- **disconnect**: 클라이언트가 중간에 끊으면 generator가 done 없이 닫힘 → finally에서 실패로 기록(보수적). `cached`+`done`(캐시 히트)도 `done`으로 성공 집계.

### 4.3 `/capabilities` 노출 (`api/admin.py`)

```python
"metrics": {**state.metrics.snapshot(), "cache_hit_rate": _hit_rate(state.cache.stats())},
```

- `cache_hit_rate` = `hit/(hit+miss)` (cache.stats의 hit_count/miss_count 사용, 0 division 가드). PRD "캐시 적중률" 충족.
- 기존 `cache` 키(entries/size_mb/hit_count/miss_count)는 유지.

### 4.4 lifespan 배선 (`api/app.py`)

`app.state.metrics = Metrics()`를 `_lifespan`에 추가.

---

## 5. Dockerfile (CPU 전용)

```dockerfile
FROM python:3.12-slim

# LibreOffice (doc/ppt), CJK fonts for soffice rendering. pyhwp uses lxml
# (no xsltproc/libxslt system dep needed).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-impress libreoffice-calc \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README* ./
COPY src ./src
RUN pip install --no-cache-dir ".[hwp]"

ENV MDFLOW_CACHE_DIR=/var/cache/mdflow
EXPOSE 8000
CMD ["mdflow", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

- `.[hwp]` = base deps(fastapi/uvicorn/fastmcp/pymupdf4llm/...) + pyhwp. doc/ppt는 LibreOffice subprocess.
- **GPU/Marker 분기 비목표**(M2b 후속): GPU 이미지는 `torch`+`marker-pdf`를 별도 stage/태그로 추가 예정.
- `.dockerignore`: `.venv`, `.git`, `__pycache__`, `tests`, `archive`, `docs` 등 제외.
- **빌드 검증 한계**: 이 호스트에서 LibreOffice 포함 이미지 빌드는 무겁고 GPU 부재로 완전 검증이 어렵다. Dockerfile은 정적으로 작성하고, 빌드/실행 검증은 별도 환경 후속(문서에 명시).

---

## 6. 통합 테스트 매트릭스 (`docs/test-matrix.md`)

문서로 작성. 각 포맷의 컨버터·테스트 위치·OS 의존·마커를 표로 정리하고, GPU(Marker) 행은 **M2b 보류**로 명시. 기존 마커(`requires_soffice`, `integration`, skip-if-absent, `requires_pyhwp_fixture`)와 정합. 별도 자동 테스트는 만들지 않는다(메타/문서 성격 — 사용자 합의). `tests/test_composition.py`가 이미 레지스트리 포맷 완전성을 잠그므로 매트릭스 문서가 그와 일치해야 한다.

---

## 7. 에러 / 보안

- CLI: `MdflowError` → stderr 코드 표시 + exit 1. 입력 검증 실패 → exit 2.
- 메트릭: 카운터는 PII/콘텐츠 미포함(수치만). URL query redaction은 로깅 영역(PRD §12, M5 비변경).
- Dockerfile: 무인증 v1 가정 유지. 메트릭/admin 엔드포인트도 무인증(컨테이너는 신뢰 네트워크 가정).

---

## 8. 테스트 전략

- **CLI** (`tests/test_cli.py`, `typer.testing.CliRunner`):
  - `convert <txt>` → exit 0, stdout에 변환 markdown.
  - `convert <txt> -o out.md` → 파일 기록.
  - `convert` (file/url 모두 없음 또는 모두 있음) → exit != 0.
  - `convert <bad>` (존재X) → exit != 0.
  - `--help`에 `convert`,`serve` 표시. (serve는 블로킹이라 직접 실행 안 함; uvicorn.run을 monkeypatch해 호출 인자만 검증하거나 --help만.)
- **메트릭** (`tests/api/test_capabilities`/신규 `tests/api/test_metrics.py`):
  - 초기 `/capabilities` metrics = requests 0.
  - `/convert` 성공 1회 후 requests 1, failures 0, avg_latency_ms > 0.
  - `/convert` 실패(미지원/garbage) 1회 후 failures 1, failure_rate 반영.
  - cache_hit_rate: 동일 입력 2회 → hit 반영.
- **Dockerfile**: pytest 비대상(빌드 무거움). 구문/내용은 리뷰로. 선택적으로 `docker --version` 있으면 `docker build` 스모크는 비목표.
- **테스트 매트릭스 문서**: 컨버터 집합이 `build_registry`와 일치하는지 육안/`test_composition`로 보장.
- 전체 `pytest` + `ruff` clean 유지(현재 277 passed/2 skipped 기준 증가).

---

## 9. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | `typer` 의존 + `[project.scripts] mdflow` | `pyproject.toml` |
| 1 | `Metrics` + `_metered` 래퍼 + lifespan 배선 + `/capabilities` metrics + 테스트 | `core/metrics.py`, `api/convert.py`, `api/app.py`, `api/admin.py` |
| 2 | `cli.py` (convert/serve) + CliRunner 테스트 | `cli.py`, `tests/test_cli.py` |
| 3 | `Dockerfile`(CPU) + `.dockerignore` | `Dockerfile`, `.dockerignore` |
| 4 | `docs/test-matrix.md` | 문서 |
| 5 | PROCESS_STATE 갱신 + M5 Codex 묶음 리뷰 + `v0.6.0-m5` 태그 | `PROCESS_STATE.md` |

---

## 10. 비범위 / 후속 (기록)

- **GPU Docker 이미지 / Marker**: M2b 후속.
- **MCP 경로 메트릭**: v1은 HTTP `/convert`만. MCP runtime에도 Metrics 주입은 후속.
- **Prometheus 익스포트, CI 파이프라인, CLI 배치**: v2/후속.
- **메트릭 thread-safety**: best-effort 단일 프로세스 카운터. `/convert` 루프에서 write, `/capabilities`(sync route, threadpool)에서 read — eventually consistent(중간값 순간 노출 무해). 멀티프로세스 집계는 v2.
- **CLI size cap 미적용 (Codex M5 권고 4, 의도적)**: HTTP/MCP는 `MDFLOW_MAX_INPUT_MB`로 서버를 보호하지만, CLI는 로컬 단발 도구라 사용자 자신의 파일 변환에 서버-보호 cap을 강제하지 않는다(local convenience). 세 transport 계약 통일이 필요하면 후속에서 옵션화.
