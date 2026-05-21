---
title: mdflow — 문서→Markdown 변환 API/MCP 서비스 설계
status: draft
date: 2026-05-21
author: Taeyoung Song
related: paperflow (sibling project)
---

# mdflow 설계 문서

## 1. 개요

`mdflow`는 다양한 문서 포맷(PDF, DOCX, PPTX, HTML, HWP, XLSX, 오래된 DOC/PPT 등)을 받아 LLM 소비에 적합한 Markdown으로 변환하는 서비스다. HTTP API와 MCP 서버를 동시에 제공하여 에이전트·RAG·웹 클라이언트 어디서든 단일 호출로 변환할 수 있게 한다.

PaperFlow가 *논문 단일 포맷에 대한 끝단 워크플로우(viewer 포함)*라면, mdflow는 *범용 변환 게이트웨이*다. 두 프로젝트는 독립적이며, mdflow는 추후 PaperFlow의 업스트림으로도 활용 가능하다.

### 1.1 목표

- 가능한 모든 일반 사무 문서 포맷을 Markdown으로 변환
- LLM이 바로 소비할 수 있는 **의미 구조 보존**(헤딩 레벨, 리스트, 표, 코드 블록)
- 단일 호출로 진행 상황과 결과를 함께 받는 SSE 스트리밍 API
- 동일 코드에서 stdio·Streamable HTTP 두 가지 MCP transport 제공
- GPU가 있으면 자동으로 고품질 경로(Marker), 없으면 경량 CPU 경로 사용
- 동일 입력 재요청 시 캐시로 즉시 응답

### 1.2 비목표 (Out of Scope, 적어도 v1에서는)

- 인증·권한·멀티테넌시 (PaperFlow와 별개 후속 작업)
- 시각 충실도 보존(인쇄용 PDF 재현 등)
- Markdown 편집 UI (PaperFlow viewer가 담당)
- 번역·요약 (입력 텍스트의 LLM 후처리는 호출자 책임)
- 임의 URL 크롤링/SPA 렌더링 (HTML 입력은 정적 문서 가정, URL 입력은 v1에서 단일 리소스 GET + 제한된 redirect 처리만 지원)
- URL 내 문서 발견/사이트별 변환 규칙 (예: HTML에서 PDF 링크 추출, arXiv/OpenReview/학술 publisher transformer, citation meta tag 해석은 호출자 또는 PaperFlow 책임)
- Headless browser/Chromium 기반 print-to-PDF, 사용자 지정 header/cookie 전달, 인증이 필요한 URL fetch

## 2. 사용 시나리오

### 2.1 MCP 도구로 변환 (가장 흔한 경로)

```text
사용자 → Claude/Codex → MCP tool convert_file(path="/tmp/report.docx")
        → mdflow MCP server → ConversionService
        → Markdown 반환
```

### 2.2 HTTP 클라이언트 SSE

```text
curl -N -X POST /convert -F file=@deck.pptx
event: started   data: {"converter":"pptx-python-pptx","gpu":false}
event: progress  data: {"stage":"slides","pct":50}
event: done      data: {"markdown":"# Slide 1...","metadata":{...}}
```

### 2.3 동일 파일 재요청 (캐시 적중)

```text
event: cached    data: {"sha256":"..."}
event: done      data: {"markdown":"...","metadata":{...}}
```

## 3. 아키텍처

```text
┌─────────────────────────────────────────────────────────────┐
│                   mdflow (단일 프로세스)                     │
│                                                             │
│  FastAPI HTTP API        FastMCP HTTP route                 │
│  /convert (SSE)          /mcp (streamable HTTP)             │
│         │                       │                           │
│         └──────────┬────────────┘    FastMCP stdio          │
│                    │                 (mdflow-mcp entrypt)   │
│                    ▼                       │                │
│             ┌──────────────────────────────┴──────┐         │
│             │       ConversionService             │         │
│             │  • format detect (magic + ext)      │         │
│             │  • cache lookup (sha256+opts)       │         │
│             │  • route → Converter                │         │
│             │  • event publisher (asyncio.Queue)  │         │
│             └─────┬──────────────────┬────────────┘         │
│      GPU semaphore(=1)         CPU ThreadPool(N)            │
│                ▼                       ▼                    │
│      ┌────────────────────────────────────────────┐         │
│      │  Converter Registry                        │         │
│      │  pdf→Marker(GPU)/PyMuPDF(CPU)              │         │
│      │  docx→Mammoth   pptx→PythonPptx            │         │
│      │  html→Trafilatura+Markdownify              │         │
│      │  xlsx→Openpyxl  txt/md→Passthrough         │         │
│      │  hwp,doc,ppt→LibreOfficeBridge→pdf 재진입  │         │
│      └────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
   $MDFLOW_CACHE_DIR (기본 ~/.cache/mdflow)
       <sha256>/
         result.md
         meta.json
         assets/*  (선택)
```

