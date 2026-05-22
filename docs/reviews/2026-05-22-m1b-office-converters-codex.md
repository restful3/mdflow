# mdflow M1b office converters 리뷰 - Codex

작성일: 2026-05-22
대상 diff: `git diff eeb5d88 c72dd4b`

검증:
- `.venv/bin/python -m pytest -q` -> 191 passed / 1 skipped
- `.venv/bin/ruff check src/mdflow/converters src/mdflow/api/app.py tests/converters tests/golden.py tests/api/test_convert.py` -> All checks passed
- `docs/specs/2026-05-22-m1b-office-converters-design.md`, converter 구현, lifespan 등록, format detect, golden 하니스를 실제 파일 기준으로 확인

## Blockers

없음.

설계 §6의 핵심 계약은 지켜져 있습니다. `DocxConverter`, `PptxConverter`, `XlsxConverter`, `HtmlConverter`는 라이브러리 예외를 자체 `except`로 삼키지 않습니다. `spreadsheet.py`의 `try/finally: wb.close()`는 자원 정리 전용이고 예외 전파를 보존하므로 허용 범위입니다. 실제로 손상된 docx/pptx/xlsx bytes는 각 라이브러리 예외가 그대로 올라오며, 현재 `ConversionService.run_conversion()`에서 `CONVERSION_FAILED`로 wrap되는 경로와 맞습니다.

ProgressCallback 계약도 위반이 보이지 않습니다. 4종 모두 `convert()` 내부에서 동기적으로 `progress(...)`를 호출하고 성공 경로는 `("done", 100)`으로 끝납니다. 별도 thread/async task를 띄우는 구현은 없습니다.

Protocol과 등록도 충족합니다. 4종 모두 `name`, `formats`, `requires_gpu`, `can_handle`, `convert` 표면을 갖고 있고, lifespan에서 `TextConverter` 다음에 `DocxConverter`, `PptxConverter`, `XlsxConverter`, `HtmlConverter`가 등록됩니다. `format_detect`는 ext, MIME/Content-Type, OOXML/HTML magic 경로에서 docx/pptx/xlsx/html을 이미 인식합니다.

## Recommendations

### 1. PPTX/XLSX Markdown table cell escaping을 후속으로 넣는 편이 좋습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/pptx.py:82`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/spreadsheet.py:47`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/spreadsheet.py:51`

현재 PPTX/XLSX 표는 cell text를 그대로 `" | ".join(...)`에 넣습니다. 셀 값에 `|`, newline, carriage return이 들어가면 Markdown table 구조가 깨질 수 있습니다. 사무 문서 표에서는 꽤 현실적인 입력입니다.

M1b를 막을 정도는 아니지만, `text.py`의 CSV 표 렌더링도 같은 한계를 공유하므로 공통 helper로 다음을 처리하면 좋습니다.
- `|` -> `\|`
- `\r\n`/`\n`/`\r` -> `<br>` 또는 space
- leading/trailing whitespace normalize

회귀 테스트는 xlsx cell과 pptx table cell에 `a|b` 및 multi-line 값을 넣어 golden 또는 구조 assert로 고정하면 됩니다.

### 2. Golden update mode가 CI에서 켜지지 않도록 가드가 있으면 더 안전합니다

위치:
- `/home/restful3/workspace/mdflow/tests/golden.py:24`
- `/home/restful3/workspace/mdflow/tests/golden.py:33`

`MDFLOW_UPDATE_GOLDEN=1`이면 golden mismatch가 전부 "rewrite and pass"가 됩니다. 로컬 갱신 UX로는 좋지만, CI 환경변수 누출 시 골든 테스트가 무의미하게 통과할 수 있습니다.

권고:
- CI에서 `MDFLOW_UPDATE_GOLDEN`이 설정되어 있으면 hard fail하도록 하거나,
- `MDFLOW_UPDATE_GOLDEN=1`과 `MDFLOW_ALLOW_GOLDEN_WRITE=1` 같은 이중 opt-in을 요구하세요.

