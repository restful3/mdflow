# 세션 핸드오프 — mdflow M2b(Marker, GPU) 완료, 전 마일스톤 종료

_최종 갱신: 2026-05-23 14:30 KST_

## 🎯 목표
mdflow의 마지막 보류 마일스톤 M2b(Marker GPU PDF 컨버터)를 GPU 호스트에서 spec→plan→TDD 구현→Codex 묶음 리뷰→채택→태그 사이클로 완료. M2a가 깐 GPU 라우팅 배관(`gpu_semaphore(1)` + `queued` 이벤트) 위에 실제 GPU 컨버터를 끼우고 검증.

## ✅ 완료 (이번 세션)

**M2b까지 모든 변경 원격 동기 완료** — `HEAD == origin/master == 9857393`, 태그 `v0.7.0-m2b` 원격에도 반영. 총 7 마일스톤 태그(`v0.0.1-m0` \~ `v0.7.0-m2b`) 전부 push 됨.

- **검증 체크포인트** (turn 마지막): `git push origin master && git push origin v0.7.0-m2b` 성공, `git status --short`는 HANDOFF.md만(이 turn에서 곧 덮어씀). 304 passed / 2 skipped, ruff clean.
- **M2b Marker(GPU) PDF 컨버터 — `v0.7.0-m2b`**
  - **Plan** `docs/superpowers/plans/2026-05-23-m2b-marker.md` — Task 시퀀스, 설치 핀 노트, MCP/CLI 비범위 명시.
  - **`[gpu]` extra**(`pyproject.toml`): `marker-pdf>=1.0`, `torch>=2.4`. 설치 실증: `pip install --index-url https://download.pytorch.org/whl/cu124 'torch>=2.4'` + `pip install marker-pdf` + cu124 force-reinstall로 PyPI의 `torch 2.12+cu13`(driver 12.6 부적합) 덮어쓰기 회복.
  - **`MarkerConverter`** `src/mdflow/converters/marker.py` (a1dcc23 + harden 0756562): `requires_gpu=True`, `formats=("pdf",)`. `can_handle` 세 게이트(`_force_cpu()`/`_cuda_available()`/`_marker_available()`) — round-2에서 `_cuda_available`/`_marker_available`이 broad `Exception` 잡도록 hardening(깨진 torch/marker init 시 raw `INTERNAL` SSE 누출 방지). `convert()`는 lazy import + bytes→임시 PDF→Marker(path) + `text_from_rendered`. `tmp: Path | None = None` 초기화 + `if tmp is not None`로 `NamedTemporaryFile` 실패 시 `UnboundLocalError` 마스킹 방지. PaperFlow VRAM 정리(`del model; gc.collect(); torch.cuda.empty_cache()`)를 outer `finally`에 강제(예외 경로 포함 모든 path에서 실행).
  - **registry first-wins 등록**(`src/mdflow/runtime/composition.py`): `MarkerConverter`를 `PdfConverter` **앞에** 등록. `build_registry(settings, *, allow_gpu=True)` 매개변수 추가 — `allow_gpu=False`면 MarkerConverter 등록 자체에서 제외.
  - **autouse `MDFLOW_FORCE_CPU=1`**(`tests/conftest.py`): 전체 테스트 스위트에서 PyMuPDF 경로 결정성 유지. 실 GPU smoke만 `monkeypatch.delenv` opt-out. fake-GPU 컨버터 테스트는 직접 app registry 주입이라 영향 없음.
  - **실 GPU 검증**: RTX 3060 12GB + driver 12.6 + torch 2.6.0+cu124 + marker-pdf 1.10.2 — `test_marker_real_gpu_smoke` 7초에 fixture PDF에서 "Document Title" 추출, `test_convert_sse_routes_pdf_through_marker_when_gpu_enabled`로 SSE `started.converter="pdf-marker"`+`gpu=True` 통합 검증.
  - **Codex 1라운드 차단 1건 → FIXED**: HTTP-mounted MCP가 같은 FastAPI 프로세스에서 `gpu_semaphore` 우회 가능(M4 시점엔 GPU 컨버터 없어 권고, M2b가 Marker를 들이면서 VRAM 1-모델-1-프로세스 위반으로 승격). `build_mcp(allow_gpu=False)` + `build_registry(allow_gpu=False)` — M4 `allow_path=False` 패턴 동형. stdio MCP는 별도 프로세스라 GPU opt-in 유지. CLI는 별도 프로세스로 in-process semaphore 공유 불가 — 사용자 결정으로 `docs/test-matrix.md` "GPU 동시 실행 정책"에 "서버와 CLI GPU 변환 동시 실행 금지" 명시(`--gpu` opt-in은 후속).
  - **Codex 권고 1·2·3·4 전부 반영**: (1) broad Exception, (2) tempfile masking, (3) GPU install 운영 문서(cu124 force-reinstall + 동시 실행 정책 섹션), (4) SSE marker routing 통합 테스트(`@pytest.mark.gpu`).
  - **Codex 재리뷰 (round-2)**: 첫 줄 정확히 `===CODEX_FINAL_APPROVAL===` 수신(round2 파일 미생성 = M1a/M4 패턴 — 승인이라 정상). **잔존 차단 0건**.

