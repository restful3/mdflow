# M3b — HWP 컨버터 (pyhwp) 설계

**작성일**: 2026-05-22
**상태**: 설계 (평가 산출물 — writing-plans 입력 대기)
**선행**: M3a LibreOffice 컨버터(`v0.3.0-m3a`, Codex 승인). 본 설계는 M3a의 `office-libreoffice` 패턴(외부 도구 → 중간 포맷 → 합성)을 참고하되, **HWP 5.0은 LibreOffice로 변환 불가**가 실증되어 다른 엔진(`pyhwp`)을 쓴다.
**정본 상태**: `PROCESS_STATE.md` §9 (M3)

---

## 0. 평가 요약 (이 설계의 근거)

이 호스트(LibreOffice 24.2.7.2, Python 3.12)에서 실제 `.hwp` 파일 10개로 실증한 결과:

| 항목 | 결과 |
|---|---|
| **LibreOffice HWP 변환** | **불가**. 번들 필터 `writer_MIZI_Hwp_97`은 구형 HWP 3.0(1997) 전용. 현대 HWP 5.0(OLE/CFB, magic `d0cf11e0`) 입력은 `"source file could not be loaded"`로 거부(2개 파일 모두). → M3a의 `soffice → PDF` 접근 **재사용 불가**. |
| **pyhwp 변환률** | 실제 파일 10개 중 **8개 성공**, 2개(영수증 서식) 실패. |
| **백엔드** | `pyhwp`의 XSLT 백엔드는 `get_xslt()`가 lxml을 우선 선택. **이미 우리 스택에 있는 lxml로 충분**. `PYHWP_XSLTPROC` 환경변수를 줘도 lxml이 우선되어 백엔드가 바뀌지 않음 → **외부 `xsltproc`/`libxslt` 시스템 의존 불필요**. (초기 가설 "xsltproc가 실패를 구제한다"는 파일별 차이를 백엔드 차이로 오인한 것으로, 같은 파일은 두 백엔드에서 동일하게 실패/성공.) |
| **실패 원인** | 일부 파일은 pyhwp 내부 XML 생성 단계에서 `lxml.etree.XMLSyntaxError: invalid character in attribute value`. 이는 pyhwp의 한계이며 우리 코드에선 `CONVERSION_FAILED`로 표면화. |
| **통합 방식** | `HTMLTransform().transform_hwp5_to_xhtml(Hwp5File, out_stream)` — 단일 XHTML 스트림을 in-process 생성(디렉토리/subprocess 불요). |
| **품질** | 표(`<table>`)·헤딩·한글 텍스트 보존. 수식·특수 객체(이미지/도형)는 드롭(pyhwp 한계, v1 허용). |

---

## 1. 목표 / 범위

### 1.1 목표

`POST /convert`가 현재 txt/md/csv/docx/pptx/xlsx/html/pdf/doc/ppt를 처리한다. M3b는 **HWP 5.0 문서를 Markdown으로 변환**한다. 경로: hwp bytes → 임시 파일 → `pyhwp`(`Hwp5File` + `HTMLTransform`) in-process XHTML 생성 → 기존 `_html_to_md`(markdownify) 합성 → Markdown.

핵심 가치(PRD §1): **의미 구조 보존(헤딩/리스트/표) > 시각 충실도.**

### 1.2 In Scope (M3b)

- **HWP 컨버터** `hwp-pyhwp` — formats `("hwp",)`, `requires_gpu=False`. 전 과정 CPU.
- hwp bytes → 임시 파일 → `pyhwp` in-process XHTML → `_html_to_md`(이미지 드롭) → Markdown.
- **신규 Python optional 의존**: `pyhwp` (`[hwp]` extra). 시스템 의존 추가 없음.
- **신규 ErrorCode 1개**: `HWP_UNAVAILABLE`(`pyhwp` 미설치 시, non-retryable) — M3a의 `LIBREOFFICE_UNAVAILABLE` 선례와 일관.
- 테스트: pyhwp transform을 monkeypatch한 결정적 unit(컨버터 로직·에러 매핑) + 개발자 제공 실제 `.hwp` 통합 테스트(`requires_pyhwp_fixture` skip).

### 1.3 Out of Scope (M3b 비목표)

