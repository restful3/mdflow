# M3a — LibreOffice 폴백 컨버터 (doc + ppt) 설계

**작성일**: 2026-05-22
**상태**: 설계 (브레인스토밍 산출물 — writing-plans 입력 대기)
**선행**: M2a PDF 컨버터(`v0.2.0-m2a`, Codex 최종 승인). 본 설계는 기존 `PdfConverter`(pymupdf4llm, CPU)를 **내부 합성(composition)** 으로 재사용한다.
**정본 상태**: `PROCESS_STATE.md` §9 (M3)

---

## 1. 목표 / 범위

### 1.1 목표

`POST /convert`가 현재 txt/md/csv/docx/pptx/xlsx/html/pdf를 처리한다. M3a는 **레거시 바이너리 오피스 포맷 doc/ppt를 Markdown으로 변환**한다. 경로: `soffice --headless --convert-to pdf` → PDF bytes → `PdfConverter`(pymupdf4llm) 내부 합성 → Markdown.

핵심 가치(PRD §1): **의미 구조 보존(헤딩/리스트/표) > 시각 충실도.**

### 1.2 In Scope (M3 = "M3a")

- **LibreOffice 컨버터** `office-libreoffice` — formats `("doc","ppt")`, `requires_gpu=False`. 전 과정 CPU.
- doc/ppt bytes → 임시 파일 → `soffice` 헤드리스 PDF 변환 → PDF bytes → 기존 `PdfConverter` 합성 호출 → Markdown.
- **접근 A (단일 컨버터, 내부 PDF→MD 합성)** 채택. 근거: registry first-wins에 그대로 맞고, 이 호스트(LibreOffice 24.2.7.2)에서 완결 검증되며, PDF→MD 로직을 재사용(중복 0). M2 설계 철학("폴백 체인 = 능력 게이팅 + 등록 순서, 별도 체인 실행기 없음")과 일관.
- 신규 Settings 1개: `MDFLOW_SOFFICE_TIMEOUT_S`(기본 120s).
- 테스트: soffice-의존 테스트는 `skipif(soffice 부재)`. fixture는 빌드타임 soffice 변환으로 생성. 출력 검증은 구조적 assert 우선(+선택적 버전-핀 골든).

### 1.3 Out of Scope (M3a 비목표)

- **hwp → 별도 슬라이스 "M3b"**. LibreOffice HWP import 필터 신뢰도가 들쭉날쭉하고 `pyhwp` 별도 의존성·한국어 폰트(Docker)가 얽혀 복잡도가 다르다. M3b에서 HWP 필터 vs pyhwp를 평가.
- **GPU 고품질 체인 (접근 B)**: doc → PDF → Marker(GPU). Marker(M2b)가 없고, 컨버터 스레드에서 `gpu_lock`(async, `convert.py` SSE 계층)에 닿을 수 없어 다단계 SSE 오케스트레이션이 필요 — 별도 설계로 분리. M3a는 PDF 중간 산출을 항상 CPU(PyMuPDF) 경로로 처리.
- 스캔 PDF/이미지 OCR (tesseract 미설치, PyMuPDF는 텍스트 레이어만).
- 기타 레거시 포맷(xls/rtf/odt) — PROCESS_STATE M3 범위 밖, YAGNI.
- soffice 동시 실행 throughput 제한(전역 세마포어) — v1은 per-call 프로필로 충분. 필요 시 후속 hardening.

---

## 2. 아키텍처 / 모듈

기존 `Converter` Protocol(`converters/base.py`)을 그대로 구현. `PdfConverter`(`converters/pdf.py`)를 합성으로 재사용.

```text
src/mdflow/converters/office.py   신규: LibreOfficeConverter
src/mdflow/api/app.py             수정: lifespan에 LibreOfficeConverter 등록 (PdfConverter 뒤)
src/mdflow/settings.py            수정: soffice_timeout_s 필드 추가
```

- `pyproject.toml` **변경 없음**: system `soffice` 바이너리(subprocess) + 기존 core 의존 `pymupdf4llm`을 그대로 쓴다.
- `core/format_detect.py` **변경 없음**: `doc`/`ppt`는 이미 `_EXT_TO_FORMAT`에 존재. 레거시 OLE compound 바이너리는 magic으로 doc/ppt/xls를 구분할 수 없으므로(모두 동일 OLE 시그니처) **확장자 기반 탐지에 의존**. 확장자 없는 doc/ppt 입력은 `FORMAT_DETECT_FAILED`(v1 한계, 문서화).

---

## 3. 컨버터 동작 (`office-libreoffice`)

