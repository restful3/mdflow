# M2b Codex Review — Marker(GPU) PDF Converter

**검토자**: codex (gpt-5.5)
**검토일**: 2026-05-23
**대상**: git diff v0.6.0-m5..HEAD

## 자체 검증

- pytest 결과: `.venv/bin/python -m pytest -q` 통과. 299 passed / 2 skipped. skip은 hwp fixture 부재 1건, URL redirect status 1건. Marker real GPU smoke도 이 호스트에서 실행됨.
- focused pytest: `.venv/bin/python -m pytest tests/converters/test_marker.py tests/test_composition.py -q` 통과. 13 passed.
- ruff: `.venv/bin/ruff format --check src tests && .venv/bin/ruff check src tests` 통과.
- runtime 확인: torch `2.6.0+cu124`, `torch.cuda.is_available() == True`, marker import 성공.

## 차단 (Blocking)

### 1. HTTP-mounted MCP가 실제 Marker GPU 컨버터를 세마포어 없이 실행할 수 있음

M4에서 non-blocking이었던 "MCP `_run`은 default executor를 쓰고 `gpu_semaphore`를 우회한다"는 지적은 그때 등록된 `requires_gpu=True` 컨버터가 없어서 권고로 충분했습니다. M2b 이후에는 `MarkerConverter(requires_gpu=True)`가 `build_registry()`에 실제 등록되므로 같은 문제가 VRAM 직렬화 불변식 위반으로 승격됩니다.

근거:
- Marker는 `requires_gpu=True`입니다: `src/mdflow/converters/marker.py:92-95`.
- HTTP `/convert`만 `lr.converter.requires_gpu`를 보고 `pool.gpu_semaphore`를 획득합니다: `src/mdflow/api/convert.py:239-251`.
- MCP runtime은 같은 `build_registry()`를 사용하지만 `Runtime`에 pool/semaphore가 없고, tool 실행은 `loop.run_in_executor(None, ...)`로 곧장 `runtime.service.convert(...)`를 호출합니다: `src/mdflow/mcp/server.py:37-50`, `src/mdflow/mcp/tools.py:52-63`, `src/mdflow/mcp/tools.py:94-95`, `src/mdflow/mcp/tools.py:103-113`.
- `create_app()`는 같은 FastAPI 프로세스에 `/mcp`를 마운트합니다: `src/mdflow/api/app.py:70-86`.
- PROCESS_STATE도 "M2b가 합류하면 SSE+MCP 함께 재설계"였던 M4 노트를 보존하고 있습니다: `PROCESS_STATE.md:522`. 현재 M2b 노트는 "단일 프로세스에서 두 transport가 동시에 GPU 호출하는 시나리오가 없으면 무해"라고 쓰지만, `/convert`와 mounted `/mcp`는 바로 같은 서버 프로세스의 동시 transport입니다: `PROCESS_STATE.md:466`.

영향:
- `/convert`가 Marker 변환 중일 때 `/mcp`의 `convert_file(content_base64=PDF)` 또는 `convert_url(PDF)`가 동시에 Marker 모델을 로드할 수 있습니다.
- M2a의 "VRAM 1-모델-1-프로세스" 불변식과 `queued` 이벤트 설계가 MCP 경로에서 깨집니다. OOM, CUDA allocator fragmentation, 두 변환 모두 실패하는 상태가 가능합니다.

권장 수정:
- HTTP-mounted MCP runtime에 FastAPI `app.state.pool.gpu_semaphore`를 공유 주입하고, `_run`/tool 실행에서 `service.lookup()` 후 `requires_gpu`이면 같은 세마포어를 잡아 `service.run_conversion()`을 호출하도록 SSE와 동형으로 나누세요.
- 더 작은 hotfix는 MCP HTTP runtime에 `allow_gpu=False` 또는 `force_cpu=True`를 주입해 Marker를 비활성화하고 PyMuPDF로 fallback시키는 것입니다. stdio MCP도 GPU 사용을 opt-in으로 두면 안전합니다.
- CLI는 별도 프로세스라 in-process semaphore 공유가 불가능합니다. 운영 문서에 "서버와 CLI GPU 변환을 동시에 돌리지 말 것"을 명시하거나, CLI 기본을 CPU로 두고 `--gpu` opt-in을 추가하는 편을 권합니다. 단, 같은 FastAPI 프로세스의 mounted MCP 문제는 코드로 막아야 합니다.

## 권고 (Recommendations)

