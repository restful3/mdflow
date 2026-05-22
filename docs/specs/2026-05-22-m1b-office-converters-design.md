# M1b — 사무 포맷 컨버터 (docx/pptx/xlsx/html) 설계

**작성일**: 2026-05-22
**상태**: 설계 (브레인스토밍 산출물 — writing-plans 입력 대기)
**선행**: M1a SSE 인프라 완료 (`/convert` SSE, Codex 최종 승인). 본 설계는 M1a가 만든 SSE 경로 위에 실제 컨버터를 끼운다.
**정본 상태**: `PROCESS_STATE.md` §7 (M1)

---

## 1. 목표 / 범위

### 1.1 목표

`POST /convert`(M1a)가 현재 txt/md/csv만 변환한다. M1b는 **사무 문서 4종(docx, pptx, xlsx, html)을 의미 구조 보존 중심으로 Markdown 변환**하는 컨버터를 추가하고, 골든 출력 회귀 테스트 인프라를 세운다.

핵심 가치(PRD §1): **의미 구조 보존(헤딩/리스트/표/노트) > 시각 충실도.** 이미지·정밀 레이아웃은 v1 비목표.

### 1.2 In Scope

- 컨버터 4종: `docx-mammoth`, `pptx-python-pptx`, `xlsx-openpyxl`, `html-trafilatura`
- 4종을 lifespan에 등록 (format_detect는 M0에서 이미 4종 인식 → 등록만 하면 `UNSUPPORTED_FORMAT` 해소)
- 골든 테스트 인프라: 코드-생성 입력 fixture + `tests/golden/<converter>/sample.md` 전체-파일 exact 비교
- 신규 의존성 추가 (mammoth/python-docx/python-pptx/openpyxl/trafilatura/markdownify/beautifulsoup4)
- 포맷별 `/convert` SSE 통합 테스트 1건씩

### 1.3 Out of Scope (M1b 비목표)

- 이미지/자산 바이트 추출 — **이미지는 드롭** (base64 bloat 회피). markdownify 경로(docx, html fallback)는 alt 텍스트가 있으면 보존, trafilatura 경로(html 본문)는 `include_images=False`로 이미지를 완전히 제거(alt 미보존). 즉 alt 보존은 best-effort이며 markdownify 경로에 한정
- 정밀 레이아웃/스타일 충실도 (색상, 폰트, 위치)
- PDF (M2), LibreOffice/doc/ppt/hwp (M3), MCP (M4)
- cross-cutting 정리 항목(cache delete/purge OSError 정규화, shutdown/disconnect 정책, URL temp-file streaming, `language_hint`) — **별도 "M1 hardening" 슬라이스로 분리** (본 설계에 포함하지 않음)

---

## 2. 아키텍처 / 모듈

기존 `Converter` Protocol(`src/mdflow/converters/base.py`: `name`/`formats`/`requires_gpu`/`can_handle`/`convert(ctx, progress)`)을 그대로 구현한다. `TextConverter`가 참조 패턴이다. 모든 컨버터 `requires_gpu = False`.

```text
src/mdflow/converters/
├── base.py          (기존) Converter Protocol + Context/Result
├── text.py          (기존) TextConverter
├── _html_to_md.py   신규: markdownify 설정 공유 헬퍼 (docx, html fallback이 사용)
├── docx.py          신규: DocxConverter      name="docx-mammoth"      formats=("docx",)
├── pptx.py          신규: PptxConverter       name="pptx-python-pptx"  formats=("pptx",)
├── spreadsheet.py   신규: XlsxConverter       name="xlsx-openpyxl"     formats=("xlsx",)
└── html.py          신규: HtmlConverter       name="html-trafilatura"  formats=("html",)
```

등록: `src/mdflow/api/app.py` lifespan에서 기존 `registry.register(TextConverter())` 다음에 4종 등록.

`_html_to_md.py`는 markdownify를 한 곳에서 설정(ATX 헤딩 스타일, 이미지 변환 비활성/ alt 보존)해 docx와 html이 일관된 MD를 내도록 한다. 단일 책임: HTML 문자열 → Markdown 문자열.

각 컨버터는 동기 라이브러리를 호출한다. `convert(ctx, progress)`는 M1a `run_conversion`이 CPU executor에서 호출하며, `progress`는 **동기·in-call**로 호출한다(M1a ProgressCallback invariant).