### 3.1 실행 모델 (Execution Model)

- 단일 FastAPI/Uvicorn 프로세스에서 HTTP API와 MCP HTTP를 함께 호스팅한다.
- stdio MCP는 `mdflow-mcp` 별도 엔트리포인트가 동일 `ConversionService`를 임포트해 stdio 위에서 노출한다.
- 변환 함수는 대부분 **동기 라이브러리**(mammoth, python-pptx, marker 등)이므로, FastAPI 핸들러는 `run_in_threadpool`로 위임한다.
- GPU를 쓰는 Marker 경로는 **`asyncio.Semaphore(1)`** 로 직렬화하여 VRAM 경쟁/누수를 방지한다(PaperFlow 경험 반영). CPU 컨버터는 N개 동시 실행 허용(`N = MDFLOW_CPU_WORKERS`, 기본=CPU 코어 수).
- 변환기는 진행률을 **콜백**으로 보고하고, `ConversionService`가 그 콜백을 SSE 이벤트로 펌프(publishes)한다.

### 3.2 GPU 자동 감지

부팅 시 `torch.cuda.is_available()`을 확인하여 `Capabilities` 싱글톤에 `gpu: bool`를 채운다. 환경변수 `MDFLOW_FORCE_CPU=1`이면 강제로 false. PDF 라우팅이 이 값을 보고 Marker/PyMuPDF를 선택한다. 부팅 로그에 다음 한 줄로 출력한다: `mdflow ready: gpu=true cuda=12.1 cpu_workers=8`.

## 4. 컴포넌트

| 모듈 | 책임 | 주요 의존 |
|---|---|---|
| `mdflow/api/app.py` | FastAPI 앱 팩토리, 라우터 등록, lifespan(`Capabilities` 초기화) | fastapi, sse-starlette |
| `mdflow/api/convert.py` | `POST /convert` SSE 핸들러 | — |
| `mdflow/api/admin.py` | `/healthz`, `/capabilities`, `/cache/*` | — |
| `mdflow/mcp/server.py` | FastMCP 인스턴스, HTTP+stdio 노출 | fastmcp |
| `mdflow/mcp/tools.py` | `convert_file`, `convert_url`, `list_formats`, `get_cached` | — |
| `mdflow/core/service.py` | `ConversionService` — 진입점, 라우팅, 캐시, 동시성, 이벤트 펌프 | — |
| `mdflow/core/registry.py` | `Converter` 추상 + 데코레이터 기반 등록, 디스패치 | — |
| `mdflow/core/cache.py` | sha256 기반 디스크 캐시, TTL, 통계 | — |
| `mdflow/core/events.py` | Pydantic 이벤트 모델 (`Started`/`Progress`/`Done`/`Error`/`Cached`/`Queued`) | pydantic |
| `mdflow/core/errors.py` | 표준 예외 + `code` enum | — |
| `mdflow/core/format_detect.py` | 확장자 + magic bytes 합의 | python-magic |
| `mdflow/runtime/capabilities.py` | GPU 감지, 환경변수 override | torch |
| `mdflow/runtime/concurrency.py` | GPU 세마포어, CPU ThreadPool 공유 인스턴스 | — |
| `mdflow/converters/base.py` | `Converter` 인터페이스 (`can_handle`, `convert`, `requires_gpu`) | — |
| `mdflow/converters/pdf.py` | Marker(GPU) → PyMuPDF(CPU) fallback, OCR math 정리 재활용 | marker-pdf, pymupdf |
| `mdflow/converters/docx.py` | mammoth + python-docx 보강 | mammoth, python-docx |
| `mdflow/converters/pptx.py` | python-pptx, 슬라이드별 섹션·노트 추출 | python-pptx |
| `mdflow/converters/html.py` | trafilatura(본문 추출) → markdownify | trafilatura, markdownify |
| `mdflow/converters/spreadsheet.py` | openpyxl → 시트별 MD 표 | openpyxl |
| `mdflow/converters/text.py` | txt/md/csv passthrough, 인코딩 감지(chardet) | chardet |
| `mdflow/converters/libreoffice.py` | `soffice --headless --convert-to pdf` 위임 후 pdf 컨버터 재진입 | subprocess |
| `mdflow/converters/hwp.py` | hwp5proc 우선 시도 → 실패 시 libreoffice 경로 | hwp5, libreoffice |
| `mdflow/cli.py` | `mdflow convert <file>`, `mdflow serve`, `mdflow-mcp` | typer |
| `tests/` | 포맷별 fixture, 라우터·서비스·캐시 단위 + 통합 | pytest, httpx |

