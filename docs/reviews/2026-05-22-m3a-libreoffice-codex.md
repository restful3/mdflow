# mdflow M3a LibreOffice converter 리뷰 - Codex

작성일: 2026-05-22
대상 diff: `git diff 05b86c1 HEAD`

검증:
- `git log --oneline 05b86c1..HEAD` 및 대상 diff 확인
- `.venv/bin/python -m pytest -q tests/converters/test_office.py tests/api/test_convert.py -k 'office or doc_streams or ppt_streams or soffice or doc_structure or ppt_structure or progress_is_monotonic'` -> 13 passed
- `.venv/bin/python -m pytest -q` -> passed / 1 skipped
- `.venv/bin/ruff check src tests` -> All checks passed
- `docs/specs/2026-05-22-m3a-libreoffice-design.md`, `office.py`, `pdf.py`, `service.py`, `convert.py`, `app.py`, 관련 테스트를 실제 파일 기준으로 확인

## Blocking

없음.

M3a의 핵심 계약은 지켜져 있습니다. `LibreOfficeConverter`는 `TimeoutExpired`를 `TIMEOUT`으로, soffice 부재를 `LIBREOFFICE_UNAVAILABLE`으로, nonzero exit/PDF 미생성을 `CONVERSION_FAILED`로 신호화하고, PDF 단계 예외는 삼키지 않고 `ConversionService.run_conversion()`의 `CONVERSION_FAILED` wrap으로 넘깁니다. subprocess는 shell 없이 argv list로 실행되고, per-call `UserInstallation` profile과 `TemporaryDirectory`도 모든 정상/예외 경로에서 적절히 닫히는 구조입니다.

## Recommendations

### 1. M3a 전용 SSE error 매핑 테스트를 추가하면 더 직접적인 회귀 방지가 됩니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:43`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:70`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:76`
- `/home/restful3/workspace/mdflow/tests/converters/test_office.py:59`

현재 unit 테스트는 `LIBREOFFICE_UNAVAILABLE`, `TIMEOUT`, `CONVERSION_FAILED`가 converter에서 정확히 발생하는지 확인합니다. `service.run_conversion()`이 `MdflowError`를 그대로 통과시키고 `/convert`가 SSE `error`로 매핑하는 계약은 기존 M1a 테스트로 간접 보장됩니다.

그래도 M3a 전용으로 한두 개의 SSE 테스트를 두면 좋습니다. 예를 들어 app registry에 `_soffice = None`인 `LibreOfficeConverter`를 주입해 `.doc` 요청 마지막 이벤트가 `error/LIBREOFFICE_UNAVAILABLE`인지 확인하면, “office converter가 만든 MdflowError가 SSE surface까지 보존된다”를 직접 고정할 수 있습니다. timeout도 `mdflow.converters.office.subprocess.run` monkeypatch로 결정적으로 재현 가능합니다.

### 2. soffice 실패 메시지는 stderr가 비어 있을 때 stdout도 포함하면 진단성이 좋아집니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:76`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:77`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:80`

현재 nonzero exit 또는 PDF 미생성 시 `stderr[:500]`만 메시지에 넣습니다. LibreOffice는 상황에 따라 stdout 쪽에 의미 있는 문구를 남길 수 있습니다. `stderr or stdout` 또는 둘 다 잘라 넣으면 운영 디버깅에 유리합니다.

동작/계약상 문제는 아니므로 권고 수준입니다.

### 3. 입력 파일 확장자는 명시 매핑으로 고정하면 더 방어적입니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:51`

서비스 경로에서는 `ctx.format`이 `format_detect`의 고정값 `doc`/`ppt`에서 오므로 path traversal 위험은 실질적으로 없습니다. 다만 `convert()`가 public-ish method인 점을 고려하면 설계 문서처럼 `ext = "doc" if ctx.format == "doc" else "ppt"` 또는 `if ctx.format not in self.formats: ...`를 한 줄 둬도 좋습니다.

현재 코드가 사용자 filename을 쓰지 않고 temp dir 아래 합성 경로만 쓰는 점은 안전합니다. 이 권고는 직접 호출 방어성 개선입니다.

### 4. subprocess argv/profile/timeout을 테스트에서 assert하면 안전 계약이 더 단단해집니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:55`
- `/home/restful3/workspace/mdflow/tests/converters/test_office.py:67`
- `/home/restful3/workspace/mdflow/tests/converters/test_office.py:81`