---

## 3. 컨버터별 동작

공통: `convert()`는 `ctx.data`(bytes)를 `io.BytesIO`로 감싸 라이브러리에 전달. 반환 `ConversionResult(markdown=..., metadata={...})`. progress 단계는 대략 parse→render→done(100). 입력 손상 시 라이브러리 예외는 **그대로 전파**(M1a `run_conversion`이 `CONVERSION_FAILED`로 wrap).

### 3.1 docx (`docx-mammoth`)

- `mammoth.convert_to_html(BytesIO(data))` — Word 스타일을 시맨틱 HTML로 매핑(헤딩/리스트/표/bold/italic). 이미지 핸들러를 빈 결과로 설정해 **이미지 임베드 차단**(기본 base64 data URI 방지).
- 결과 HTML → `_html_to_md`(markdownify) → Markdown.
- mammoth가 반환하는 `messages`(경고)는 `metadata["warnings"]`에 수집(있을 때만).

### 3.2 pptx (`pptx-python-pptx`)

- `python-pptx`로 `Presentation(BytesIO(data))`. 슬라이드 1..N 순회.
- 슬라이드별 출력:
  - 제목 placeholder 있으면 `## <제목>`, 없으면 `## Slide N`
  - 본문 텍스트 프레임 단락 → **불릿 리스트로 렌더**: 각 단락을 `-` 항목으로, `paragraph.level`(0부터)만큼 2칸 들여쓰기해 중첩 표현. (PowerPoint 본문 placeholder는 통상 불릿이므로 v1은 본문 단락을 일괄 리스트로 처리. 빈 단락은 생략.)
  - 표 shape → Markdown 표
  - **발표자 노트(notes_slide)** 있으면 슬라이드 끝에 `> Notes:` 인용 블록으로
- 이미지/도형 그래픽은 드롭(텍스트 없는 shape 무시).

### 3.3 xlsx (`xlsx-openpyxl`)

- `openpyxl.load_workbook(BytesIO(data), data_only=True, read_only=True)` — 메모리 안전 + formula는 **마지막 캐시 값**.
- 시트별 출력: `## <SheetName>` + used range(`min_row..max_row` × `min_col..max_col`) Markdown 표. 첫 행을 헤더로 사용.
- 빈 셀 → 빈 칸(`None`→`""`). 완전히 빈 시트 → 헤딩만(또는 `(empty sheet)` 한 줄).
- 주의(`metadata` note): `data_only=True`는 파일이 Excel에서 저장된 적 없으면 formula 셀이 `None`일 수 있음 — v1 허용, metadata에 `formula_values="cached"` 기록.

### 3.4 html (`html-trafilatura`)

- `trafilatura.extract(html_str, output_format="markdown", include_tables=True, include_images=False)` — boilerplate(nav/footer/광고) 제거 후 본문을 Markdown으로.
- 추출이 `None`(기사형 본문 미검출) → **fallback**: `beautifulsoup4`로 `<body>`(없으면 전체) 파싱 → `_html_to_md`(markdownify).
- 입력 인코딩: bytes → `chardet`/utf-8 디코드(TextConverter `_decode` 재사용 또는 동등 처리).

---

## 4. 골든 테스트 인프라

### 4.1 입력 fixture (코드 생성)

`tests/converters/conftest.py`에 fixture로 입력을 **코드로 생성**(git에서 리뷰 가능·결정적):

- `sample_docx_bytes`: `python-docx`로 heading(2레벨) + 단락(+bold run) + 2×2 표 작성 → BytesIO bytes
- `sample_pptx_bytes`: `python-pptx`로 슬라이드 2장(제목+본문 불릿, 1장은 노트 포함) 작성
- `sample_xlsx_bytes`: `openpyxl`로 2시트(헤더+데이터 행) 작성
- `sample_html`: 본문+표를 가진 HTML 문자열 리터럴(boilerplate 포함시켜 trafilatura 제거 검증)

라이브러리 버전은 pyproject에 하한 고정. fixture 출력이 결정적이어야 골든 exact 비교가 안정적.

### 4.2 골든 비교