### 4.1 Converter 인터페이스

```python
class Converter(Protocol):
    name: str                       # "pdf-marker", "docx-mammoth", ...
    formats: tuple[str, ...]        # 확장자 매핑, e.g. ("pdf",)
    requires_gpu: bool

    def can_handle(self, ctx: ConversionContext) -> bool: ...

    def convert(
        self,
        ctx: ConversionContext,
        progress: Callable[[str, int], None],
    ) -> ConversionResult: ...
```

`ConversionContext`는 입력 바이트·임시 파일 경로·옵션·메타데이터를 보유한다.
`ConversionResult`는 `{markdown, metadata, assets[]}` 구조이며 캐시에 그대로 저장된다.

## 5. 데이터 흐름 — `POST /convert`

1. **수신**: `multipart/form-data` 파일 또는 `application/json` `{url}` / `{content_base64, filename}` 수신
   - URL 입력은 §5.0 URL 입력 전처리를 통과한 뒤 다음 단계로 들어간다.
2. **포맷 감지**: 확장자/filename hint + Content-Type + magic bytes 교차검증. 불일치 시 magic 우선, 경고를 메타데이터에 기록
3. **캐시 키 계산**: `sha256(input_bytes || canonical_json(options))`
4. **캐시 적중**: `event: cached` → request별 metadata를 합성한 `event: done` 발행 후 스트림 닫음
5. **캐시 미스**:
   - 컨버터 라우팅: `Registry.select(format, capabilities)` → 가장 우선 순위 높은 `Converter`
   - `event: started` 발행
   - GPU 컨버터면 `gpu_semaphore.acquire()` — 즉시 못 잡으면 `event: queued` 발행
   - 변환 실행은 `loop.run_in_executor(cpu_pool, converter.convert, ctx, on_progress)`
   - 컨버터의 `on_progress` 콜백이 `event: progress` 발행
   - 완료 시 변환 결과를 캐시에 원자적으로 저장(tmp + os.replace)
   - `event: done` (markdown 본문 + 변환 metadata + request별 fetch metadata 포함) 발행 후 스트림 닫음
6. **컨버터 실패**:
   - 라우터에 정의된 fallback 체인을 순서대로 시도(상세는 §8.2)
   - 모든 단계가 실패하면 마지막 시도의 코드/메시지를 `event: error`로 보고
7. **에러**: SSE는 HTTP 200 유지(스트림 안에서만 에러). 클라이언트는 마지막 이벤트 종류로 성공/실패 판단.

### 5.0 URL 입력 전처리

`{url}` 또는 MCP `convert_url` 입력은 §5 본문 1단계 수신 직후, 2단계 포맷 감지 이전에 다음 fetch 단계를 통과한다. 이 단계의 출력은 "다운로드된 바이트/임시 파일 + fetch metadata"이며, 이후 흐름은 파일 입력과 동일하다.