- **구형 HWP 3.0**: `pyhwp`는 HWP 5.0 전용. HWP 3.0/한글 97 입력은 `CONVERSION_FAILED`(v1 한계, 문서화).
- **수식·이미지·도형 보존**: pyhwp가 XHTML 단계에서 드롭. OCR/수식 복원은 비목표.
- **암호화 HWP**: 비밀번호 보호 문서는 미지원 → `CONVERSION_FAILED`.
- **per-converter timeout**: pyhwp는 in-process(서브프로세스 아님)라 M3a식 subprocess timeout이 없다. 다른 in-process 컨버터(docx/pptx/xlsx)와 동일하게 별도 timeout 없음. 대형 입력은 `MDFLOW_MAX_INPUT_MB` cap으로 1차 방어. (필요 시 후속 hardening.)
- **AGPL 테스트 자산 벤더링**: mdflow는 MIT. pyhwp(AGPL) 저장소의 `sample-*.hwp`를 리포에 커밋하지 않는다(§7).

---

## 2. 아키텍처 / 모듈

기존 `Converter` Protocol(`converters/base.py`)을 그대로 구현. `_html_to_md.html_to_markdown`을 합성으로 재사용(docx/html 컨버터와 동일 헬퍼).

```text
src/mdflow/converters/hwp.py      신규: HwpConverter
src/mdflow/converters/_html_to_md.py  변경 없음 (재사용)
src/mdflow/core/errors.py         수정: HWP_UNAVAILABLE 추가
src/mdflow/api/app.py             수정: lifespan에 HwpConverter 등록
src/mdflow/settings.py            변경 없음
pyproject.toml                    수정: [project.optional-dependencies] hwp = ["pyhwp"]
```

- `core/format_detect.py` **변경 없음**: `.hwp`는 이미 `_EXT_TO_FORMAT`에 `"hwp"`로 매핑됨. 이 호스트에서 `_magic_format`은 hwp 입력에 `None`을 반환(libmagic이 OLE/CFB를 `_MIME_TO_FORMAT`에 없는 값으로 분류하거나 미설치) → 확장자 기반 `format="hwp"`, `source="ext"`, 경고 없음. **v1 한계**: libmagic이 hwp의 OLE 시그니처를 `application/msword` 등으로 분류하는 환경에서는 magic-wins로 `doc`에 오라우팅될 수 있음(M3a §2의 OLE 모호성 한계와 동일). 확장자 없는 hwp는 `FORMAT_DETECT_FAILED`(v1 한계).

### 2.1 pyhwp 지연 import (중요)

`pyhwp`는 optional `[hwp]` extra이므로 base 설치엔 없다. `converters/hwp.py`는 **모듈 top-level에서 pyhwp를 import하지 않는다**(import하면 base 설치에서 `api/app.py`가 컨버터를 등록하다 ImportError로 앱 전체가 죽는다). 대신 `convert()` 내부에서 지연 import하고, 실패 시 `HWP_UNAVAILABLE`을 올린다. 이는 M3a가 `shutil.which("soffice")`를 인스턴스 생성 시 1회 확인하고 `convert()`에서 `None`을 검사하는 패턴과 동일한 의도(포맷은 지원 대상, 도구만 부재).

---

## 3. 컨버터 동작 (`hwp-pyhwp`)

- `name = "hwp-pyhwp"`, `formats = ("hwp",)`, `requires_gpu = False`.
- `can_handle(self, ctx)`: `return ctx.format in self.formats` — **pyhwp 가용성으로 게이팅하지 않는다**(M3a §4와 동일 근거: 포맷은 지원 대상, 도구만 부재 → 정확한 진단 코드 제공).
- `convert(self, ctx, progress)`:
  1. `progress("parse", 5)`.
  2. 지연 import:
     ```python
     try:
         from hwp5.xmlmodel import Hwp5File
         from hwp5.hwp5html import HTMLTransform
     except ImportError as e:
         raise MdflowError(ErrorCode.HWP_UNAVAILABLE, "pyhwp not installed (pip install 'mdflow[hwp]')") from e
     ```
  3. `with tempfile.TemporaryDirectory() as tmp:` 안에서:
     - 입력을 `<tmp>/input.hwp`에 기록(파일명 합성 — 사용자 입력 아님 → path traversal 없음). **이유**: `Hwp5File`은 OLE 스토리지를 경로/파일로 연다(bytes API 불안정) → 임시 파일 경유.
     - `from contextlib import closing`; `buf = io.BytesIO()`.
     - `with closing(Hwp5File(str(src))) as hwp5: HTMLTransform().transform_hwp5_to_xhtml(hwp5, buf)`.
  4. `progress("render", 60)`.
  5. `html = buf.getvalue().decode("utf-8", "replace")` (pyhwp XHTML 출력은 UTF-8 고정).
  6. `markdown = html_to_markdown(html, strip_images=True)` — `transform_hwp5_to_xhtml`은 단일 파일이라 bindata 이미지를 추출하지 않음(깨진 ref) → 이미지 드롭(docx와 동일 방침). `<style>`/CSS는 markdownify가 제거.
  7. `progress("done", 100)`.
  8. 반환:
     ```python
     ConversionResult(
         markdown=markdown,
         metadata={"source_format": "hwp", "engine": "pyhwp"},
     )
     ```