1. `can_handle` availability probe는 import-time `Exception`도 안전 fallback으로 처리하는 편이 좋습니다.
   - `_cuda_available()`은 `import torch`의 `ImportError`만 잡고, `_marker_available()`도 `import marker`의 `ImportError`만 잡습니다: `src/mdflow/converters/marker.py:36-52`.
   - 깨진 torch wheel, CUDA shared library 문제, marker의 transitive dependency 초기화 실패는 `ImportError`가 아닌 `OSError`/`RuntimeError`/Pydantic 계열 예외로 날 수 있습니다.
   - `Registry.select()`는 `can_handle()` 예외를 잡지 않습니다: `src/mdflow/core/registry.py:21-27`. HTTP `/convert`에서는 lookup 단계의 unexpected exception이 `INTERNAL` SSE error가 되어 PyMuPDF fallback이 아니라 서버 내부 오류처럼 보입니다.
   - 권장: availability probe에서는 broad `Exception`을 잡아 debug log 후 `False`를 반환하세요. 실제 `_load_models()`/`_marker_convert()` 단계의 예외는 현재처럼 전파해 `CONVERSION_FAILED`가 되게 두면 §6 계약과 일치합니다.

2. 임시 파일 생성 실패 시 `tmp` 미할당으로 원 예외가 가려질 수 있습니다.
   - `tmp`는 `NamedTemporaryFile` 컨텍스트 내부에서만 할당되고, 바로 다음 `finally`에서 `tmp.unlink(...)`를 호출합니다: `src/mdflow/converters/marker.py:112-120`.
   - `NamedTemporaryFile()` 생성 또는 `f.write(ctx.data)`가 실패하면 `tmp`가 없어서 `UnboundLocalError`가 원 예외를 덮을 수 있습니다. 매우 드문 환경 오류지만, lifecycle 보장을 더 단단히 하려면 `tmp: Path | None = None`으로 초기화하고 `if tmp is not None: tmp.unlink(...)` 형태가 낫습니다.
   - `tests/converters/test_marker.py:135-143`은 파일 삭제만 확인하고 "파일에 bytes가 쓰였다"는 주석과 달리 실제 내용 검증은 하지 않습니다. `_marker_convert` stub에서 `path.read_bytes()`를 기록하면 이 경로를 더 직접적으로 잠글 수 있습니다.

3. `torch 2.6+cu124` 우회는 기능상 실증됐지만, 운영 설치 문서가 필요합니다.
   - `[gpu]` extra는 `marker-pdf>=1.0`, `torch>=2.4`만 선언합니다: `pyproject.toml:37-40`.
   - `marker-pdf 1.10.2`는 `torch>=2.7`을 요구하고, 일반 pip resolver는 이 호스트 driver 12.6과 맞지 않는 최신 CUDA wheel을 고를 수 있습니다. PROCESS_STATE에는 `torch==2.6.0+cu124` force reinstall 절차와 resolver warning을 기록했습니다: `PROCESS_STATE.md:465`.
   - 위험은 API incompatibility, marker 내부에서 torch>=2.7 API를 나중에 사용하기 시작하는 경우, silent numerical/performance regression입니다. 현재 smoke는 "Document Title" 추출까지 확인했으므로 M2b 수용에는 충분하지만, 운영자는 이 pin이 supported matrix 밖이라는 사실을 알아야 합니다.
   - 권장: README 또는 `docs/test-matrix.md` 근처에 "GPU install on CUDA 12.x driver" 섹션을 두고, `pip install marker-pdf` 후 cu124 torch force-reinstall 절차, pip conflict warning의 의미, 검증 명령(`python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'`, `pytest -m gpu`)을 명시하세요. 가능하면 constraints 파일을 별도 제공하세요.

4. `MDFLOW_FORCE_CPU=1` autouse 정책은 적절하지만, GPU 경로 통합 테스트가 direct converter smoke에 한정됩니다.
   - autouse fixture는 전체 suite에서 Marker routing을 끄고, real GPU smoke만 `monkeypatch.delenv`로 opt-out합니다: `tests/conftest.py:167-177`, `tests/converters/test_marker.py:164-172`.
   - 이 정책은 기존 fake-GPU SSE tests와 충돌하지 않습니다. 그 테스트들은 직접 fake converter를 app registry에 주입하므로 `MarkerConverter.can_handle()`의 env gate와 무관합니다.
   - 다만 실제 `/convert` SSE가 `pdf-marker`를 선택해 `started.gpu=true`와 semaphore branch를 타는 통합은 현재 direct converter smoke와 기존 fake-GPU tests의 조합으로 간접 검증됩니다. blocking #1 수정 시 MCP/HTTP 공통 GPU gate test와 함께 실제 Marker 선택 path를 하나 더 추가하면 좋습니다.

## 메모 (Notes)