1. URL을 파싱하고 scheme이 정확히 `http` 또는 `https`인지 확인한다. host가 없거나 userinfo(`user:pass@host`)가 있으면 `URL_INVALID`로 거부한다.
2. fragment는 fetch와 cache에 사용하지 않는다. 운영 로그에는 URL query를 기본 redaction한다.
3. DNS 이름 또는 IP literal을 연결 직전에 검증한다. `MDFLOW_ALLOW_PRIVATE_URLS=false`이면 loopback, private, link-local, multicast, unspecified, cloud metadata IP(예: `169.254.169.254`)를 `URL_BLOCKED`로 거부한다. IPv4와 IPv6 모두 적용한다.
4. mdflow 고정 `User-Agent`와 보수적 `Accept` header로 GET을 수행한다. 사용자 지정 header, cookie, Authorization 전달은 v1에서 지원하지 않는다.
5. redirect는 mdflow가 관리한다. 최대 `MDFLOW_URL_MAX_REDIRECTS`회까지 따르며, 각 hop마다 URL 파싱, scheme/host 검사, DNS/IP SSRF 검사를 반복한다. 초과 시 `URL_REDIRECT_LIMIT`.
6. connect/read timeout은 fetch 전용 환경변수로 제한한다. fetch timeout은 `URL_TIMEOUT`, 변환 timeout은 기존 `TIMEOUT`으로 구분한다.
7. 응답은 temp file로 streaming 저장하며 `MDFLOW_MAX_URL_INPUT_MB`를 넘으면 즉시 중단하고 `URL_TOO_LARGE`를 반환한다. Content-Length가 없거나 chunked 응답이어도 실제 수신 바이트 기준으로 제한한다.
8. 최종 HTTP status가 2xx가 아니면 `URL_NON_2XX`로 실패한다.
9. 포맷 감지는 magic bytes를 우선하고, 그 다음 `Content-Type`, `Content-Disposition` filename, URL path extension을 hint로 사용한다. 불일치 시 magic 우선이며 경고를 metadata에 기록한다.
10. `source_url`, `effective_url`, `http_status`, `content_type`, `content_length`, `content_disposition`, `filename_hint`, `fetched_at`, `redirect_count`, `fetch_warnings`를 request별 fetch metadata로 보존한 뒤 기존 포맷 감지/캐시/변환 흐름으로 넘긴다.

품질 게이트: v1에는 keyword 기반 bot/error hard reject를 넣지 않는다. `fetch_warnings`는 optional field로만 둔다. v1.1에서 classifier 또는 keyword gate를 별도 검토한다.

### 5.1 SSE 이벤트 스키마

```text
event: started   data: {"converter":"docx-mammoth","gpu":false,"sha256":"..."}
event: queued    data: {"reason":"gpu_busy","position":1}
event: progress  data: {"stage":"parse","pct":42,"detail":"슬라이드 13/30"}
event: cached    data: {"sha256":"...","cached_at":"2026-05-20T10:00:00Z"}
event: done      data: {"markdown":"# ...","metadata":{"input_kind":"url","fetch":{...},"conversion":{...}},"assets":[]}
event: error     data: {"code":"UNSUPPORTED_FORMAT","message":"...","retryable":false}
```

모든 페이로드는 `mdflow/core/events.py`의 Pydantic 모델에 정의되어 단일 출처(single source of truth)로 유지된다.

URL 입력의 `done.metadata.fetch`는 request별 metadata이며, 캐시된 변환 결과를 반환할 때도 현재 요청의 `source_url`/`effective_url`을 기준으로 합성된다.

## 6. API 표면

| 메소드 | 경로 | 용도 | 응답 |
|---|---|---|---|
| `POST` | `/convert` | 변환 (SSE 스트림) | `text/event-stream` |
| `GET` | `/healthz` | 라이브니스 프로브 | `{"ok":true,"uptime_s":...}` |
| `GET` | `/capabilities` | GPU/지원 포맷/캐시 통계 | JSON |
| `GET` | `/cache/{sha256}` | 캐시 항목 조회 | JSON or 404 |
| `DELETE` | `/cache/{sha256}` | 캐시 무효화 | `{"ok":true}` |
| `POST` | `/cache/purge` | 전체 캐시 비우기 | `{"removed":N}` |
| `POST` | `/mcp` | MCP Streamable HTTP 엔드포인트 | FastMCP 규격 |

요청 옵션(쿼리 또는 multipart `options` JSON):

```text
output_format=md          # 향후 확장 (예: "json", "structured")
preserve_images=false     # 이미지 추출+로컬 저장 여부
language_hint=ko          # OCR/번역 힌트
max_pages=                # PDF 페이지 제한
timeout_s=600             # 변환 타임아웃 상한
```

URL 입력 v1 제약:

- `url`은 `http`/`https`만 허용한다.
- 사용자 지정 header, cookie, Authorization 전달 옵션은 v1에서 제공하지 않는다.
- `follow_redirects` 옵션은 제공하지 않는다. mdflow가 고정 redirect 정책과 per-hop SSRF 검증을 적용한다.
- URL fetch 한도와 private network 허용 여부는 요청 옵션이 아니라 서버 환경변수로만 제어한다.

