# M2 — PDF 컨버터 (CPU 경로 + GPU 라우팅 배관) 설계

**작성일**: 2026-05-22
**상태**: 설계 (브레인스토밍 산출물 — writing-plans 입력 대기)
**선행**: M1a SSE 인프라(Codex 최종 승인), M1b 사무 컨버터(`v0.1.0-m1b`, Codex 차단 0). 본 설계는 M1a SSE 경로 + M1b 컨버터 패턴 위에 PDF를 얹는다.
**정본 상태**: `PROCESS_STATE.md` §8 (M2)

---

## 1. 목표 / 범위

### 1.1 목표

`POST /convert`가 현재 txt/md/csv/docx/pptx/xlsx/html를 처리한다. M2는 **PDF를 Markdown으로 변환**하고, **GPU 컨버터를 위한 SSE 라우팅 배관**(GPU 세마포어 직렬화 + `queued` 이벤트)을 `convert.py`에 처음으로 끼운다.

핵심 가치(PRD §1): **의미 구조 보존(헤딩/리스트/표) > 시각 충실도.**

### 1.2 In Scope (M2 = "M2a")

- **PDF CPU 컨버터** `pdf-pymupdf4llm` — `pymupdf4llm`로 PDF bytes → 구조 보존 Markdown. `requires_gpu=False`.
- **GPU 라우팅 배관** (실제 GPU 소비자 없이, fake 컨버터로 검증):
  - `convert.py`의 miss 경로에서 `lr.converter.requires_gpu`가 True면 `ConcurrencyPool.gpu_lock()`으로 직렬화.
  - GPU 세마포어가 이미 점유 중이면 `started` 이전에 `queued` 이벤트 1회 방출.
  - VRAM 1-모델-1-프로세스 불변식은 세마포어(1)가 강제 (M1a `ConcurrencyPool`가 이미 보유, 현재까지 미사용).