- `name = "office-libreoffice"`, `formats = ("doc", "ppt")`, `requires_gpu = False`.
- `__init__(self, timeout_s: float, pdf: PdfConverter | None = None)`:
  - `self._soffice = shutil.which("soffice")` — 1회 캐시(인스턴스는 lifespan에서 1회 생성).
  - `self._timeout_s = timeout_s`.
  - `self._pdf = pdf or PdfConverter()` — 합성용 PDF 컨버터(테스트 주입 가능).
- `can_handle(self, ctx)`: `return ctx.format in self.formats` — **soffice 가용성으로 게이팅하지 않는다**(§4 참조).
- `convert(self, ctx, progress)`:
  1. `if self._soffice is None: raise MdflowError(LIBREOFFICE_UNAVAILABLE, ...)`.
  2. `progress("convert", 5)`.
  3. `with tempfile.TemporaryDirectory() as tmp:` 안에서:
     - `ext = "doc" if ctx.format == "doc" else "ppt"`; 입력을 `<tmp>/input.<ext>`에 기록(파일명은 합성 — 사용자 입력 아님 → path traversal 없음).
     - `subprocess.run([self._soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, "-env:UserInstallation=file://<tmp>/lo_profile", input_path], timeout=self._timeout_s, check=False, capture_output=True)`.
       - **argv 리스트(shell 미사용)** → 커맨드 인젝션 불가.
       - **per-call `UserInstallation` 프로필 디렉토리** → 동시 soffice 호출이 사용자 기본 프로필 락에서 충돌하지 않음(cpu_executor 병렬성 유지).
     - `returncode != 0` 또는 `<tmp>/input.pdf` 미생성 → `raise MdflowError(CONVERSION_FAILED, <stderr 요약>)`.
     - `pdf_bytes = (<tmp>/input.pdf).read_bytes()`.
  4. `progress("convert", 50)`.
  5. PDF 단계: `pdf_ctx = ConversionContext(data=pdf_bytes, filename_hint="input.pdf", format="pdf", options=ctx.options, metadata={"format": "pdf"})`; `sub_progress = lambda s, p: progress(s, 50 + p // 2)`; `pdf_result = self._pdf.convert(pdf_ctx, sub_progress)`. (PDF 진행률 10/60/100 → 55/80/100, 단조 증가.)
  6. 반환:
     ```python
     ConversionResult(
         markdown=pdf_result.markdown,
         metadata={
             "source_format": ctx.format,
             "engine": "libreoffice+pymupdf4llm",
             "pages": pdf_result.metadata.get("pages"),
         },
     )
     ```
- **TimeoutExpired**: `subprocess.run`이 올리는 `subprocess.TimeoutExpired`를 잡아 `MdflowError(TIMEOUT, ...)`(retryable)로 변환. `TemporaryDirectory` 컨텍스트가 예외 경로에서도 임시 디렉토리를 정리.
- **§6 준수**: 라이브러리/하위 프로세스 예외를 삼키지 않는다. subprocess는 예외 대신 returncode를 돌려주므로 명시적으로 검사해 에러를 신호화(삼킴이 아님). PDF 단계의 fitz/pymupdf4llm 예외는 그대로 전파 → `run_conversion`이 `CONVERSION_FAILED`로 wrap.

---

## 4. can_handle를 soffice 가용성으로 게이팅하지 않는 이유

`can_handle`이 soffice 부재 시 False를 반환하면, `Registry.select`가 다른 컨버터를 못 찾아 `UNSUPPORTED_FORMAT`을 올린다 — 그러나 포맷(doc/ppt)은 **지원 대상이며 단지 도구가 없을 뿐**이라 오해를 부른다. 대신 `can_handle`은 항상 True(포맷 매칭)를 반환하고, `convert`가 soffice 부재 시 전용 코드 `LIBREOFFICE_UNAVAILABLE`을 올려 정확한 진단을 제공한다. 이 코드는 M0에서 본 용도로 이미 enum에 정의돼 있다.

---

## 5. 에러 처리 (§6 불변)

| 상황 | 코드 | retryable |
|---|---|---|
| soffice 미설치 | `LIBREOFFICE_UNAVAILABLE` | False |
| soffice timeout | `TIMEOUT` | True |
| soffice 비정상 종료 / PDF 미생성 / 손상 입력 | `CONVERSION_FAILED` | True |
| PDF 단계(fitz/pymupdf4llm) 내부 오류 | 전파 → `run_conversion`이 `CONVERSION_FAILED` wrap | True |

세 코드 모두 `MdflowError`이므로 `run_conversion`의 `except MdflowError: raise`를 그대로 통과해 SSE `error` 이벤트로 표면화된다(M1a 에러 계약과 동일).

