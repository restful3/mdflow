# 세션 핸드오프 — mdflow M2 (PDF) 완료, M2b는 GPU 대기
_최종 갱신: 2026-05-22 18:30_

## 🎯 목표
mdflow에 문서→Markdown 컨버터를 마일스톤 단위로 추가. 이번 세션은 M1b 마무리 → **M2a(PDF CPU + GPU 라우팅 배관) 구현·Codex 승인·태그**까지 완료. M2b(Marker GPU)는 이 호스트에 GPU가 없어 보류.

## ✅ 완료 (이번 세션)
- **M1b** 사무 컨버터 4종 + 골든 하니스 — Codex 차단 0, 권고 3건 반영(M1b-harden), 태그 **`v0.1.0-m1b`**
- **M2a** PDF: `pdf-pymupdf4llm` 컨버터(`pymupdf4llm`, core 의존) + `convert.py` GPU dispatch(`_run_conversion_stream` 추출 + `gpu_lock`+`queued`, fake-GPU로 검증) + 등록 + PDF/손상/GPU-error/disconnect/cached-hit SSE 테스트
  - opus holistic → ready-to-ship. **Codex 1차: 차단 1건 → 수정(`ca299ec`) → round-2 `===CODEX_FINAL_APPROVAL===`**. 채택.
  - 태그 **`v0.2.0-m2a`** (@`1859d86`). **240 passed / 1 skipped**, ruff clean. 트리 깨끗.
- **M2b kickoff(.agent_io/Tori)** 처리 → host-independent 체크포인트 작성, GPU 블로커 명시(no commit)

## 🔄 진행 중
- 없음 (M2a 닫힘). M2b는 GPU 호스트 대기 상태로 **차단**.

## ⏭️ 다음 단계
1. **M2b (Marker GPU) — CUDA GPU 호스트에서 실행**. 슬라이스 계획은 `.agent_io/claude/output.md`(이번 턴 체크포인트)에 순서대로 있음:
   ① `[gpu]` extras(`marker-pdf`,`torch`) 추가 → GPU 호스트 `pip install -e ".[gpu]"` → `torch.cuda.is_available()`/`import marker` 확인
   ② `pdf-marker` 컨버터(`requires_gpu=True`, `can_handle` GPU 게이팅, PyMuPDF **앞에** 등록, VRAM 정리 `del model;gc.collect();torch.cuda.empty_cache()`, §6 자체 try/except 금지)
   ③ CPU에서도 가능한 검증: GPU 없으면 `can_handle` False → pdf가 `pdf-pymupdf4llm`로 폴백. GPU 호스트: 골든 + `/convert` SSE, M2a `gpu_lock`/`queued` 분기에서 실행 확인
   ④ Codex 묶음 리뷰 → 태그(`v0.3.0-m2b`)
2. 대안: **M3** (LibreOffice → PDF 폴백, doc/ppt/hwp) — GPU 불필요, 이 호스트에서 진행 가능.
3. 또는 M1 hardening 잔여(cache 동시성/lifecycle, disconnect 취소 정책, URL temp streaming, language_hint).