현재 monkeypatch tests는 patch target이 실제 코드 경로(`mdflow.converters.office.subprocess.run`)라 vacuous하지 않습니다. 추가로 fake `subprocess.run`에서 다음을 assert하면 subprocess 안전 계약도 회귀 방지됩니다.

- 첫 인자가 argv list이고 shell을 쓰지 않음
- `--headless`, `--convert-to pdf`, `--outdir`가 포함됨
- `-env:UserInstallation=file://.../lo_profile`가 포함됨
- `timeout`이 converter에 주입한 값과 같음

## Notes

### 1. 에러 계약과 §6 no-swallow 원칙은 적절합니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:43`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:70`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:76`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:91`
- `/home/restful3/workspace/mdflow/src/mdflow/core/service.py:120`

`TimeoutExpired` 변환과 returncode/PDF 존재 검사는 subprocess API를 구조화된 mdflow error로 바꾸기 위한 신호화이며, 예외 삼킴으로 보지 않습니다. PDF 단계는 `PdfConverter.convert()`를 그대로 호출하므로 fitz/pymupdf4llm 예외가 `LibreOfficeConverter`에서 흡수되지 않습니다. 바깥 `run_conversion()`은 raw exception만 `CONVERSION_FAILED`로 wrap하고 `MdflowError`는 그대로 통과시키므로 `LIBREOFFICE_UNAVAILABLE`/`TIMEOUT` 코드도 보존됩니다.

### 2. subprocess 생명주기는 안전한 편입니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:49`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:53`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:55`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:82`

임시 디렉터리 안에 합성 파일명 `input.<format>`을 쓰고, `shell=True` 없이 argv list로 `subprocess.run()`을 호출합니다. per-call LibreOffice profile도 temp dir 아래에 있어 동시 실행의 shared profile lock 충돌을 피합니다. `pdf_bytes`는 temp dir이 닫히기 전에 읽히므로 이후 PDF 단계가 temp path에 의존하지 않습니다.

`TemporaryDirectory`는 timeout/nonzero/missing-output 예외 경로에서도 정리됩니다.

### 3. progress remap은 SSE pump 불변식과 맞습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:48`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:83`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:91`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/pdf.py:30`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/pdf.py:37`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/pdf.py:38`

성공 경로의 progress는 `convert:5 -> convert:50 -> pdf parse:55 -> pdf render:80 -> pdf done:100` 형태라 단조 비감소이고 100에서 끝납니다. 모든 callback은 `convert()` 호출 내부에서 동기 실행되므로 M1a SSE pump의 “in-call only” invariant도 깨지 않습니다.

### 4. 합성 설계는 깔끔합니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:34`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:84`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/office.py:91`

`PdfConverter`를 인스턴스로 보유하고 PDF bytes를 `ConversionContext(format="pdf")`로 넘기는 방식은 `_html_to_md`를 공유한 M1b 패턴과 같은 수준의 합성입니다. `pymupdf4llm` 호출을 재구현하지 않아 중복도 없습니다. GPU Marker 체인까지 억지로 끌어오지 않은 것도 M3a 범위에 맞습니다.

### 5. 테스트 전략은 현실적입니다

위치:
- `/home/restful3/workspace/mdflow/tests/conftest.py:138`
- `/home/restful3/workspace/mdflow/tests/conftest.py:144`
- `/home/restful3/workspace/mdflow/tests/converters/test_office.py:25`
- `/home/restful3/workspace/mdflow/tests/api/test_convert.py:518`

레거시 `.doc`/`.ppt` fixture를 순수 Python으로 생성하기 어렵기 때문에 docx/pptx를 코드 생성한 뒤 soffice로 변환하는 선택은 타당합니다. `@requires_soffice` skip도 올바르게 걸려 있습니다. 손상 입력 에러를 실제 soffice에 맡기지 않고 monkeypatch unit으로 고정한 것도, soffice가 garbage를 유효 PDF로 복구할 수 있다는 관찰이 있다면 더 결정적인 테스트 전략입니다.

### 6. YAGNI/수술적 범위

변경은 `Settings`, `LibreOfficeConverter`, lifespan 등록, doc/ppt fixture/tests, 상태 문서에 국한되어 있습니다. hwp, OCR, GPU PDF chain, 전역 soffice 세마포어 등을 끌어오지 않은 점은 M3a 범위에 맞습니다.

## 결론

M3a는 ship 가능한 상태로 보입니다. 차단급 문제는 없습니다. 후속으로는 M3a 전용 SSE error 매핑 테스트와 subprocess argv/profile assertion, 실패 메시지의 stdout 보강 정도를 추천합니다.