- **§6 준수**: pyhwp/lxml의 라이브러리 예외(`InvalidHwp5FileError`, `lxml.etree.XMLSyntaxError`, `ParseError` 등)를 **삼키지 않고 그대로 전파** → `run_conversion`이 비-MdflowError를 `CONVERSION_FAILED`로 wrap(M1b의 docx/pptx 라이브러리 예외 전파와 동일). `HWP_UNAVAILABLE`만 컨버터가 직접 신호.

---

## 4. 에러 처리 (§6 불변)

| 상황 | 코드 | retryable | 신호 위치 |
|---|---|---|---|
| `pyhwp` 미설치 | `HWP_UNAVAILABLE` | False | 컨버터(지연 import 실패) |
| 손상/비-HWP5/HWP3.0/암호화 입력 | `CONVERSION_FAILED` | True | pyhwp 예외 전파 → `run_conversion` wrap |
| pyhwp XML 생성 실패(일부 정상 hwp) | `CONVERSION_FAILED` | True | lxml 예외 전파 → `run_conversion` wrap |

`HWP_UNAVAILABLE`은 `MdflowError`이므로 `run_conversion`의 `except MdflowError: raise`를 통과해 SSE `error` 이벤트로 표면화(M1a 에러 계약과 동일). 나머지는 비-MdflowError로 `CONVERSION_FAILED` wrap.

---

## 5. ErrorCode 추가

`core/errors.py`의 `ErrorCode` enum에 추가:

```python
HWP_UNAVAILABLE = ("HWP_UNAVAILABLE", False)
```

M3a의 `LIBREOFFICE_UNAVAILABLE = ("LIBREOFFICE_UNAVAILABLE", False)` 선례와 동일(도구 부재는 재시도 무의미 → non-retryable).

---

## 6. 의존성

- **신규 Python optional 의존**: `pyhwp`. `pyproject.toml`의 `[project.optional-dependencies]`에 `hwp = ["pyhwp"]` 추가. pyhwp는 `cryptography`, `olefile`, `cffi`를 끌어옴(검증됨: Python 3.12 venv에 `pyhwp 0.1b15` 설치 성공).
- **시스템 의존 추가 없음**: lxml(이미 trafilatura/bs4 스택에 존재)이 XSLT 백엔드. `xsltproc`/`libxslt`, 한국어 폰트 모두 불필요(텍스트 추출이지 렌더링이 아님).
- **Docker**: M3a처럼 별도 폰트 불요. `pip install '.[hwp]'`만.
- **pyhwp 성숙도 리스크(기록)**: pyhwp는 베타(0.1b15, 마지막 릴리스 ~2016). 일부 정상 hwp가 실패할 수 있고(평가 8/10), 유지보수가 비활성. `[hwp]`를 **격리된 optional extra**로 두어 미설치 시 다른 포맷에 영향 0, 설치 시 실패는 `CONVERSION_FAILED`로 안전 표면화.
- **라이선스 표기(운영자용, Codex 권고 3)**: mdflow 본체는 MIT지만 `[hwp]` extra가 끌어오는 `pyhwp`는 **AGPL-3.0**이다. `pip install 'mdflow[hwp]'`로 HWP 지원을 켜는 운영자는 AGPL 의존을 설치하게 됨을 인지해야 한다(별도 프로세스 의존이며 mdflow 코어 코드와 정적 링크되지 않음). base 설치(`pip install mdflow`)는 AGPL 의존을 포함하지 않는다. (README 신설 시 이 단락을 옮긴다.)