1. §6 에러 계약은 Marker convert path에 대해 대체로 맞습니다. `_load_models()`, `_marker_convert()`, `_text_from_rendered()` 예외를 `MarkerConverter.convert()`가 catch하지 않으므로 `ConversionService.run_conversion()`이 non-`MdflowError`를 `CONVERSION_FAILED`로 wrap합니다: `src/mdflow/converters/marker.py:106-129`, `src/mdflow/core/service.py:91-97`.

2. VRAM cleanup은 happy / load-error / convert-error 세 경로에서 실행됩니다. `models = None`으로 초기화한 뒤 outer `finally`에서 `del models; _cleanup_vram()`을 호출하므로 `UnboundLocalError`는 없습니다: `src/mdflow/converters/marker.py:107-129`. 테스트도 세 경로의 cleanup 호출을 확인합니다: `tests/converters/test_marker.py:122-132`, `tests/converters/test_marker.py:146-158`.

3. `_cleanup_vram()`은 `gc.collect()` 후 torch import / `cuda.is_available()` / `empty_cache()` 예외를 모두 삼켜 cleanup 자체가 conversion error를 덮지 않게 합니다: `src/mdflow/converters/marker.py:78-86`. 이 선택은 적절합니다.

4. `can_handle()`의 정상 게이트 순서는 의도와 맞습니다. format mismatch, `MDFLOW_FORCE_CPU`, CUDA absence, marker absence가 모두 False를 반환하고, `MarkerConverter`가 `PdfConverter` 앞에 등록되어 first-wins fallback이 됩니다: `src/mdflow/converters/marker.py:97-104`, `src/mdflow/runtime/composition.py:32-35`, `tests/test_composition.py:20-23`.

5. 임시 PDF는 `NamedTemporaryFile(delete=False)`로 marker path API에 넘긴 뒤 `finally`에서 삭제합니다: `src/mdflow/converters/marker.py:112-120`. `delete=False` 자체는 Windows 호환 path handoff 관점에서도 합리적이고, 경로는 OS temp에 랜덤 생성되므로 심볼릭/경로 주입 위험은 낮습니다.

6. cache hit은 `service.lookup()` 단계에서 converter 실행 전 반환되므로 Marker model load/VRAM cleanup이 필요 없습니다. 이 동작은 기존 cache semantics와 일치합니다.

7. `docs/test-matrix.md`의 converter set은 `build_registry(Settings()).list_formats()`와 일치합니다. `pdf-marker`와 `pdf-pymupdf4llm`이 모두 `pdf` row로 있고 marker가 앞입니다: `docs/test-matrix.md:22`, `src/mdflow/runtime/composition.py:32-35`.

8. `PROCESS_STATE.md`의 "M0~M5 + M2b 모든 마일스톤 구현 완료" 표현은 blocking #1 해결 전에는 "M2b 구현 완료, 리뷰 차단 처리 전" 정도가 더 정확합니다: `PROCESS_STATE.md:6`.

## 7개 포커스 항목별 판정

1. §6 에러 계약 — **PASS**. Marker load/convert/text 예외를 converter가 삼키지 않고 `run_conversion()` wrap에 맡깁니다. 단, availability probe 예외는 fallback predicate 성격이라 별도 권고 1을 남겼습니다.
2. VRAM finally — **PASS**. happy/load-error/convert-error 모두 `_cleanup_vram()`이 실행되고, `models = None` 후 `del models`라 미할당 에러는 없습니다.
3. `can_handle` 게이팅 — **PARTIAL**. 정상 `False` 케이스와 first-wins fallback은 맞습니다. import-time non-`ImportError`가 fallback이 아니라 lookup exception이 될 수 있어 hardening 권고가 필요합니다.
4. 임시 PDF lifecycle — **PASS with recommendation**. 정상/convert-error 삭제는 보장됩니다. temp 생성/write 실패 시 `tmp` 미할당 masking 가능성은 권고 2로 남깁니다.
5. autouse `MDFLOW_FORCE_CPU=1` 정책 — **PASS**. 일반 테스트 결정성을 지키고 real GPU smoke는 opt-out합니다. fake-GPU converter tests와 충돌하지 않습니다.
6. `torch 2.6+cu124` 핀 — **PASS with operational risk**. 이 호스트에서 import/inference는 통과했지만 marker-pdf declared requirement 밖이라 운영 문서/constraints가 필요합니다.
7. MCP/CLI `gpu_semaphore` 미적용 — **FAIL / BLOCKING for mounted MCP**. M2b 이후 `/mcp`는 같은 FastAPI process에서 실제 Marker를 세마포어 없이 실행할 수 있습니다. CLI는 별도 프로세스라 문서/opt-in 정책 권고 대상입니다.