- **Fallback-chain = 능력 게이팅 + 등록 순서** (Codex M0 권고 #11 해소): 별도 체인 실행기를 만들지 않는다. 기존 `Registry.select`(first-wins + `can_handle`)를 그대로 쓰되, GPU 컨버터(M2b Marker)가 `can_handle`에서 GPU 가용성을 게이팅하면 first-wins가 곧 "Marker(GPU) → PyMuPDF(CPU)" 순서 선택이 된다. M2a엔 PDF 컨버터가 PyMuPDF 1개뿐이라 체인 길이 1.
- 골든 테스트: 코드 생성 PDF fixture + `tests/golden/pdf/sample.md` 전체-파일 비교. `/convert` SSE 통합 1건. GPU 배관은 fake `requires_gpu=True` 컨버터로 `queued`/세마포어 직렬화 검증.
- 신규 의존성: `pymupdf4llm`(PyMuPDF 동반) — **core** 의존(CPU 베이스라인은 항상 존재).

### 1.3 Out of Scope (M2a 비목표)

- **Marker 실제 통합 (GPU 고품질 경로) → 별도 슬라이스 "M2b"**. 이 호스트엔 GPU/torch가 없어 실행·검증 불가. M2b에서 `[gpu]` extras(`marker-pdf`, `torch`) + `pdf-marker` 컨버터(`requires_gpu=True`, `can_handle`에서 GPU 게이팅) + PaperFlow VRAM 정리 패턴(`del model; gc.collect(); torch.cuda.empty_cache()`) 추가. 본 설계의 GPU 배관에 그대로 끼워진다.
- 스캔 PDF OCR (PyMuPDF는 텍스트 레이어만; 스캔본은 빈/희박 출력 → v1 한계로 허용, metadata에 기록 가능).
- 이미지/자산 바이트 추출(M1b와 동일하게 드롭).
- LibreOffice/doc/ppt/hwp(M3), MCP(M4).
- client disconnect 시 GPU task 취소(Codex M1a 권고 #2 DEFER 유지).

---

## 2. 아키텍처 / 모듈

기존 `Converter` Protocol(`converters/base.py`)을 그대로 구현. M1b 컨버터들이 참조 패턴.

```text
src/mdflow/converters/
├── ... (기존)
└── pdf.py            신규: PdfConverter  name="pdf-pymupdf4llm"  formats=("pdf",)  requires_gpu=False
```

```text
src/mdflow/api/convert.py   수정: miss 경로에 GPU 분기(gpu_lock + queued) 추가
src/mdflow/api/app.py       수정: lifespan에 PdfConverter 등록
pyproject.toml              수정: pymupdf4llm 추가
```

GPU 배관은 `convert.py` `stream()`의 miss 경로에만 영향을 준다. cached 경로(cached→done)와 CPU 컨버터(PyMuPDF 포함 기존 전부)는 기존 흐름 유지.

---

## 3. PDF 컨버터 동작 (`pdf-pymupdf4llm`)

- `import pymupdf4llm`, `import fitz`(PyMuPDF). `fitz.open(stream=ctx.data, filetype="pdf")`로 bytes를 연다(임시 파일 불필요).
- `md = pymupdf4llm.to_markdown(doc)` — 폰트 크기 휴리스틱으로 헤딩/리스트/표를 Markdown으로. `doc.close()`는 `try/finally`로 보장(except 없음 — M1b spreadsheet와 동일, §6 준수).
- progress: `("parse",10)` → `to_markdown` → `("render",60)` → `("done",100)`. (pymupdf4llm가 단일 호출이라 페이지별 스트리밍은 v1 비목표; 거친 단계만.)
- 반환 `ConversionResult(markdown=md.strip(), metadata={"pages": doc.page_count, "engine": "pymupdf4llm"})`.
- **컨버터는 자체 try/except로 라이브러리 예외를 삼키지 않는다**(§6). 손상 PDF → fitz/pymupdf4llm 예외 전파 → `run_conversion`이 `CONVERSION_FAILED`로 wrap.

---

## 4. GPU 라우팅 배관 (convert.py)

현재 miss 경로(M1a):

```text
yield started
task = ensure_future(run_in_executor(cpu_executor, run_conversion, ...))
async for ev in _drain_until_done(q, task): yield progress
yield done   # 또는 error
```

M2 변경 — miss 경로를 작은 헬퍼로 감싼다:

- `if lr.converter.requires_gpu:`
  - `if pool.gpu_semaphore.locked():` → `yield _sse("queued", Queued(reason="gpu_busy", position=<대기 추정치>))` (1회).
  - `async with pool.gpu_lock():`  ← 세마포어 획득(점유 중이면 여기서 대기) 후
    - `yield started` → run_conversion(cpu_executor) → drain progress → done/error.
- `else:` (CPU 컨버터) → 기존 흐름 그대로(`started` → … → done).

설계 포인트:
- **`queued`는 `started` 이전**에만 방출(GPU 대기 알림). 세마포어가 즉시 가용이면 `queued` 없음.
- `position`은 best-effort(현재 대기자 수 추정; 단일 세마포어라 보통 1). 정밀 큐 길이는 비목표.
- GPU 컨버터의 sync 라이브러리(M2b Marker)는 여전히 `cpu_executor` 스레드에서 실행되고, `gpu_lock`(async)이 그 실행을 프로세스 전역에서 직렬화한다. 즉 동시에 GPU 모델 1개만 살아있음 = VRAM 안전.
- cached-hit는 GPU와 무관(변환 안 함) → 분기 이전에서 처리(기존과 동일).
- 에러 계약 불변: GPU 경로의 예외도 기존 3-경계(MdflowError→코드, broad→INTERNAL)와 `run_conversion` wrap을 그대로 통과.

M2a엔 실제 GPU 컨버터가 없으므로(PyMuPDF는 CPU) 이 분기는 **fake `requires_gpu=True` 컨버터**로만 실행·검증된다(M1a `BoomConverter`/`ProgressyConverter` 주입 패턴 재사용).

---

## 5. Fallback chain (Codex 권고 #11) — 능력 게이팅으로 해소

별도 체인 실행 모델/에러-기반 런타임 폴백을 **만들지 않는다**(§6 예외-삼킴 회피 + YAGNI). 대신:

- `Registry.select`는 현행 first-wins(+`can_handle`) 유지.
- M2b에서 `pdf-marker`를 PyMuPDF **앞에** 등록하고, Marker의 `can_handle`이 GPU/torch/marker 가용성을 게이팅한다. → GPU 있으면 Marker 선택, 없으면 자동으로 PyMuPDF. 이것이 PRD가 말한 "Marker(GPU) → PyMuPDF(CPU) 자동 분기"다.
- M2a에선 PyMuPDF 1개만 등록 → 체인 길이 1. 등록 순서/게이팅 메커니즘은 M2b에서 Marker를 앞에 끼우면 그대로 동작.
- (런타임 에러 폴백 "Marker OOM → PyMuPDF 재시도"는 §6와 충돌 소지가 있어 M2a/M2b 비목표. 필요 시 후속에서 명시적 신호 기반으로만.)

---

## 6. 의존성

`pyproject.toml [project.dependencies]`(core)에 추가:

```toml
"pymupdf4llm>=0.0.17",
```

(PyMuPDF는 pymupdf4llm가 동반 설치. 정확 하한은 Task 0에서 `.venv/bin/pip install -e ".[dev]"` 결과로 확정.) Marker/torch는 M2b에서 `[project.optional-dependencies] gpu = ["marker-pdf", "torch"]`로 분리 — **M2a에 추가하지 않는다.**

---

## 7. 에러 처리 (§6 불변)

- 컨버터는 자체 try/except 없음. 손상 PDF → fitz/pymupdf4llm 예외 전파 → `run_conversion`이 `CONVERSION_FAILED`로 wrap → SSE `error`. (M1b 손상 OOXML 테스트와 동일 계약. PDF도 동일 통합 테스트 추가.)
- `doc.close()`는 except 없는 `try/finally` 자원정리(허용).
- format_detect는 M0에서 이미 `%PDF` magic으로 pdf 인식 → 등록 후 `UNSUPPORTED_FORMAT` 해소.
- 빈/텍스트 없는 PDF(스캔본 등) → 예외가 아니라 빈/최소 Markdown(골든에 반영). metadata에 `pages` 기록.

---

## 8. 테스트 전략

- **PDF 단위(골든)**: 코드 생성 fixture → 기대 골든. fixture는 `fitz`로 PDF를 코드 생성(서로 다른 폰트 크기로 제목/본문/리스트 텍스트 삽입 → pymupdf4llm가 구조를 잡도록). `MDFLOW_UPDATE_GOLDEN=1`로 1차 생성 후 사람이 검수, 이후 `tests/golden/pdf/sample.md` 전체-파일 비교. (출력이 결정적이어야 안정 — 동일 fixture/버전에서 pymupdf4llm는 결정적.)
- **빈 PDF**: 페이지만 있고 텍스트 없는 PDF → 빈/최소 Markdown 확인(예외 아님).
- **손상 PDF SSE**: garbage bytes(`x.pdf`) `/convert` → 마지막 이벤트 `error`/`CONVERSION_FAILED` (§6 회귀).
- **포맷 SSE 통합**: 코드 생성 PDF → `/convert` → `started.converter == "pdf-pymupdf4llm"`, `done.markdown` == 골든.
- **GPU 배관 (fake 컨버터)**:
  - fake `requires_gpu=True` 컨버터 주입 → `started.gpu == True`, gpu_lock 경유 정상 done.
  - 세마포어 점유 상태에서 요청 → `started` 이전에 `queued` 이벤트 방출 확인(대기 강제는 세마포어를 테스트에서 선점유; 정확한 async 하니스는 plan에서 확정).
  - 직렬화: 두 GPU 작업이 동시 진입해도 세마포어(1)로 직렬 실행됨을 검증(또는 점유 중 `gpu_semaphore.locked()` True 경유).
- 전체 `pytest` + `ruff check`/`format --check` clean 유지(현재 228 passed/1 skipped 기준 증가).
- libmagic/네트워크/GPU 의존 없음(입력 코드 생성, GPU 배관은 fake로 검증).

---

## 9. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | `pymupdf4llm` 의존성 추가 + 설치 검증 | `pyproject.toml` |
| 1 | PDF fixture(코드 생성) + 골든 하니스 재사용 | `tests/conftest.py` |
| 2 | `PdfConverter`(pymupdf4llm) + 골든 + 빈 PDF | `converters/pdf.py` |
| 3 | `convert.py` GPU 분기(gpu_lock + queued) + fake-GPU 컨버터 테스트 | `api/convert.py`, 테스트 |
| 4 | lifespan 등록 + PDF SSE 통합 + 손상 PDF SSE 테스트 | `api/app.py`, 테스트 |
| 5 | PROCESS_STATE 갱신 + M2a Codex 묶음 리뷰 | `PROCESS_STATE.md` |

각 컨버터/배관 Task는 subagent-driven(implementer → spec 리뷰 → quality 리뷰). Task 3은 `convert.py`의 핵심 변경이라 특히 주의(에러 계약·이벤트 순서·세마포어 lifecycle).

---

## 10. 비범위 / 후속 (기록)

- **M2b**: Marker GPU 통합(`[gpu]` extras, `pdf-marker` requires_gpu, can_handle GPU 게이팅, VRAM 정리), GPU 호스트에서 실행·검증. 본 설계의 GPU 배관에 드롭-인.
- 스캔 PDF OCR, 페이지별 progress 스트리밍, 표/수식 고품질화, 런타임 에러 폴백(Marker→PyMuPDF)은 후속.
- M1 hardening 잔여(cache 동시성/lifecycle, disconnect 취소, URL temp streaming, language_hint)는 별도 슬라이스 유지.