## 7. MCP 표면

| Tool | 입력 | 출력 |
|---|---|---|
| `convert_file` | `path: str`(서버 파일시스템) **또는** `content: bytes`, `filename: str`, `options?: dict` | `{markdown, metadata, sha256}` |
| `convert_url` | `url: str`, `options?: dict` | `{markdown, metadata, sha256}` |
| `list_formats` | — | `[{ext, converter, requires_gpu}]` |
| `get_cached` | `sha256: str` | `{markdown, metadata}` 또는 `null` |

- stdio 모드에서 `path` 입력은 클라이언트 파일시스템 접근을 의미한다. HTTP 모드에서는 `content`(base64) 또는 `convert_url`을 권장한다.
- `convert_url`은 mdflow 프로세스가 실행되는 환경의 네트워크에서 URL을 fetch한다. stdio MCP에서는 사용자의 로컬 실행 환경 네트워크, HTTP/Streamable HTTP에서는 서버 네트워크가 기준이다. 두 transport 모두 동일한 URL 검증과 SSRF 정책을 적용한다.
- SSE 진행 이벤트는 FastMCP `Context.report_progress`로 변환되어 MCP 진행 알림으로 전달된다.

## 8. 에러 처리

### 8.1 표준 에러 코드 (`mdflow.core.errors.ErrorCode` enum)

| 코드 | 의미 | retryable |
|---|---|---|
| `UNSUPPORTED_FORMAT` | 등록된 컨버터 없음 | false |
| `FORMAT_DETECT_FAILED` | 확장자/magic 모두 미상 | false |
| `INPUT_TOO_LARGE` | 입력 크기 한도 초과 | false |
| `CONVERSION_FAILED` | 컨버터 자체 실패 (라이브러리 예외) | true(다음 fallback 있을 때) |
| `LIBREOFFICE_UNAVAILABLE` | soffice 실행 불가 | false |
| `TIMEOUT` | 컨버터 타임아웃 초과 | true |
| `CACHE_IO_ERROR` | 캐시 쓰기/읽기 실패 | true(캐시 우회) |
| `INTERNAL` | 분류되지 않은 예외 | false |
| `URL_INVALID` | URL scheme/host/userinfo 등 기본 검증 실패 | false |
| `URL_BLOCKED` | SSRF 정책 또는 private network 정책으로 차단 | false |
| `URL_FETCH_FAILED` | DNS, 연결 실패, TLS 오류 등 fetch 실패 | true |
| `URL_TIMEOUT` | URL fetch connect/read timeout 초과 | true |
| `URL_TOO_LARGE` | URL 응답이 `MDFLOW_MAX_URL_INPUT_MB` 초과 | false |
| `URL_REDIRECT_LIMIT` | redirect 최대 횟수 초과 | false |
| `URL_NON_2XX` | 최종 HTTP status가 2xx가 아님 | false |

### 8.2 폴백 체인

- **PDF**: Marker(GPU) → PyMuPDF(CPU) → 실패 시 `CONVERSION_FAILED`
- **HWP**: hwp5proc → LibreOffice → PDF 컨버터(=Marker/PyMuPDF) → 실패 시 `CONVERSION_FAILED`
- **DOC/PPT(구버전 바이너리)**: LibreOffice → PDF 컨버터 → 실패 시 `CONVERSION_FAILED`

### 8.3 타임아웃 정책

- 기본 글로벌 한도: `MDFLOW_DEFAULT_TIMEOUT_S=600`
- 요청 옵션 `timeout_s`로 단축만 가능(연장 불가)
- LibreOffice 부팅: 60s 고정
- 변환기별 가이드라인: PDF는 페이지수×3s(캡 600s), 그 외는 30s 기본
- URL fetch timeout은 변환 timeout과 별도다. fetch 단계의 connect/read timeout은 `URL_TIMEOUT`, 변환 실행 timeout은 `TIMEOUT`으로 보고한다.

## 9. 캐시 정책