- 골든 출력 `tests/golden/<converter>/sample.md` 커밋(PRD §10.3 — 변경 시 diff 리뷰 강제).
- 비교 헬퍼 `assert_golden(actual: str, golden_path)`: trailing whitespace/말미 개행 정규화 후 **전체 문자열 exact 일치**. 불일치 시 unified diff를 assert 메시지로.
- 최초 생성/갱신: `MDFLOW_UPDATE_GOLDEN=1` 환경변수면 헬퍼가 골든 파일을 기록(테스트는 그 실행에서 통과로 간주). 평소엔 읽기-비교만.

### 4.3 통합 테스트

포맷별 1건: 코드-생성 fixture를 `/convert` multipart로 POST → SSE 파싱 → `started`의 `converter`가 기대 이름(`docx-mammoth` 등), `done.markdown`이 골든과 일치.

---

## 5. 의존성

`pyproject.toml [project.dependencies]`에 추가(PRD §11 — core, optional 아님):

```toml
"mammoth>=1.6",
"python-docx>=1.1",
"python-pptx>=0.6.23",
"openpyxl>=3.1",
"trafilatura>=1.8",
"markdownify>=0.11",
"beautifulsoup4>=4.12",
```

(정확한 하한 버전은 Task 0에서 설치 결과로 확정. `.venv/bin/pip install -e ".[dev]"`로 설치 검증.)

---

## 6. 에러 처리

- **컨버터는 자체 try/except를 두지 않는다**(YAGNI + 일관성). 손상/비정상 입력으로 라이브러리가 예외를 raise하면 M1a `ConversionService.run_conversion`의 wrap(`MdflowError(CONVERSION_FAILED)`)이 SSE `error` 이벤트로 변환한다. 라우트 경계의 broad except(INTERNAL)도 잔여 방어선.
- format_detect는 M0에서 이미 docx/pptx/xlsx/html을 magic(OOXML ZIP probe)·확장자·content-type로 인식. 4종 등록 후에는 이 포맷에 대해 `UNSUPPORTED_FORMAT`이 발생하지 않는다.
- 빈/엣지 입력(빈 시트, 노트 없는 슬라이드, 본문 없는 html)은 예외가 아니라 **빈/최소 Markdown**으로 처리(골든에 반영).

---

## 7. 테스트 전략

- 컨버터별 단위 TDD: **골든 먼저** — fixture 생성 → 기대 골든 작성(또는 `MDFLOW_UPDATE_GOLDEN=1`로 1차 생성 후 사람이 검수) → 컨버터 구현 → exact 비교 통과.
- 통합: 포맷별 `/convert` SSE 1건(§4.3).
- 회귀: 골든 파일 커밋, 변경 시 diff 리뷰.
- 전체 `pytest` + `ruff check`/`format --check` clean 유지(현재 191 passed/1 skipped 기준 증가).
- libmagic/네트워크 의존 없음(입력은 코드 생성, html은 문자열 — trafilatura는 순수 파싱).

---

## 8. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | 의존성 7종 추가 + 설치 검증 | `pyproject.toml` |
| 1 | 골든 하니스(`assert_golden` + `MDFLOW_UPDATE_GOLDEN`) + fixture 헬퍼 | `tests/converters/conftest.py`, 골든 헬퍼 |
| 2 | `_html_to_md` 헬퍼 + docx 컨버터 + 골든 | `converters/_html_to_md.py`, `converters/docx.py` |
| 3 | pptx 컨버터 + 골든 | `converters/pptx.py` |
| 4 | xlsx 컨버터 + 골든 | `converters/spreadsheet.py` |
| 5 | html 컨버터(+fallback) + 골든 | `converters/html.py` |
| 6 | lifespan 등록 + 포맷별 `/convert` SSE 통합 테스트 | `api/app.py`, 통합 테스트 |
| 7 | PROCESS_STATE 갱신 + M1b Codex 묶음 리뷰 | `PROCESS_STATE.md` |

각 컨버터 Task는 subagent-driven(implementer → spec 리뷰 → quality 리뷰). Task 2는 `_html_to_md`와 docx를 함께(공유 헬퍼 첫 소비자).

---

## 9. 비범위 / 후속 (기록)

- 이미지/자산 추출, `language_hint`, URL temp-file streaming, cache 동시성/lifecycle 정리, disconnect 취소(Codex M1a 권고 #2) — 별도 "M1 hardening" 또는 M2에서.
- pptx 슬라이드 내 이미지 alt, docx 각주/주석, xlsx 병합 셀 정밀 처리는 v1 미보장(필요 시 후속).