**테스트/린트**: 287 → **304 passed / 2 skipped**(신규 17개: marker unit 10 + 실 GPU smoke 1 + composition 2 + harden 회귀 3(broken torch, broken marker, tempfile masking) + SSE marker routing 1). 2 skip = hwp 실제 fixture 부재 + url redirect step5. ruff clean.

## 🔄 진행 중
없음. M2b 슬라이스가 종료되어 mdflow v1의 모든 합의된 마일스톤(M0\~M5 + M2b)이 채택됨.

## ⏭️ 다음 단계
사용자 결정 필요. 가능한 후속 작업(전부 non-blocking, PROCESS_STATE §8/§11에 기록됨):

1. **GPU Docker 이미지 분기** — 현재는 CPU 단일 이미지(M5 산출). NVIDIA CUDA base + `.[gpu]` + cu124 torch force-reinstall로 별도 태그(예: `mdflow:0.7.0-gpu`). marker 모델 사전 다운로드 여부 결정 필요.
2. **CLI `--gpu` opt-in 플래그** — 현재는 `MDFLOW_FORCE_CPU=1` autouse가 CLI 호출 시 영향을 주지 않으니 운영자가 `MDFLOW_FORCE_CPU=0`로 호출하면 GPU 사용 가능. 명시적 `--gpu` 플래그 + 서버-CLI 간 GPU lockfile 등 동시 실행 방지 메커니즘.
3. **MCP `gpu_semaphore` 공유 주입** — 현재는 HTTP 마운트 MCP에 `allow_gpu=False`로 차단해 문제 회피. 운영상 MCP에서도 GPU가 필요해지면 pool/semaphore를 MCP runtime에 공유 주입 + `_run`/tool에서 SSE와 동형으로 lookup→`requires_gpu` 분기 필요.
4. **M5 DEFER 후속 hardening** — MCP `_run`의 default executor → bounded pool, MCP `convert_file(path)`/`get_cached` cache.read를 executor로 오프로드.
5. **README 신설** — 없음. `[hwp]` AGPL 노트와 `[gpu]` cu124 install 절차를 묶어 정리할 수 있음.

## 🧠 대화에만 있던 핵심 컨텍스트

모든 결정 근거는 commit·spec·`docs/reviews/`·`PROCESS_STATE.md`에 영구 저장됨. 메타-수준 요점만:

- **M2b 설치 함정의 정확한 형태** — `marker-pdf 1.10.2`가 `torch>=2.7`을 요구 + PyPI 기본 resolver는 `torch 2.12.0`(CUDA 13 wheel)을 가져옴 → 이 호스트 driver 12.6은 CUDA 12.x까지만 지원 → `torch.cuda.is_available()`이 `"NVIDIA driver too old"` 경고 후 false 처리. 우회: `--index-url https://download.pytorch.org/whl/cu124 --force-reinstall 'torch==2.6.0+cu124'`. pip resolver는 `marker-pdf 1.10.2 requires torch<3.0.0,>=2.7.0, but you have torch 2.6.0+cu124` 경고를 띄우지만 **실제 import + RTX 3060 inference는 통과**(7s, fixture PDF에서 "Document Title" 추출). marker 안정 채널이 driver를 따라잡거나 호스트 driver를 12.8+로 업그레이드할 때까지 핀 유지. 운영자에게 알려야 함 — `docs/test-matrix.md` "GPU install (M2b)" 섹션에 절차 + 경고 의미 명시.
- **`allow_gpu=False` 결정 근거** — Codex 차단 1의 hotfix 옵션 두 가지(① pool/semaphore 공유 주입, ② MCP에서 GPU 명시거부) 중 ②를 선택. M4의 `allow_path=False` 패턴이 이미 정착돼 있어 동형으로 일관, 5\~10줄 변경으로 끝. 운영에서 MCP가 GPU 필요해지면 ①로 확장(별도 슬라이스). stdio MCP는 별도 프로세스라 SSE와 충돌 없어 GPU opt-in 유지.
- **autouse `MDFLOW_FORCE_CPU=1` 필요 이유** — MarkerConverter를 `PdfConverter` 앞에 등록하면 GPU+marker 있는 호스트에서 모든 PDF 테스트가 Marker로 라우팅(모델 다운로드 + 느린 inference로 깨짐). 실 GPU 분기를 검증하는 테스트만 `monkeypatch.delenv`로 opt-out하는 게 가장 단순한 결정성 유지 방식. fake-GPU 컨버터 테스트(test_convert.py:299/377/416)는 직접 `app.state.registry`를 swap하므로 이 env-gate와 무관.
- **Codex round-2 승인의 형태** — round2 파일이 *생성되지 않는* 것이 승인이다(M1a, M4도 동일 패턴). 첫 줄에 정확히 `===CODEX_FINAL_APPROVAL===`만 출력하면 본문 없이 잔존 차단 0을 의미. round2 파일이 만들어졌다면 추가 차단/권고가 있다는 신호.
- **CLI GPU 동시 실행은 코드로 못 막음** — CLI(`mdflow convert`)는 별도 프로세스에서 `ConversionService.convert` 직접 호출 → 서버 lifespan의 in-process `gpu_semaphore`를 거치지 않는다. 운영 정책으로 "서버와 CLI GPU 변환 동시 실행 금지"를 문서화하는 게 v1 시점의 합리적 선택(사용자 결정). 코드 강제는 OS-level lockfile이나 GPU device reservation이 필요해 별도 슬라이스.
- **Marker API 형태** — `marker.models.create_model_dict()`로 model dict 로드 → `marker.converters.pdf.PdfConverter(artifact_dict=models)(str(path))`로 변환 → `marker.output.text_from_rendered(rendered)`로 `(text, _, images)` 추출. path 입력만 가능(bytes 직접 입력 안 됨) → tempfile 경유. 첫 호출 시 surya-ocr 모델 다운로드(~수백 MB, HF 캐시), 이후엔 캐시 사용해 빠름(이 호스트 모델 캐시는 이미 있어서 7s).