---

## 6. 의존성

- **신규 Python 패키지 없음**. system `soffice`(LibreOffice) + 기존 core 의존 `pymupdf4llm`.
- **system 의존**: LibreOffice. M5 Dockerfile이 이미 `libreoffice` 포함 계획. 이 호스트엔 LibreOffice 24.2.7.2 설치됨.
- Settings 추가: `soffice_timeout_s: float = Field(default=120.0, gt=0)` (env `MDFLOW_SOFFICE_TIMEOUT_S`). lifespan에서 `LibreOfficeConverter(timeout_s=settings.soffice_timeout_s)`로 주입.

---

## 7. 테스트 전략

- **soffice 의존 테스트는 `@pytest.mark.skipif(shutil.which("soffice") is None, reason=...)`** — 이 호스트에선 실행, CI/무-LibreOffice 호스트에선 skip. (M0 테스트 전략의 "OS 의존 fixture는 마커로 분리"와 일관.)
- **Fixture (빌드타임 soffice 변환)**: 레거시 바이너리 doc/ppt는 순수 파이썬 writer가 없어 코드-gen 불가. → conftest에서 python-docx/python-pptx로 `.docx`/`.pptx`를 코드 생성한 뒤 `soffice`로 `.doc`/`.ppt`로 1회 변환해 fixture를 만든다(soffice 있을 때만; session-scoped). **순수 코드-gen 패턴(M1b/M2)의 의도적 예외** — 레거시 바이너리 특성상 불가피, 사용자 승인됨.
- **출력 검증 — 구조적 assert 우선**: LibreOffice 버전마다 PDF가 미세하게 달라 exact 골든은 환경 취약. 1차 검증은 fixture에 넣은 **기대 텍스트(헤딩/본문 문자열)가 markdown에 포함**되는지 assert. exact 골든 스냅샷은 선택이며, 채택 시 integration 마커 + 이 호스트 LibreOffice 버전에 핀 명시. **M1b/M2의 exact-golden과 다른 방침 — 사용자 승인됨.**
- **에러 테스트**:
  - soffice 부재(monkeypatch `converter._soffice = None`) → `LIBREOFFICE_UNAVAILABLE` (unit, soffice 불필요).
  - `subprocess.run`이 `TimeoutExpired` raise하도록 monkeypatch → `TIMEOUT` (unit, soffice 불필요).
  - 손상 doc(garbage bytes, `.doc` hint) → soffice 실패/PDF 미생성 → `CONVERSION_FAILED` (integration).
- **SSE 통합**: 코드 생성 doc fixture → `/convert` → `started.converter == "office-libreoffice"`, 마지막 이벤트 `done`, `done.markdown`에 기대 텍스트 포함.
- 전체 `pytest` + `ruff check`/`format --check` clean 유지(현재 240 passed/1 skipped 기준 증가; soffice 없는 환경에선 신규 integration 테스트가 skip).

---

## 8. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | `MDFLOW_SOFFICE_TIMEOUT_S` Settings 추가 + 검증 | `settings.py` |
| 1 | doc/ppt fixture 빌드(conftest, soffice 변환) + skipif 헬퍼 | `tests/conftest.py` |
| 2 | `LibreOfficeConverter` 핵심(soffice subprocess + PDF 합성) + 구조적 assert 테스트 | `converters/office.py` |
| 3 | 에러 경로(LIBREOFFICE_UNAVAILABLE/TIMEOUT unit, 손상 doc integration) | 테스트 |
| 4 | lifespan 등록 + doc/ppt SSE 통합 테스트 | `api/app.py`, 테스트 |
| 5 | PROCESS_STATE 갱신 + M3a Codex 묶음 리뷰 | `PROCESS_STATE.md` |

각 Task는 subagent-driven(implementer → spec-compliance 리뷰 → code-quality 리뷰). Task 2가 핵심(subprocess lifecycle·프로필 격리·progress remap·에러 신호화).

---

## 9. 비범위 / 후속 (기록)

- **M3b**: hwp (LibreOffice HWP 필터 vs `pyhwp` 평가) + 한국어 폰트(Docker `fonts-noto-cjk`).
- **GPU 체인(접근 B)**: Marker(M2b) 후 doc→PDF→Marker 다단계 SSE 오케스트레이션 — 별도 설계.
- soffice 동시 실행 throughput 제한(전역 세마포어), 스캔 doc 내 이미지 OCR은 후속.
- 확장자 없는 레거시 바이너리 입력의 magic 탐지(OLE 시그니처는 doc/ppt/xls 구분 불가) — v1 한계 유지.