---

## 7. 테스트 전략

mdflow는 **MIT** 라이선스이고 HWP 5.0은 순수 파이썬 writer가 없어(soffice도 hwp를 못 씀) 코드-gen 불가, pyhwp(AGPL) 샘플은 라이선스 혼입 우려로 커밋 불가. 따라서:

- **결정적 CI 커버리지 (fixture 불요, monkeypatch)**:
  - **happy-path 로직**: `HTMLTransform.transform_hwp5_to_xhtml`(또는 컨버터가 호출하는 지점)를 monkeypatch해 알려진 XHTML(`<h1>제목</h1><table>...`)을 `out_stream`에 기록하도록 하고, `Hwp5File`도 monkeypatch(임의 객체) → 컨버터가 ① 임시파일 기록 ② XHTML decode ③ `_html_to_md`(이미지 드롭) ④ 메타데이터(`source_format=hwp`, `engine=pyhwp`)를 올바로 수행하는지 assert. **pyhwp 실제 transform 없이 컨버터 자체 로직을 전부 검증.**
  - **에러 매핑**: (a) 지연 import 실패 시뮬레이트(`builtins.__import__` 또는 모듈 부재 monkeypatch) → `HWP_UNAVAILABLE`. (b) `Hwp5File`/transform이 예외 raise하도록 monkeypatch → 예외 전파 → service 레벨에서 `CONVERSION_FAILED` 확인.
- **로컬 통합 (실제 pyhwp, skip-if-absent)**:
  - `tests/fixtures/hwp/sample.hwp`가 **존재하고** pyhwp import 가능할 때만 실행, 아니면 `pytest.skip`. (리포에 커밋하지 않음 — 개발자가 로컬에 둠. CI에선 skip.) 실제 hwp → 컨버터 → markdown에 기대 텍스트 포함 assert.
  - skip 헬퍼 `requires_pyhwp` (= pyhwp import 가능) + `requires_hwp_fixture` (= fixture 파일 존재).
- **SSE 통합 (monkeypatch)**: monkeypatch한 컨버터로 `.hwp` 입력 → `/convert` → `started.converter == "hwp-pyhwp"`, 마지막 이벤트 `done`, markdown에 기대 텍스트 포함. (fixture 불요.)
- 전체 `pytest` + `ruff check`/`format --check` clean 유지(현재 255 passed/1 skipped 기준 증가; 통합 테스트는 fixture 없으면 skip).

---

## 8. Task 분해 (writing-plans 입력)

| Task | 내용 | 산출 |
|---|---|---|
| 0 | `HWP_UNAVAILABLE` ErrorCode 추가 + 단위 테스트 | `core/errors.py` |
| 1 | `pyproject.toml` `[hwp]` extra 추가 | `pyproject.toml` |
| 2 | `HwpConverter` 핵심(지연 import + 임시파일 + transform + `_html_to_md`) + monkeypatch happy-path 테스트 | `converters/hwp.py` |
| 3 | 에러 경로(`HWP_UNAVAILABLE` import 실패 unit, transform 예외 → `CONVERSION_FAILED` service 테스트) | 테스트 |
| 4 | lifespan 등록 + hwp SSE 통합 테스트(monkeypatch) + skip-if-absent 실제 fixture 통합 | `api/app.py`, 테스트 |
| 5 | PROCESS_STATE 갱신 + M3b Codex 묶음 리뷰 | `PROCESS_STATE.md` |

각 Task는 subagent-driven(implementer → spec-compliance 리뷰 → code-quality 리뷰). Task 2가 핵심(지연 import 격리·임시파일 lifecycle·XHTML decode·이미지 드롭·에러 전파).

---

## 9. 비범위 / 후속 (기록)

- **GPU 무관**: 전 과정 CPU. M2b(Marker)와 독립.
- **pyhwp 실패 파일**: 일부 정상 hwp가 pyhwp 버그로 실패 → `CONVERSION_FAILED`. 대체 엔진(상용 Hancom API 등)은 v1 비목표.
- **수식·이미지·도형**: pyhwp XHTML 단계 드롭. 후속 고품질 경로는 별도 평가.
- **libmagic OLE 모호성**: hwp/doc/ppt/xls가 동일 OLE 시그니처 → 확장자 의존(M3a와 공유 한계).