## ⚠️ 클리어 전 주의

- **커밋 안 됨**: 이 turn에서 갱신되는 `HANDOFF.md` 외 없음. `git status --short`는 `HANDOFF.md` 한 줄(다음 commit이 흡수하거나 다음 세션이 다시 덮어씀).
- **미푸시 커밋**: 없음. `HEAD == origin/master == 9857393`. M2b 4개 commit + 태그 `v0.7.0-m2b` 모두 원격 반영 완료.
- **백그라운드**: 폴링 task 2건은 모두 종료. 단, **`md:codex` tmux 윈도우의 codex CLI는 계속 실행 중**(Context 77% used, 5h 99% / weekly 87% — 모두 여유). 다음 세션에서 Codex 리뷰가 필요하면 그대로 재사용 가능. Codex context를 `/clear`하려면 handout-then-clear 절차 필수(codex-peer-reviewer skill Step 8 참조).
- **미완료 todo**: 없음. M2b 슬라이스 task 12개 전부 completed.
- **`.agent_io/` 처리**: `.git/info/exclude`로 의도적 git 제외(orchestration runtime). 커밋 대상 아님.

## 📂 관련 파일

상태 정본:
- `PROCESS_STATE.md` — §2 한눈에 보기 / §4 로드맵 / §8 M2 (M2a + M2b 둘 다 채택) 갱신 완료. 다음 세션 첫 읽기 대상.

이번 세션 산출(신규):
- `docs/superpowers/plans/2026-05-23-m2b-marker.md` — M2b plan
- `docs/reviews/2026-05-23-m2b-marker-codex.md` — Codex round-1 review (차단 1 + 권고 4 + 메모 8)
- `src/mdflow/converters/marker.py` — MarkerConverter

이번 세션 산출(갱신):
- `pyproject.toml` — `[gpu]` extra
- `src/mdflow/runtime/composition.py` — MarkerConverter 등록 + `allow_gpu` 매개변수
- `src/mdflow/mcp/server.py` — `build_mcp(*, allow_gpu)` 매개변수
- `src/mdflow/api/app.py` — `build_mcp(allow_path=False, allow_gpu=False)` 마운트
- `tests/conftest.py` — `requires_gpu_runtime` skip 마커 + autouse `MDFLOW_FORCE_CPU=1`
- `tests/converters/test_marker.py` — 14 단위 테스트(게이팅·VRAM cleanup·broken-torch/marker·tempfile masking) + 1 실 GPU smoke
- `tests/test_composition.py` — Marker 등록 순서 assert + `allow_gpu=False` 회귀
- `tests/api/test_convert.py` — SSE marker routing 통합(`@pytest.mark.gpu`)
- `docs/test-matrix.md` — pdf-marker 행 COVERED + "GPU install (M2b)" + "GPU 동시 실행 정책" 섹션
- `PROCESS_STATE.md` — §8 M2b 체크박스/최종 갱신 시각

핵심 진입점(변경 없음):
- HTTP: `mdflow.api.app:create_app`
- stdio MCP: `mdflow-mcp` = `mdflow.mcp.server:main`
- CLI: `mdflow` = `mdflow.cli:app` (convert, serve)

M2b 커밋 시퀀스:
```
9857393 docs(state): M2b adopted — Codex round-2 final approval
0756562 fix(m2b-harden): block GPU converters in HTTP-mounted MCP + Codex hardening
7219962 docs(m2b): plan + state + test-matrix for Marker integration
a1dcc23 feat(m2b): MarkerConverter (GPU PDF) with first-wins registry gating
```
