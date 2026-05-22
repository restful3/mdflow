# mdflow M3b HWP converter 리뷰 - Codex

작성일: 2026-05-22
대상 diff: `git diff v0.3.0-m3a..HEAD`

검증:
- `.venv/bin/python -m pytest -q` -> 255 passed / 2 skipped
- `.venv/bin/python -m pytest -q tests/converters/test_hwp.py tests/api/test_convert.py -k 'hwp or error_code'` -> 5 passed / 1 skipped
- `.venv/bin/ruff check src tests` -> All checks passed
- `docs/specs/2026-05-22-m3b-hwp-design.md`, `docs/superpowers/plans/2026-05-22-m3b-hwp.md`, HWP converter, service/SSE error path, app registration, tests를 실제 파일 기준으로 확인

## Blocking

없음.

M3b의 핵심 설계는 잘 지켜져 있습니다. `HwpConverter`는 top-level에서 `pyhwp`를 import하지 않아 base 설치 환경의 app startup을 깨지 않고, pyhwp import 실패만 `HWP_UNAVAILABLE`으로 구조화합니다. pyhwp/lxml 변환 예외는 컨버터에서 삼키지 않으므로 `ConversionService.run_conversion()`의 비-`MdflowError` wrap 경로를 통해 `CONVERSION_FAILED`로 표면화됩니다.

## Recommendations

### 1. HWP 전용 service/SSE error 테스트를 추가하면 §6 회귀 방지가 더 직접적입니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:42`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:46`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:120`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:125`
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:56`
- `/media/restful3/data/workspace/mdflow/tests/api/test_convert.py:560`

현재 `test_library_error_propagates()`는 converter 단위에서 pyhwp/lxml 예외가 삼켜지지 않는지만 확인합니다. `run_conversion()`이 비-`MdflowError`를 `CONVERSION_FAILED`로 wrap하는 공통 계약은 기존 service 코드로 맞지만, HWP 전용 테스트로도 한 번 고정하면 좋습니다.

추천 테스트:
- `HwpConverter._hwp_to_xhtml`이 `ValueError`를 던지도록 monkeypatch한 뒤 `/convert` `.hwp` 요청의 마지막 SSE event가 `error` / `CONVERSION_FAILED`인지 확인.
- `pyhwp` import 실패를 유도해 `/convert` `.hwp` 요청의 마지막 SSE event가 `error` / `HWP_UNAVAILABLE`인지 확인.

이 테스트들은 실제 fixture 없이 결정적으로 작성할 수 있고, HWP 전용 error surface를 직접 보장합니다.

### 2. pyhwp import 실패 테스트는 import hook 방식이 더 명시적일 수 있습니다

위치:
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:46`
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:48`

현재 `sys.modules["hwp5.xmlmodel"] = None`, `sys.modules["hwp5.hwp5html"] = None` 방식은 실제로 이 환경에서도 통과했고, Python import machinery상 해당 submodule import를 막는 데 동작합니다. 다만 의도를 더 분명히 하려면 `builtins.__import__`를 특정 `hwp5.` 이름에서 `ImportError`를 던지도록 monkeypatch하거나, `_hwp_to_xhtml()` import 부분을 더 작은 helper로 분리해 patch하는 방식도 가능합니다.

필수 수정은 아닙니다. 현 테스트가 vacuous해 보이지는 않습니다.

### 3. pyhwp optional extra의 라이선스/배포 표기를 릴리스 문서에 남기면 좋습니다

위치:
- `/media/restful3/data/workspace/mdflow/pyproject.toml`
- `/media/restful3/data/workspace/mdflow/docs/specs/2026-05-22-m3b-hwp-design.md`

AGPL 샘플을 커밋하지 않는 결정은 타당합니다. `pyhwp` 자체를 optional extra로 둔 것도 base 설치 영향과 라이선스 리스크를 분리하는 좋은 선택입니다. 배포 문서나 README에 `[hwp]` extra가 별도 라이선스 조건을 갖는 의존성을 설치한다는 점을 명시하면 운영자가 판단하기 쉽습니다.

## Notes

### 1. 지연 import 격리는 적절합니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:24`
- `/media/restful3/data/workspace/mdflow/src/mdflow/api/app.py:71`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:20`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:42`

`app.py`는 `HwpConverter`를 항상 import/register하지만, `hwp.py` top-level에는 `pyhwp` import가 없습니다. 실제 optional dependency 접근은 `_hwp_to_xhtml()` 내부에서만 일어나므로 `[hwp]` extra가 없는 base 환경에서도 app factory/lifespan 등록이 깨지지 않습니다.

### 2. 에러 계약은 기존 M1b/M3a 패턴과 일관합니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:43`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:47`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:52`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:122`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:124`

`ImportError`는 도구/extra 부재로 보아 `HWP_UNAVAILABLE`이 맞고, 그 외 `Hwp5File`/`HTMLTransform`/lxml 예외는 그대로 전파됩니다. `run_conversion()`은 `MdflowError`는 보존하고 raw exception만 `CONVERSION_FAILED`로 wrap하므로, 설계 §6의 분류가 실제 코드와 일치합니다.

### 3. 임시파일 lifecycle과 보안 경계는 괜찮습니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:58`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:59`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:60`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:61`

pyhwp가 path 기반으로 OLE storage를 여는 제약 때문에 bytes를 temp file로 쓰는 설계는 합리적입니다. 파일명은 사용자 입력이 아니라 `input.hwp`로 합성되고, temp dir 안에서만 사용되므로 path traversal 위험은 보이지 않습니다. `TemporaryDirectory`는 pyhwp 예외 경로에서도 정리됩니다.

### 4. 출력 처리와 progress도 계약에 맞습니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:57`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:62`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:63`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:64`
- `/media/restful3/data/workspace/mdflow/src/mdflow/converters/hwp.py:65`
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:25`

XHTML bytes를 UTF-8 `errors="replace"`로 decode하는 것은 pyhwp 출력 특성상 보수적이고, `html_to_markdown(..., strip_images=True)`도 단일 XHTML transform의 broken image ref를 피하는 정책과 맞습니다. progress는 `parse:5 -> render:60 -> done:100`으로 단조 증가하고, 모두 `convert()` 내부에서 동기 호출됩니다.

### 5. 테스트 전략은 결정성과 라이선스 제약 사이의 균형이 좋습니다

위치:
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:25`
- `/media/restful3/data/workspace/mdflow/tests/converters/test_hwp.py:46`
- `/media/restful3/data/workspace/mdflow/tests/api/test_convert.py:560`
- `/media/restful3/data/workspace/mdflow/tests/api/test_convert.py:572`

`_hwp_to_xhtml` seam monkeypatch로 temp-file write 이후의 XHTML decode, markdownify, image/style drop, metadata, progress를 deterministic하게 검증합니다. 실제 pyhwp fixture test는 fixture와 pyhwp가 있을 때만 실행되어 CI를 불안정하게 만들지 않습니다. MIT repo에 AGPL 샘플을 커밋하지 않는 결정도 타당합니다.

### 6. 범위는 수술적입니다

변경은 `HwpConverter`, `HWP_UNAVAILABLE`, app registration, optional extra, HWP tests/docs에 집중되어 있습니다. LibreOffice HWP fallback, OCR, 수식/이미지 보존, timeout 등 평가상 비범위로 둔 항목을 끌어오지 않아 M3b 범위에 맞습니다.

## 결론

M3b는 ship 가능한 상태로 보입니다. 차단급 문제는 없습니다. 후속 보강은 HWP 전용 SSE error tests와 optional extra 라이선스 문서화 정도면 충분합니다.