- 키: `sha256(input_bytes || canonical_options_json)` — 입력 바이트와 변환 옵션이 모두 같아야 적중. URL 입력도 다운로드된 바이트 기준으로 캐시하며 URL 문자열은 캐시 키에 포함하지 않는다.
- 위치: `$MDFLOW_CACHE_DIR` (기본 `~/.cache/mdflow`)
- 구조:
  ```text
  <sha256>/
    result.md         # 결과 Markdown
    meta.json         # converter, gpu, duration_ms, version, options, sha256 등 변환 불변 metadata
    assets/*          # preserve_images=true인 경우만
  ```
- 쓰기: tmp 디렉터리에 작성 후 `os.replace`로 원자적 이동
- TTL: 기본 무제한. `MDFLOW_CACHE_TTL_DAYS` 환경변수로 만료 가능
- 버전: `meta.json`에 `schema_version`과 `converter_version` 기록. 컨버터 패키지 버전이 다르면 캐시 무효화
- 통계: `/capabilities`가 `cache: {entries, size_mb, hit_count, miss_count}` 보고
- URL provenance: `source_url`, `effective_url`, HTTP status/header, `fetched_at` 등은 request별 fetch metadata로 취급한다. 동일 바이트를 여러 URL에서 받은 경우 하나의 변환 캐시를 공유하되, `event: done`/MCP 응답에서는 현재 요청의 fetch metadata를 변환 metadata와 합성한다.
- `/cache/{sha256}`는 기본적으로 변환 캐시의 불변 metadata만 반환한다. signed URL이나 query token 노출을 피하기 위해 request별 `source_url`/`effective_url`은 캐시 조회 응답에 저장/노출하지 않는다.

## 10. 테스트 전략

### 10.1 계층

- **단위**: 각 컨버터는 격리. `tests/fixtures/sample.{docx,pptx,html,...}` 골든 입력에 대해 출력 일부 라인을 스냅샷 비교
- **통합**: `httpx.AsyncClient` 기반 FastAPI TestClient로 `/convert` SSE 응답 라인 파싱, 포맷별 1개 이상 통과
- **MCP**: FastMCP 인메모리 클라이언트로 `convert_file`/`list_formats` 호출 검증
- **캐시**: 같은 입력+옵션 두 번째 요청이 `cached` 이벤트로 즉시 종료되는지 확인. 옵션 변경 시 재변환 확인
- **fallback**: PDF에서 Marker 강제 실패(모킹)→PyMuPDF로 폴백 검증
- **URL fetch**: invalid scheme/host/userinfo 거부, localhost/private/link-local/metadata IP 차단, public URL에서 private URL로 redirect 차단, redirect limit 초과, Content-Length 및 chunked 응답 크기 초과, non-2xx status 처리, Content-Type과 magic bytes 불일치, Content-Disposition filename hint, 같은 bytes를 다른 URL에서 받을 때 request별 provenance 합성 검증

### 10.2 CI 정책

- 기본 CI는 CPU 경로만 실행. Marker GPU 테스트는 `@pytest.mark.gpu`로 분리, 별도 GPU 러너에서 야간 실행
- LibreOffice 통합 테스트는 `@pytest.mark.libreoffice`로 표시, Docker CI에서만 실행
- 커버리지 게이트: `mdflow/core/`, `mdflow/converters/` 합산 ≥ 80%
- 코드 작성 순서는 TDD: 컨버터별로 fixture·assertion을 먼저 작성하고 통과시킨다

### 10.3 회귀 방지

- 골든 출력 파일을 `tests/golden/<converter>/<fixture>.md`에 커밋. 변경 시 diff 리뷰 강제
- URL fetch 테스트는 실제 외부 네트워크에 의존하지 않고 `httpx` mock transport 또는 로컬 테스트 서버로 재현한다. SSRF 테스트는 DNS/IP resolution을 모킹해 redirect별 검증을 포함한다.

## 11. 의존성

URL fetch는 기존 `httpx` 의존성을 사용한다. SSRF 검증은 표준 라이브러리(`ipaddress`, `socket`, `urllib.parse`)와 얇은 내부 helper로 구현하고, v1에서는 별도 crawler/browser 의존성을 추가하지 않는다.

`pyproject.toml`의 그룹별 분리 예시:

```toml
[project.dependencies]
fastapi
uvicorn[standard]
sse-starlette
fastmcp
pydantic
pydantic-settings
typer
httpx
python-multipart
python-magic
chardet

# 직접 컨버터 의존
mammoth
python-docx
python-pptx
openpyxl
trafilatura
markdownify
beautifulsoup4
pymupdf

[project.optional-dependencies]
gpu = ["marker-pdf", "torch"]
hwp = ["pyhwp"]
dev = ["pytest", "pytest-asyncio", "ruff", "mypy"]
```