현재 커밋된 golden 파일 자체와 exact 비교 방식은 좋습니다. 이 권고는 테스트 운영 안전장치입니다.

### 3. 손상 입력이 SSE `CONVERSION_FAILED`로 끝나는 통합 테스트를 4종 중 최소 1~2개 추가하면 좋습니다

위치:
- `/home/restful3/workspace/mdflow/tests/api/test_convert.py:237`
- `/home/restful3/workspace/mdflow/tests/converters/test_docx.py:32`
- `/home/restful3/workspace/mdflow/tests/converters/test_pptx.py:36`
- `/home/restful3/workspace/mdflow/tests/converters/test_spreadsheet.py:36`

현재 M1a의 fake `BoomConverter` 테스트가 raw exception -> `CONVERSION_FAILED` terminal SSE를 검증하므로 core 계약은 덮입니다. 다만 M1b에서 중요한 것은 "실제 라이브러리 예외를 converter가 삼키지 않는다"이므로, 손상된 docx/pptx/xlsx bytes를 `/convert`로 보내 마지막 이벤트가 `error` / `CONVERSION_FAILED`인지 확인하는 테스트가 있으면 §6 회귀 방지가 더 직접적입니다.

HTML은 parser가 관대해서 손상 입력이 예외가 아니라 fallback markdown으로 갈 수 있으니, 이 테스트는 OOXML 3종 중 하나 또는 전부가 적합합니다.

## Notes

### 1. 이미 수용된 두 사항에 동의합니다

docx 표의 빈 헤더 합성은 mammoth/python-docx 기본 동작에서 오는 현재 v1 한계로 보이며, golden에 충실히 캡처되어 있습니다. 이 리뷰에서 문제로 보지 않습니다.

`html.py`가 `text.py`의 사설 `_decode`를 재사용하는 것도 설계에 명시된 허용 사항이고, 이 범위에서는 중복을 줄이는 실용적 선택입니다.

### 2. Converter별 구현은 M1b 범위에 맞게 작고 일관적입니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/converters/docx.py:33`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/pptx.py:30`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/spreadsheet.py:30`
- `/home/restful3/workspace/mdflow/src/mdflow/converters/html.py:34`

docx는 mammoth -> shared markdownify, pptx는 title/body/notes/table, xlsx는 sheet heading + table, html은 trafilatura + BeautifulSoup/markdownify fallback으로 책임이 명확합니다. 이미지/레이아웃 비목표도 코드와 설계가 일치합니다.

### 3. Lifespan 등록과 SSE 통합 smoke는 의미 있게 작성되어 있습니다

위치:
- `/home/restful3/workspace/mdflow/src/mdflow/api/app.py:60`
- `/home/restful3/workspace/mdflow/tests/api/test_convert.py:237`

포맷별 `/convert` 테스트가 `started.converter`를 확인하고 `done.markdown`을 golden과 비교하므로, 단순히 converter unit만 통과하는 것이 아니라 app factory 등록, detection, registry select, SSE done 경로까지 함께 확인합니다.

### 4. Golden harness는 전체 문자열 exact 비교라 회귀 감지력이 있습니다

위치:
- `/home/restful3/workspace/mdflow/tests/golden.py:16`
- `/home/restful3/workspace/mdflow/tests/golden.py:24`

trailing whitespace와 최종 newline만 normalize하고 본문은 exact diff로 비교하는 방식이라, "대충 포함 여부만 보는" 약한 골든은 아닙니다. 변경 시 unified diff가 나오는 점도 리뷰하기 좋습니다.

## 결론

M1b 구현은 태그/다음 단계로 넘어갈 수 있는 수준입니다. 최우선 계약인 예외 전파, progress 동기 호출, Protocol 준수, 등록 완전성에 차단급 문제는 없습니다. 후속 hardening으로는 표 cell escaping과 golden update mode 가드, 실제 OOXML 손상 입력 SSE 테스트를 추천합니다.