## 🧠 대화에만 있던 핵심 컨텍스트
- **결정 (M2a GPU 세마포어 해제)**: GPU 세마포어를 변환 **task의 done-callback**으로 해제(제너레이터 scope 아님). 이유: client disconnect 시 제너레이터가 닫혀도 ThreadPoolExecutor 변환은 취소 안 되고 계속 도는데, scope 해제면 세마포어가 작업보다 먼저 풀려 두 번째 GPU 변환이 동시 진입 → VRAM 직렬화 붕괴. Codex가 1차에서 이 차단을 잡음(holistic 리뷰는 놓침). `_run_conversion_stream`은 이제 **이미 생성된 task**를 받음.
- **발견 (테스트 하니스)**: httpx `ASGITransport`는 응답을 **버퍼링**해 mid-flight 상태 관찰 불가 → disconnect 회귀 테스트는 **raw ASGI**로 직접 구동(body 주입 → 첫 청크 후 `http.disconnect`). 이 테스트는 구버전(scope 해제)에서 fail함을 실증해 차별성 확인됨.
- **결정 (fallback chain, Codex #11)**: 별도 체인 실행기/런타임 에러폴백 안 만듦. 능력 게이팅(`can_handle`) + 등록 순서로 해소(Marker가 GPU 게이팅, PyMuPDF 앞에 등록 → first-wins가 곧 자동 분기). §6(예외 삼킴 금지)와 충돌하는 에러폴백은 비목표.
- **배제**: 이 호스트에서 Marker 코드 작성 — marker API를 import/테스트할 수 없어 추측성 코드가 되므로 작성 안 함(체크포인트만). torch/marker/CUDA 전부 부재.
- **⚠️ `.agent_io` 파일-IPC 채널 (Tori 오케스트레이터)**: 다른 tmux 세션/에이전트("Tori")가 `.agent_io/claude/input.md`로 작업을 큐잉, 나는 `output.md`+`status.json`에 체크포인트를 씀(README는 `.agent_io/README.md`). **세션 초반엔 STALE 루프**(M0 시절 권고 #4/#5/#6 재발화)가 5분마다 반복됐고 사용자가 오케스트레이터를 중단시킴. **현재 input.md는 진짜 M2b kickoff**(`updated_at` 신선, summary "M2b kickoff queued by Tori"). 다음 세션: input.md를 **다시 읽고 mtime/summary로 신선도 확인** 후 처리 — stale면 재적용 금지.

## ⚠️ 클리어 전 주의
- **커밋 안 됨**: 없음. 트리 깨끗(`git status` empty). M2a 전부 커밋·태그됨. `.agent_io/claude/{output.md,status.json}`는 gitignored 채널 파일(커밋 대상 아님) — 이번 턴 M2b 체크포인트로 갱신됨.
- **백그라운드**: tmux 세션 `md`의 `codex` 윈도우(window 2)에 Codex CLI 실행 중(Context ~63%). `/clear`로 안 사라짐 — `tmux select-window -t md:codex`. Codex 폴링 백그라운드 태스크는 모두 종료. 활성 백그라운드 Bash 없음.
- **미완료 todo**: 없음.

## 📂 관련 파일
- `PROCESS_STATE.md` — **정본 상태**. §2 한눈에 보기 + §8(M2): M2a DONE/채택, M2b PENDING(GPU 호스트 필요). 정확·최신.
- `.agent_io/claude/output.md` — **이번 턴 M2b 체크포인트**(스코프·블로커·GPU-호스트 슬라이스 순서). M2b 시작 시 먼저 읽을 것.
- `.agent_io/claude/{input.md,status.json}` — Tori 채널(input=큐된 지시, status=`blocked`/needs GPU host). gitignored.
- `docs/specs/2026-05-22-m2-pdf-design.md` — M2 설계(§10에 M2b 노트). `docs/superpowers/plans/2026-05-22-m2-pdf.md` — M2a 계획.
- `docs/reviews/2026-05-22-m2-pdf-codex.md` — M2a Codex 리뷰(차단 1건 + 권고 3). (round-2는 승인토큰만, 파일 없음)
- `src/mdflow/api/convert.py` — SSE 핸들러. `_run_conversion_stream`(task 받음) + GPU 분기(acquire→task→done-callback release→queued). M2b Marker가 이 분기에 드롭인.
- `src/mdflow/converters/pdf.py` — `pdf-pymupdf4llm`. `app.py` lifespan에 컨버터 등록(M2b는 `pdf-marker`를 PyMuPDF 앞에 추가).
- `src/mdflow/runtime/{capabilities,concurrency}.py` — GPU detect + `gpu_semaphore`/`gpu_lock`(gpu_lock은 현재 convert.py 미사용, 잔존 인프라).
- `CLAUDE.md` — 운영 규칙(작은 슬라이스, Codex milestone 리뷰, 수술적 변경, §6 예외 전파).