OS 의존: `libreoffice`(Docker 이미지에 포함), `tesseract-ocr-*`(필요 시), `fonts-noto-cjk`(한국어 PDF 폴백 출력 시).

## 12. 운영 고려사항 (v1 한도)

- **로깅**: 표준 `logging` 모듈 사용. PaperFlow의 `print()` 패턴을 도입하지 않는다. JSON 라인 또는 텍스트 둘 다 환경변수로 선택
- **메트릭**: `/capabilities`에 누적 카운터(요청 수·캐시 적중률·평균 지연·변환 실패율). 본격 메트릭(Prometheus 등)은 v2
- **리소스 한도**: 입력 크기 `MDFLOW_MAX_INPUT_MB`(기본 200MB). URL 입력은 별도 `MDFLOW_MAX_URL_INPUT_MB`를 적용하며 기본값은 `MDFLOW_MAX_INPUT_MB` 이하로 둔다.
- **URL fetch 보안 기본값**:
  - `MDFLOW_ALLOW_PRIVATE_URLS=false` (기본). true는 로컬 개발/폐쇄망 배포에서만 사용한다.
  - `MDFLOW_URL_MAX_REDIRECTS=5`
  - `MDFLOW_URL_CONNECT_TIMEOUT_S=10`
  - `MDFLOW_URL_READ_TIMEOUT_S=30`
  - `MDFLOW_URL_USER_AGENT="mdflow/1.0 (+https://github.com/...)"` 형태의 고정 UA
  - URL query는 운영 로그에서 기본 redaction한다.
- **VRAM 정리**: PaperFlow의 `del model; gc.collect(); torch.cuda.empty_cache()` 패턴을 PDF 컨버터에 그대로 적용. 단일 세마포어가 직렬화하므로 한 번에 한 모델만 살아 있음을 보장

## 13. 미해결/추후 결정 사항

- **인증**: v1은 무인증. 후속 작업에서 PaperFlow 인증 모델(또는 별도 토큰)을 통합 검토
- **결과 후처리**: 한국어 번역·요약 통합 여부 — 현재는 비목표. mdflow는 변환만, 번역은 호출자(혹은 PaperFlow)가 담당
- **이미지/asset 반환**: v1은 `preserve_images=false` 기본. 어떻게 클라이언트에 노출할지(URL, base64) v1.1에서 결정
- **URL 입력의 SPA/Headless 대응**: Headless Chrome/Chromium 기반 렌더링 또는 print-to-PDF는 v1 비목표. v1.1 이후 별도 sandbox/resource-limit 설계와 함께 검토
- **URL 품질 게이트 고도화**: custom 200 bot/error page 감지, keyword/classifier 기반 reject, converter별 empty-output 품질 평가는 v1.1에서 검토. v1은 HTTP status, size, format detect 중심
- **인증이 필요한 URL fetch**: 사용자 지정 header/cookie/Authorization 전달은 v1 비목표. v1.1 이후 credential store, allowlist, 감사 로그와 함께 재검토
- **도메인 allowlist/blocklist 정책**: v1은 기본 SSRF 차단과 `MDFLOW_ALLOW_PRIVATE_URLS`만 제공한다. 운영자 정의 allowlist/blocklist는 v1.1에서 검토

## 14. 마일스톤 제안 (참고)

| M | 범위 | 산출물 |
|---|---|---|
| M0 | 골격 | `pyproject.toml`, `mdflow.core`, `Converter` 인터페이스, `txt/md/csv` passthrough, `/healthz` |
| M1 | 사무 포맷 | docx·pptx·xlsx·html 컨버터, SSE 스트림, 캐시 |
| M2 | PDF | Marker(GPU) + PyMuPDF(CPU) 폴백, 자동 감지 |
| M3 | LibreOffice 폴백 | doc/ppt/hwp, fallback 체인 |
| M4 | MCP | FastMCP 통합, stdio + HTTP, MCP 진행 알림 |
| M5 | 운영 도구 | CLI, Dockerfile, 메트릭, 통합 테스트 매트릭스 |

각 M은 별도 implementation plan으로 분해될 예정.
