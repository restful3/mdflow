# mdflow — PROCESS_STATE.md

> 본 문서는 mdflow 프로젝트의 **정본 상태 문서**다. 이전 정본인 `STATE.md`는 `archive/STATE_20260522.md`에 보존되었다. `STATE.md`의 모든 맥락(설계 결정·트레이드오프·리스크·잊지 말 결정)은 본 문서에 그대로 흡수되었다.

**최초 작성**: 2026-05-22
**최종 갱신**: 2026-05-22 (**M2 Task 3 완료** — GPU dispatch in /convert: `_run_conversion_stream` 헬퍼 추출 + GPU 브랜치(`gpu_lock` + `queued` 이벤트). 229 passed/1 skipped, ruff clean. commit `929dafa`. 다음: M2 Task 4 (PDF 컨버터 등록 + SSE 통합 테스트))

---

## 0. 문서 운영 규칙

### 0.1 자율 업데이트 (Self-Update)

본 문서는 **에이전트가 별도 지시 없이도 다음 시점에 자동 갱신**한다.

자동 갱신 트리거:

- 주요 기능 구현 완료 (Task 단위 또는 슬라이스 단위 commit 직후)
- 버그 수정 완료 (fix commit 직후)
- Codex 리뷰 요청 송부 / 결과 수신 직후
- Phase / sub-phase 시작 또는 종료
- 사용자 결정이 필요한 항목 발생
- 세션 종료 전 (handoff 준비)

갱신 시 최소 다음을 반영:

1. §2 "한눈에 보기"의 현재 phase·테스트 상태·다음 액션
2. 해당 phase의 task 체크박스 (`[ ]` → `[x]`)
3. 새로 발견한 이슈/리스크 실현은 해당 phase 하단 "이슈 / 노트"에
4. 갱신 시각을 문서 상단 "최종 갱신"에 갱신
5. 사용자에게는 변경 사실만 1\~2줄로 알리고 본문은 보여주지 않는다 (사용자가 직접 열어 본다)

업데이트 자체는 commit하지 않고 작업 결과 commit에 함께 묶거나, 별도 `docs(state): ...` commit으로 분리한다 (사용자가 commit 시점을 명시한 경우 그 시점에).

### 0.2 작성 원칙

- 한 phase 안에서는 `[x] 완료 task` → `[ ] 진행/예정 task` 순으로 정렬
- 새로 추가되는 phase가 있으면 §4 로드맵 표와 본문 둘 다 갱신
- "이슈 / 노트"는 phase별로 누적. 해결된 이슈도 지우지 않고 `**RESOLVED**` 마커와 commit hash 함께 보존

---

## 1. 프로젝트 개요

### 1.1 정의 / 최종 목적

`mdflow`는 다양한 문서 포맷(PDF, DOCX, PPTX, HTML, HWP, XLSX, 오래된 DOC/PPT 등)을 받아 **LLM 소비에 적합한 Markdown**으로 변환하는 서비스다. HTTP API와 MCP 서버를 동시에 제공하여 에이전트·RAG·웹 클라이언트 어디서든 단일 호출로 변환할 수 있게 한다.

핵심 가치: **의미 구조 보존**(헤딩 레벨, 리스트, 표, 코드 블록) > 시각 충실도. LLM 입력으로 바로 소비 가능한 Markdown을 만든다.

### 1.2 v1 목표 (In Scope)

- 가능한 모든 일반 사무 문서 포맷을 Markdown으로 변환
- 단일 호출로 진행 상황 + 결과를 함께 받는 **SSE 스트리밍 API**
- 동일 코드에서 **stdio + Streamable HTTP** 두 가지 MCP transport 제공
- **GPU 자동 감지** — 있으면 고품질 경로(Marker), 없으면 경량 CPU 경로
- 동일 입력 재요청 시 **sha256 디스크 캐시**로 즉시 응답
- **URL 입력** — 단일 리소스 GET + 제한된 redirect + SSRF 차단 (v1 7개 원칙은 §3.3)

### 1.3 v1 비목표 (Out of Scope)

- 인증·권한·멀티테넌시 (별도 후속 작업)
- 시각 충실도 보존 (인쇄용 PDF 재현 등)
- Markdown 편집 UI (PaperFlow viewer 담당)
- **번역·요약** (호출자 혹은 PaperFlow 책임)
- **임의 URL 크롤링 / SPA 렌더링 / 사이트별 변환 규칙** (예: HTML→PDF 링크 추출, arXiv/OpenReview 학술 publisher transformer, citation meta tag 해석)
- **Headless browser / Chromium 기반 print-to-PDF**, 사용자 지정 header/cookie/Authorization 전달, 인증이 필요한 URL fetch

### 1.4 PaperFlow와의 관계

- mdflow는 PaperFlow(`/media/restful3/data/workspace/paperflow`)의 **형제 프로젝트** (sibling, 독립)
- PaperFlow = *PDF 논문 단일 포맷에 대한 끝단 워크플로우 (viewer 포함)*
- mdflow = **범용 변환 게이트웨이**
- 두 프로젝트 독립. 추후 mdflow가 PaperFlow의 업스트림으로 활용 가능
- PaperFlow의 **엔진 패턴 재활용** (참고용): Marker VRAM 정리 (`del model; gc.collect(); torch.cuda.empty_cache()`), 번역 청크 분할
- PaperFlow의 **재활용 회피** 패턴: VRAM 누수, `print()` 로깅 (mdflow는 표준 `logging` 사용)

---

## 2. 한눈에 보기 (현재 상태)

- **현재 phase**: **M1b 컨버터 구현 + Codex milestone 리뷰 완료 (차단 0건) → M1b 사실상 채택**. M1a: Codex 1·2차 최종 승인. M1b: 설계 + 구현 계획 + 컨버터 4종(docx/pptx/xlsx/html) + 골든 하니스 + lifespan 등록 + 포맷별 SSE 통합 테스트 + opus holistic(ready-to-ship) + Codex 묶음 리뷰(차단 0). **다음: M1b 권고 3건을 M1 hardening으로 분리 / (선택) 태그**
- **테스트**: **228 passed / 1 skipped** (`.venv/bin/pytest`; M1b +26, M1b-harden +11). 린트 clean
- **린트**: `ruff check` + `ruff format --check` 통과 (src tests 전체)
- **git**: master 브랜치, 태그 **`v0.0.1-m0`**, **`v0.1.0-m1b`**(@`f687dc4`, M1b+harden 완료점). M1b 코드 `298975a`\~`ab6f92a`(harden 포함). 트리 깨끗. (태그는 로컬만 — push 미실시)
- **실행 방식**: Subagent-Driven Development (`superpowers:subagent-driven-development`). task별 fresh implementer subagent + spec-compliance 리뷰 → code-quality 리뷰, 전체 완료 후 opus 최종 holistic 리뷰
- **M1a 문서**:
  - 설계: `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`
  - 구현 계획: `docs/superpowers/plans/2026-05-22-m1a-sse-infrastructure.md` (Task 0\~9)
- **M1a 구현 결과 (Task별 commit)**:
  - Task 0 `b36836b` python-multipart 의존성 / Task 1 `94ec1ca`+`c980ddf` `Cache.cached_at()` / Task 2 `5d1598e` service 분할(lookup/run_conversion/convert wrapper)
  - Task 3 `65eda1e` `/convert` SSE file 경로(started→progress→done) + 이벤트 펌프 / Task 4 `236cfdb` cache-hit(cached→done) / Task 5 `28cb161` error 경로 테스트
  - Task 6 `3487b8f` url 경로(fetch in executor → 공통 흐름, `_done_event`로 fetch metadata 합성) / Task 7 `5a3bbf8` 입력 검증(file/url 정확히 하나, 400) / Task 8 `17dd70e` 이벤트 펌프 순서 테스트
- **M1a 최종 리뷰 (opus)**: 판정 **"노트된 제약과 함께 ship 가능"**. 이벤트 펌프 race는 **safe-by-construction** 확정
- **M1a Codex 묶음 리뷰**: `docs/reviews/2026-05-22-m1a-sse-infrastructure-codex.md` — **차단 2건 + 권고 4건 + 메모 4건**. 메모 4건(펌프 race·UploadFile import·service split·URL metadata)은 모두 우리 판단에 동의. 반영 결과:
  - **차단 1 (비-MdflowError 절단) — FIXED** `46ae469`+`dbc4269`. 설계 §6이 "예외 전체 → error event"를 요구 → 우리 초기 defer 분류가 틀렸음. run_conversion이 converter 예외를 `CONVERSION_FAILED`로 wrap + 라우트 3경계에 broad except → `INTERNAL` + logger.exception
  - **차단 2 (file 크기 cap) — FIXED** `8bcebec`. `MDFLOW_MAX_INPUT_MB`를 file 경로에도 적용(bounded read + pre-stream 413). URL 경로는 기존 `UrlPolicy.max_bytes`로 이미 적용됨
  - **권고 1 (JSON 입력 검증) — FIXED** `08feff0`. 비-object body/비-string url/invalid JSON → pre-stream 400 (raw 500 방지)
  - **메모 1 + 권고 3 — APPLIED** `dd761c7`. ProgressCallback "synchronous, in-call only" invariant 문서화 + `async with request.form()`로 업로드 리소스 close
  - **권고 2 (client disconnect 시 task 미취소) — DEFER** (Codex도 동의). §7 M1a 알려진 제약 #2 유지. M1b/M2 긴 변환 붙을 때 처리
  - **2차 재리뷰 (round-2)**: 위 반영분(`git diff 96ceffd..HEAD`)을 Codex에 재송부 → 첫 줄 정확히 `===CODEX_FINAL_APPROVAL===` 출력. 추가 수정 파일 없음 = **잔존 이견 0건, M1a 최종 확정**. (Codex가 화면 토큰만 출력하고 별도 round-2 파일은 미생성 — 승인이므로 정상)
- **Codex M0 API 리뷰**: `docs/reviews/2026-05-22-m0-api-surface-codex.md` — **차단 0건**. #1(delete/purge OSError)·#4(shutdown in-flight) DEFER M1. **#3(pool↔service)는 M1a에서 해소**
- **M1b Codex milestone 리뷰**: `docs/reviews/2026-05-22-m1b-office-converters-codex.md` — **차단 0건**. §6 예외 전파·progress 동기 호출·Protocol·등록 완전성 모두 통과 확인. 수용 2건(docx 빈 헤더, `_decode` 재사용)에 Codex 동의. (참고: Codex 자체 pytest는 191/1로 보고했으나 Codex 환경이 신규 테스트를 미수집한 것 — 우리 측 다중 독립 실행은 일관)
- **M1b 권고 3건 — 전부 구현 완료 (M1b-harden, TDD)**:
  - ① 표 셀 escaping `ab6f92a`: 공통 `converters/_md_table.py:escape_table_cell`(`|`→`\|`, 개행→space)를 pptx/xlsx/csv(text) 표 렌더러에 적용. 골든 무영향(특수문자 없음)
  - ② golden CI 가드 `c1d62bf`: `MDFLOW_UPDATE_GOLDEN`이 `CI` 하에 set이면 rewrite 거부(hard-fail)
  - ③ 손상 OOXML SSE 테스트 `186bf60`: garbage docx/pptx/xlsx → 마지막 이벤트 `error`/`CONVERSION_FAILED` (§6 end-to-end 회귀 잠금)
- **다음 액션 (다음 1\~3)**:
  1. M1b + 권고 반영 모두 완료, 차단 0. (선택) `v0.1.0-m1b` 태그 / (선택) M1b-harden 묶음 Codex 재리뷰 — 사용자 판단
  2. M1 잔여 DEFER 항목은 별도 "M1 hardening" 슬라이스로 분리 (cache delete/purge OSError 정규화, shutdown/disconnect 정책, URL temp streaming, language_hint) — M1b 범위에서 제외 확정
  3. **M1b 후속(non-blocking, opus holistic 리뷰 도출)**: (a) docx 표 헤더가 본문 행으로 강등됨 — python-docx/mammoth가 `<th>` 없이 `<td>`만 내보내 markdownify가 빈 헤더 합성. 골든에 충실히 캡처됨. 헤더 행이 있는 실제 docx에선 의미상 부정확 → `_html_to_md` docx 경로에서 첫 `<tr>`을 헤더 승격하거나 한계 문서화. (b) `html.py`가 `text._decode`(사설) 교차 import — 세 번째 소비자 생기면 `converters/_decode.py`로 승격

- **M1a 핵심 설계 결정** (계획/스펙에 상세, 구현으로 확정됨):
  - async 핸들러 orchestrate, `ConversionService`는 sync 유지. asyncio.Queue + `call_soon_threadsafe`로 스레드풀 progress 펌프 (Task 8 순서 테스트로 검증)
  - `convert()`를 `lookup()` + `run_conversion()`으로 분리(wrapper 존치, 회귀 0)해 started(miss)/cached(hit) 구분
  - 입력: 파일(multipart) + url(JSON). url은 핸들러가 `fetch_url`을 executor에서 직접 호출. **구현 발견**: `request.form()`은 `starlette.datastructures.UploadFile`을 반환 → isinstance 체크는 starlette에서 import (fastapi의 것은 starlette의 하위클래스라 raw form 객체와 매칭 안 됨)
  - GPU/queued→M2, shutdown drain→후속, content_base64→M4 (M1a 밖, 확인됨)

작업 디렉토리 깨끗.

---

## 3. 확정 설계 결정 (불변 기준)

### 3.1 9개 핵심 결정

| 결정 영역 | 선택 | 비고 |
|---|---|---|
| 주 소비자 | LLM/에이전트 입력용 | 의미 보존 > 시각 재현 |
| 엔진 전략 | **하이브리드** | 직접 변환 우선 (mammoth, python-pptx 등), 어려운 포맷은 LibreOffice → PDF → Marker fallback |
| API 응답 모델 | **SSE 스트리밍** | 단일 호출로 진행률+결과, MCP·CLI·웹 모두 단순 |
| MCP transport | **stdio + Streamable HTTP 둘 다** | FastMCP, 동일 코드 두 transport |
| GPU 정책 | **자동 감지** | `torch.cuda.is_available()`, `MDFLOW_FORCE_CPU=1`로 override |
| 캐시 | **sha256(콘텐츠+옵션) 디스크 캐시** | `~/.cache/mdflow/<sha256>/result.md` |
| 실행 모델 | **단일 프로세스 + GPU 세마포어(=1) + CPU ThreadPool** | PaperFlow의 VRAM 누수 패턴 재활용 회피 |
| 인증 | **v1 비목표** | 후속 작업, "나중에 검토" |
| 결과 후처리 | **비목표** | 번역·요약은 호출자(혹은 PaperFlow) 책임 |

### 3.2 거부된 대안 (트레이드오프 메모)

"왜 이렇게 정했지?" 재질문 시 참고:

- **엔진** — MarkItDown 단일 wrapper 거부 — per-format 직접 변환이 LLM용으로 더 정확
- **엔진** — 순수 PDF 단일경로 (모든 포맷 → LibreOffice → PDF → Marker) 거부 — DOCX 표·PPTX 노트·HTML 시맨틱 손실, 속도 저하, 무거운 의존
- **API** — 완전 동기 거부 — 대용량 PDF 시 게이트웨이 타임아웃
- **API** — Job 큐 + 폴링 거부 — MCP에서 에이전트 폴링 구현 부담, YAGNI 위반
- **MCP** — stdio만 / HTTP만 거부 — FastMCP로 둘 다 큰 비용 없이 가능
- **실행 모델** — API + 워커 프로세스 분리 거부 — Redis 등 인프라 복잡도. 단순함 우선, GPU 누수 등 문제 발생 시 B로 점진 이전 (인터페이스만 유지)
- **GPU** — GPU 필수 거부 — 노트북·CPU 환경 사용 차단
- **캐시** — 캐시 없음 거부 — Marker PDF는 비싸서 재사용 가치 큼

### 3.3 v1 URL 처리 7개 원칙 (불변)

기준 문서: `docs/reviews/2026-05-21-url-handling-final-agreement.md`. Codex 4라운드 합의로 잔존 이견 0건 도달.

1. **범용 게이트웨이** — 학술 사이트별 transformer는 호출자/PaperFlow 책임
2. **SSRF v1 필수** — IPv4·IPv6·metadata IP·redirect별 재검증
3. **사용자 헤더 / 쿠키 / Authorization 차단** — `follow_redirects=false` 옵션도 없음
4. **cache key는 입력 bytes 기준** — URL 메타데이터(URL, headers)는 제외. 같은 bytes를 두 다른 URL에서 받으면 cache 공유, fetch metadata는 응답별 합성
5. **quality gate (custom 200 bot/error page 감지)는 v1.1** — v1은 HTTP status, size, format detect 중심
6. **Headless browser / SPA는 v1.1** — v1은 정적 문서 가정
7. **DOI pre-resolve 미도입** — 호출자가 알아서 final URL 전달

### 3.4 절대 잊으면 안 되는 결정

- **URL 처리는 합의안 §3 기준** (위 §3.3)
- **TDD 순서 엄수**: failing test → fail 확인 → impl → pass 확인 → ruff → commit. commit 메시지는 `feat(m0): ...` / `fix(m0): ...` / `refactor(m0): ...` 패턴
- **PaperFlow 학술 transformer는 v1 비목표** (PRD §1.2 명시). mdflow는 범용 변환 게이트웨이
- **모든 단계는 작게** — 한 task에 여러 책임이 묶이면 분할 슬라이스로 commit. 사용자가 패턴으로 굳혀 둠
- **인접 코드 "개선" 금지** — 수술적 변경 (CLAUDE.md §3). 망가지지 않은 것을 리팩토링하지 않는다

---

## 4. 전체 Phase 로드맵

| Phase | 상태 | 핵심 범위 |
|---|---|---|
| **Phase 0**. 설계 / 합의 | DONE | PRD 14섹션, URL 처리 합의안, M0 plan (17 TDD task) |
| **Phase M0**. 골격 (skeleton) | **DONE** (17/17, `v0.0.1-m0` 태그) | `pyproject.toml`, `mdflow.core`, `Converter` Protocol, txt/md/csv passthrough, URL fetch helper, ConversionService, FastAPI `/healthz` + admin/cache endpoints |
| **Phase M1**. 사무 포맷 + SSE | **IN PROGRESS** (M1a 구현 완료, Codex 리뷰 대기) | **M1a DONE**: `/convert` SSE 인프라 (Task 0\~8, 186 tests). **M1b**: docx·pptx·xlsx·html 컨버터 + 골든 출력 (미착수) |
| **Phase M2**. PDF | PENDING | Marker (GPU) + PyMuPDF (CPU) 폴백, 자동 감지 분기 |
| **Phase M3**. LibreOffice 폴백 | PENDING | doc/ppt/hwp, fallback 체인 |
| **Phase M4**. MCP | PENDING | FastMCP stdio + HTTP, MCP 4 tool, 진행 알림 |
| **Phase M5**. 운영 도구 | PENDING | CLI, Dockerfile, 메트릭, 통합 테스트 매트릭스 |

---

## 5. Phase 0 — 설계 & 합의 [DONE]

### 5.1 부트스트랩 + 브레인스토밍

- [x] PaperFlow 전체 코드 리뷰/감사 보고서 작성 (architecture·security·quality·performance)
  - 핵심 발견: path traversal, SSRF, 약한 기본값
  - 사용자 결정: "보안 이슈는 나중에 검토" → 별도 세션 / 별도 파일 없음 (이전 세션 대화 로그만)
- [x] 프로젝트 이름 후보 4개 제시 (mdforge / markdrop / docflow / anymd) → **mdflow** 선택
- [x] `~/workspace/mdflow` 디렉토리 생성 (= `/media/restful3/data/workspace/mdflow`, symlinked)
- [x] `superpowers:brainstorming` 호출 → 6개 핵심 설계 인터뷰 (HARD-GATE: 승인 전 코드 작성 금지)
- [x] engine strategy 1회 재조정 (단일 wrapper → **하이브리드**)
- [x] 7개 섹션 설계 초안 제시 → 사용자 승인

### 5.2 PRD 작성

- [x] `docs/specs/2026-05-21-mdflow-design.md` 14섹션 (406줄, URL 처리 v1 정책 반영)
- [x] self-review → PDF/HWP 폴백 체인 정합성 한 곳 수정
- [x] URL 입력 처리에 대해 PaperFlow의 9단계 `import_url_as_paper` 파이프라인과 비교 검토 작성

PRD 14섹션 구성:

1. 개요 (목표·비목표)
2. 사용 시나리오 (MCP / HTTP / 캐시 적중)
3. 아키텍처 (ASCII 다이어그램, 실행 모델, GPU 자동 감지)
4. 컴포넌트 — 22개 모듈 + `Converter` 인터페이스
5. 데이터 흐름 — `POST /convert` 7단계 + SSE 이벤트 스키마
6. API 표면 — 7개 엔드포인트 (`/convert`, `/healthz`, `/capabilities`, `/cache/*`, `/mcp`)
7. MCP 표면 — 4개 tool (`convert_file`, `convert_url`, `list_formats`, `get_cached`)
8. 에러 처리 — 8개 에러 코드 enum + 폴백 체인 + 타임아웃 정책
9. 캐시 정책
10. 테스트 전략 (TDD 명시, GPU/LibreOffice 분리 마커)
11. 의존성 (`pyproject.toml` 그룹 분리)
12. 운영 고려사항
13. 미해결 사항
14. 마일스톤 M0\~M5

### 5.3 URL 처리 Codex 4라운드 합의

- [x] `codex-peer-reviewer` 스킬로 4라운드 진행
  - Claude 검토 → Codex R1: 사실 지적 6건 / 권고 11개
  - Claude 메타리뷰 + Q1\~Q3 → Codex R2: 답변 + PRD 패치 11개
  - Codex Final Agreement → **잔존 이견 0건**
- [x] 5개 산출물 `docs/reviews/`에 보존:
  - `2026-05-21-url-handling-claude-review.md`
  - `2026-05-21-url-handling-codex-round1.md`
  - `2026-05-21-url-handling-claude-meta-review.md`
  - `2026-05-21-url-handling-codex-round2.md`
  - `2026-05-21-url-handling-final-agreement.md` ★ 기준 문서

### 5.4 PRD 패치 + M0 plan 작성

- [x] PRD 11개 패치 적용 (§1.2, §5, §5.1, §6, §7, §8.1, §8.3, §9, §10, §11, §12, §13)
- [x] M0 implementation plan: `docs/superpowers/plans/2026-05-21-m0-skeleton.md` (17 TDD task + TL;DR phases/scope/risks)
- [x] git init + 첫 커밋 (PRD + reviews + plan)

### Phase 0 — 이슈 / 노트

- Codex 4라운드 합의의 비용이 컸지만 v1 URL 정책의 잔존 이견을 0으로 만들었다. **이후 phase에서 "이 URL 동작이 맞나?" 질문이 생기면 `docs/reviews/2026-05-21-url-handling-final-agreement.md`가 단일 기준 문서.**
- "PaperFlow 보안 이슈는 나중에 검토" — 별도 파일 없이 이전 세션 대화 로그만. 핵심: path traversal, SSRF, 약한 기본값.
- v1.1 명시 분리 항목 4개 (PRD §13 등록):
  - SPA / Headless 대응
  - URL 품질 게이트 고도화
  - 인증이 필요한 URL fetch
  - 도메인 allowlist / blocklist 정책
- `superpowers:brainstorming` 스킬은 HARD-GATE — 승인 전 코드 작성 금지. Phase 0의 모든 설계 결정은 이 게이트 안에서 정렬됨.

---

## 6. Phase M0 — 골격 (skeleton) [DONE — `v0.0.1-m0`]

> 17 TDD task, 7개 sub-phase (A\~G). 모든 task: failing test → fail 확인 → impl → pass 확인 → ruff → commit. 작은 슬라이스로 분할 commit 패턴 정착.

### 6.1 M0.A — Bootstrap & core types [DONE]

- [x] **Task 1** Repo bootstrap (`pyproject.toml` hatchling + dependencies + 구조 + smoke import)
- [x] **Task 2** `ErrorCode` enum (15개 코드, `URL_*` 7개 포함) + `MdflowError` exception
- [x] **Task 3** SSE 이벤트 모델 6종 (Started / Queued / Progress / Cached / Done / Error)

### 6.2 M0.B — Settings & detection & converter base [DONE]

- [x] **Task 4** `Settings` (MDFLOW_* env vars 9개 + URL-input cap 검증)
- [x] **Task 5** `format_detect` (extension + magic, magic 우선, disagreement 보고)
- [x] **Task 6** `Converter` Protocol + `Context` / `Result` dataclass

### 6.3 M0.C — Text & registry & cache [DONE]

- [x] **Task 7** `TextConverter` (txt / md / csv passthrough, chardet 인코딩 감지, csv → Markdown table)
- [x] **Task 8** `Registry` (register + select + list_formats, 데코레이터 기반 디스패치)
- [x] **Task 9** `Cache` (sha256 atomic 디스크 캐시 + sha 검증)

### 6.4 M0.D — Runtime [DONE]

- [x] **Task 10** `Capabilities` (GPU detect + 부팅 로그 한 줄, env override)
- [x] **Task 11** `ConcurrencyPool` (GPU 세마포어 = 1 + CPU ThreadPool, `gpu_lock` async ctx + idempotent shutdown)

### 6.5 M0.E — URL fetch helper [DONE]

- [x] **Task 12** `url_fetch` — 합의안 §3.2의 10단계 모두 매핑:
  - validate URL
  - fragment 제거
  - SSRF 검증 (IPv4·IPv6·metadata IP·redirect별 재검증)
  - 고정 User-Agent
  - timeout (connect / read 분리)
  - size cap streaming
  - 2xx status 검증
  - filename hint (Content-Disposition / URL 경로)
  - redirect 정책 (per-hop SSRF, 5회 cap)
  - `FetchResult` metadata 반환 (`url`, `final_url`, `status`, `content_type`, `bytes_read`, `elapsed_s`, `filename_hint`)

### 6.6 M0.F — Service & API [IN PROGRESS]

- [x] **Task 13** `ConversionService.convert(req, progress)` — bytes 입력 cache key 계산 → cache hit/miss → format_detect → registry.select → converter.convert → metadata 보강 → cache write. `ConvertRequest` / `ConvertResponse` dataclass + `ProgressCallback` 타입 alias
- [x] **Task 13b** `url_pipeline.convert_from_url(url, policy, service, options, progress, transport)` — `fetch_url` → bytes → `service.convert`. `UrlConvertResponse(response, fetch dict)` 반환. 합의안 §3.7 핵심 케이스 (같은 bytes 두 다른 URL → cache 공유 + 응답별 fetch metadata) 명시 검증
- [x] **Task 14** FastAPI 앱 팩토리 + lifespan + `/healthz` (`feat(m0): FastAPI app factory + /healthz + lifespan` commit 예정)
  - 새 파일: `src/mdflow/api/app.py`, `tests/api/__init__.py`, `tests/api/test_app.py`
  - lifespan 와이어: `Settings()` → `detect()` → `Registry() + TextConverter` → `Cache(settings.cache_dir)` → `ConcurrencyPool(caps.cpu_workers)` → `ConversionService(registry, cache)` → `url_policy_from_settings(settings)`. 모두 `app.state.*` (`started_at`/`settings`/`capabilities`/`registry`/`cache`/`pool`/`service`/`url_policy`)
  - `/healthz` → `{"ok": True, "uptime_s": ...}`
  - 메모 #10 `url_policy_from_settings(settings) -> UrlPolicy` helper 추가 (URL 6개 설정 → UrlPolicy, MB→bytes 변환). lifespan에서 `app.state.url_policy`로 boot 시 1회 구성
  - **admin 라우트(`register_admin_routes`)는 Task 15로 분리** — 플랜 스니펫은 Task 14에 포함했으나 admin.py 미존재라 import 제거
  - TDD: `test_healthz_returns_ok` + `test_app_lifespan_initializes_state` + `test_url_policy_from_settings_maps_fields` RED(`ModuleNotFoundError`) 확인 후 GREEN (3 passed)
- [x] **Task 15** Admin endpoints — `src/mdflow/api/admin.py` (`register_admin_routes(app)`) + `create_app`에서 호출. `GET /capabilities` (gpu/cuda/cpu_workers + `registry.list_formats()` + `cache.stats()`), `GET /cache/{sha256}` (invalid sha → 400, miss → 404), `DELETE /cache/{sha256}` (miss → 404, 성공 → `{"ok": True}`), `POST /cache/purge` (`{"removed": N}`). TDD 7 tests RED→GREEN
  - **테스트 격리 안전장치**: `tests/api/conftest.py` autouse fixture가 `MDFLOW_CACHE_DIR`을 per-test tmp dir로 리다이렉트. 없으면 `/cache/purge` 테스트가 사용자의 실제 `~/.cache/mdflow` 전체를 삭제함

### 6.7 M0.G — Smoke & tag [DONE]

- [x] **Task 16** M0 integration smoke test — `tests/test_m0_smoke.py` (`pytest.mark.integration`). service text passthrough → cache hit, `/capabilities` cache stats 반영, `validate_url("file://...")` → URL_INVALID, `/healthz`. 모듈 autouse fixture로 `MDFLOW_CACHE_DIR` 격리 (tests/ 루트라 tests/api/conftest.py 미적용). 조립된 골격 검증이라 새 production 코드 없음 — 즉시 통과 정상
- [x] **Task 14\~17 묶음 Codex 리뷰** — `docs/reviews/2026-05-22-m0-api-surface-codex.md`. Codex 자체 검증: `pytest tests/api tests/test_m0_smoke.py` 13 passed, ruff clean. **차단 0건** (M0 태그 가능 판정). 분류:
  - [x] **권고 #1 (부분 ACCEPT)** — admin `GET /cache/{sha}`가 `Cache.read()`의 `MdflowError(CACHE_IO_ERROR)`(오염 meta.json)를 catch 안 해 raw 500 누출. `admin.py`에 `_mdflow_http_error()` helper 추가 → 구조화 503 `{code, message, retryable}`. 사용자 결정 status=503 (retryable 의미). 회귀: `test_cache_get_corrupt_meta_returns_503`. delete에는 미적용 — `Cache.delete`는 MdflowError를 안 올림(일어날 수 없는 핸들링 금지)
  - [x] **권고 #2 (ACCEPT)** — unknown-sha 404 테스트(get/delete)에 `r.json()["detail"] == "cache miss"` assert 추가 → 라우트 부재 404와 cache-miss 404 구분
  - [ ] **권고 #1 잔여 (DEFER M1)** — `Cache.delete`/`purge`의 raw `OSError` 정규화 (§7 M1 항목)
  - [ ] **권고 #3 (DEFER M1)** — `ConcurrencyPool` ↔ `ConversionService` 연결 (§7 M1 항목)
  - [ ] **권고 #4 (DEFER M1)** — shutdown in-flight 대기 정책 (§7 M1 항목)
  - 메모 1\~5: 전부 확인(action 없음). lifespan composition root·url_policy 매핑·테스트 격리·400/404 분기 일관성 모두 적절 판정
- [x] **Task 17** `v0.0.1-m0` 태그 + M0 완료 문서화 — 본 PROCESS_STATE에 M0 DONE 표기 + §4 로드맵 갱신 + `docs(m0): mark M0 complete and tag v0.0.1-m0` commit + annotated tag. 플랜 원안의 `STATE.md` 대상은 정본이 PROCESS_STATE로 바뀌어 본 문서로 대체

### 6.8 Codex 리뷰 트랙 (Task 1\~13)

산출 문서: `docs/reviews/2026-05-21-m0-task1-13-codex.md`. Codex 자체 검증: `pytest -q` 148/1, `ruff check` 통과.

**🔴 차단 3건 — 모두 ACCEPT + 코드 반영 완료**

- [x] **#1** `5d53995 fix(m0): include detected_format in cache key` — `detect_format`을 cache lookup 이전으로 옮기고 `compute_cache_key(data, options, *, detected_format)`로 시그니처 확장. 회귀: `b"hello world\n"` `.txt` vs `.csv` distinct 출력
- [x] **#3** `3e997d0 fix(m0): validate_url rejects malformed port` — `validate_url`에서 `parsed.port` 접근으로 ValueError를 `MdflowError(URL_INVALID)`로 wrap. 회귀: bad / -1 / 99999 parametrize 3건. **부수 권고(fetch_url의 방어적 InvalidURL catch)는 CLAUDE.md "단순함 우선" 원칙으로 추가 안 함** — `validate_url`이 모든 진입점을 막음
- [x] **#2** (3 슬라이스로 분할)
  - [x] slice 1 `e096a7b feat(m0): detect_format accepts content_type_hint` — `_CT_TO_FORMAT` (+`text/plain`), `_content_type_format` 헬퍼, magic 부재 시 content-type fallback. 회귀: `text/plain; charset=utf-8` + ext 없음 → `format=txt`, `source="content-type"`
  - [x] slice 2 `d55ec03 feat(m0): ConversionService forwards content_type_hint` — `ConvertRequest.content_type_hint: str|None = None` + `service.convert` → `detect_format(..., content_type_hint=...)` 전달. 회귀: service-level end-to-end
  - [x] slice 3 `bc87aaf feat(m0): url_pipeline forwards fetched.content_type` — `convert_from_url`에서 `ConvertRequest(content_type_hint=fetched.content_type)` 한 줄. 회귀: `Content-Type: text/plain; charset=utf-8` + plain body → `detected_format="txt"`, TextConverter passthrough
  - [x] Codex slice 1+2 ACCEPT (`.agent_io/codex/output.md`, 2026-05-22: 차단/권고 0건, focused tests 30 passed, ruff clean)
  - [x] Codex slice 3 ACCEPT (`.agent_io/codex/output.md`, 2026-05-22: 차단/권고 0건, focused tests 31 passed, ruff clean)

**🟡 권고 5건 — 분류 확정**

- [x] **#4** `c3afde8 refactor(m0): remove ConvertRequest.fetch_metadata dead field` — `ConvertRequest.fetch_metadata` 필드 제거 + 위 주석 제거 + module docstring 갱신 (URL fetch metadata는 `UrlConvertResponse.fetch` sidecar로 처리됨을 명시). 회귀: `test_convert_request_rejects_fetch_metadata_keyword` (TypeError 검증)
- [x] **#5 read 슬라이스** `2a64b7d fix(m0): wrap cache.read I/O errors as CACHE_IO_ERROR` — `cache.read`에서 `(OSError, json.JSONDecodeError)`를 catch해 `MdflowError(CACHE_IO_ERROR)`로 wrap. 회귀: 깨진 meta.json + 정상 result.md 조합에 read() → CACHE_IO_ERROR
- [x] **#5 write 슬라이스** (코드 반영, **커밋 보류**) — `cache.write`의 atomic write 블록을 `try/except OSError`로 감싸 `MdflowError(CACHE_IO_ERROR)`로 wrap + 실패 시 `shutil.rmtree(tmp, ignore_errors=True)` 정리. 회귀: `monkeypatch`로 `Path.write_text`를 OSError raise → `cache.write`가 `MdflowError(CACHE_IO_ERROR)`
- [x] **#6** (코드 반영, **커밋 보류**) — `cache.write`의 `.tmp-{sha}` 고정을 `tempfile.mkdtemp(prefix=f".tmp-{sha}-", dir=self.root)`로 변경. 동시 sha write 시 unique tmp 사용. 회귀: `monkeypatch`로 `mdflow.core.cache.tempfile.mkdtemp` spy — 두 sequential write가 distinct tmp path 받음
- [x] **Follow-up 라운드 #2 (mkdtemp OSError wrap) — ACCEPT + 적용** (`docs/reviews/2026-05-22-m0-cache-write-mkdtemp-codex.md`, **커밋 보류**) — `mkdtemp()` 호출이 try 블록 밖이라 root 권한/디스크 오류 시 raw `OSError` 누출. `tmp: Path | None = None` init + `mkdtemp` 호출을 try 안으로 이동 + cleanup에 `tmp is not None` 가드. 회귀: `test_cache_write_mkdtemp_oserror_wrapped_as_cache_io_error` (`mdflow.core.cache.tempfile.mkdtemp` monkeypatch로 OSError raise → `MdflowError(CACHE_IO_ERROR)` + `__cause__` 보존)
- [ ] **Follow-up 라운드 #1 (publish race) — DEFER (M1)** — `os.replace(tmp, entry)` 직전 `if entry.exists(): rmtree(entry)`는 두 단계라 동시 same-sha writer가 destination에서 collide 가능 (한 writer가 `OSError` 받을 수 있음). 해결책 두 옵션 모두 M0 범위 확장: (a) sha별 lock manager 도입, (b) "first-writer-wins"로 API semantics 변경. M0 단일 프로세스 sequential 가정에서 outcome은 "한 writer 실패해도 다음 호출 cache hit" — 데이터 손상 없음. 잘못된 invariant 주석 ("last replace wins")만 정정. M1에서 다른 cache concurrency 항목과 묶어 처리
- [ ] **#7 DEFER (M1)** — URL fetch temp file streaming. Codex 본인이 M1 권고
- [x] **#8** 회귀 테스트 누락은 차단 TDD에 흡수 완료

**🟢 메모 3건 — 분류 확정**

- [ ] **#9 DEFER (v1.1)** — SSRF DNS rebinding 완전 차단 (도메인 allowlist v1.1 항목과 묶음)
- [x] **#10** — `url_policy_from_settings(settings) -> UrlPolicy` helper를 Task 14에서 `api/app.py`에 추가 + lifespan에서 `app.state.url_policy`로 구성 완료. URL convert 경로(M1)가 소비
- [ ] **#11 DEFER (M2)** — Registry first-wins → fallback chain 실행 모델

### Phase M0 — 이슈 / 노트 / 리스크 실현 기록

**리스크 실현 (M0 plan §리스크 표 매핑)**:

- [x] **R1 libmagic 시스템 의존성** — 실현됨. libmagic이 `text/plain`을 일부 비-텍스트 입력에 부여하는 over-classification 발견. **RESOLVED** `45e1f43 fix(m0): exclude text/plain from MIME map (libmagic over-classifies)`. M0 fixture 범위는 prefix probe로 자급. CI 환경 `libmagic` 설치 권고는 docs/dev에 명시 필요 (Task 17에서 처리)
- [x] **R4 chardet 짧은 텍스트 정확도** — 실현됨. 20자 미만 cp949 fixture를 chardet이 인식 못함. **RESOLVED** `88ce246 fix(m0): lengthen cp949 fixture so chardet identifies the encoding`. **M1에서 `language_hint` 옵션으로 보강 예정.**
- [ ] **R2 SSRF DNS rebinding** — M0는 best-effort `getaddrinfo` + IP literal 직접 검사로 1차 차단. **완전 차단은 v1.1 도메인 allowlist 항목 (Codex 메모 #9와 동일).**
- [x] **R3 `asyncio.Semaphore` 이벤트 루프 바인딩** — **RESOLVED** Task 14에서 `ConcurrencyPool(cpu_workers=...)`을 `_lifespan` async 컨텍스트 내부에서 생성하도록 와이어. `app.state.pool`에 저장, `finally`에서 `pool.shutdown()`. TestClient의 lifespan 진입이 동일 이벤트 루프를 공유하므로 semaphore가 올바른 루프에 바인딩됨 (`test_app_lifespan_initializes_state` 통과)
- [ ] **R5 `urlparse` 관대함** — Task 12 negative case 13개로 cover. 추가 강화 (IDNA·trailing dot 정규화)는 합의안에서 v1.1로 분류됨
- [ ] **R6 캐시 동시 쓰기 경합** — 권고 #6 적용으로 `mkdtemp` unique tmp dir 사용. 변환 결과가 deterministic이므로 "마지막 replace 승"은 outcome상 무해

**구현 패턴 / 정책 노트**:

- **합의안 §3.7 cache + fetch metadata 분리** — 같은 bytes를 두 다른 URL에서 받으면 cache는 공유, fetch metadata는 응답별 합성. `url_pipeline`의 명시 테스트에 cover됨. 향후 변경 시 이 invariant를 깨면 안 됨
- **작은 슬라이스 패턴** — 한 task에 여러 책임이 묶이면 분할 슬라이스 commit. 현재 24+ commit (Task 1\~13). Codex 리뷰 대상도 슬라이스 단위로 송부 가능 (#2가 3 슬라이스, #5가 2 슬라이스로 분할된 사례)
- **차단 권고에 부수된 방어 코드 거부 사례** — 차단 #3 처리 시 Codex가 "fetch_url에 InvalidURL catch도 추가"를 권했으나 CLAUDE.md "단순함 우선" 원칙으로 거부. `validate_url`이 모든 진입점을 막으므로 일어날 수 없는 시나리오에 에러 핸들링 금지

**남은 결정 / 진행 시점에 확인할 항목**:

- **Task 14 lifespan 작성 시점**: `ConcurrencyPool(cpu_workers=caps.cpu_workers)`을 반드시 lifespan async 컨텍스트 내부에서 인스턴스화. `asyncio.Semaphore`는 생성 시점의 event loop에 바인딩됨 (R3)
- **메모 #10 helper 시그니처**: `def url_policy_from_settings(settings: Settings) -> UrlPolicy` 형태로 Task 14에 포함. Settings 9개 env 중 URL 관련 6개 (`MDFLOW_ALLOW_PRIVATE_URLS`, `MDFLOW_URL_MAX_REDIRECTS`, `MDFLOW_URL_CONNECT_TIMEOUT_S`, `MDFLOW_URL_READ_TIMEOUT_S`, `MDFLOW_URL_USER_AGENT`, `MDFLOW_MAX_URL_INPUT_MB`) 매핑
- **Task 17 태그 시점**: 모든 차단 + 권고 #5write/#6 commit 완료 후. ruff clean + pytest pass + smoke test 통과 + **Task 14\~17 묶음 Codex 리뷰 ACCEPT** 확인 후 `v0.0.1-m0` 태그
- **Codex 리뷰 케이던스 (사용자 결정 2026-05-22)**: M0 잔여는 per-task 리뷰가 아니라 **Task 14\~17을 M0 완료 직전 1회 묶음 리뷰**. 근거: Task 1\~13 관행과 일관 + API 표면이 한 묶음으로 응집 + Task 14·15가 같은 파일을 건드려 개별 리뷰 중복. 이후 milestone도 별도 지시 없으면 milestone 완료 직전 묶음 리뷰를 기본값으로

---

## 7. Phase M1 — 사무 포맷 + SSE [IN PROGRESS]

> **분해 결정 (2026-05-22)**: M1을 **M1a(SSE 인프라) → M1b(컨버터)**로 분해. 근거: SSE 오케스트레이션 골격을 기존 TextConverter 위에서 먼저 검증 후 컨버터를 끼움 (작은 슬라이스 패턴). 각 sub-project는 spec→plan→구현 사이클.
>
> **M1a [구현 완료, Codex 묶음 리뷰 대기]** — `POST /convert` SSE 인프라.
> - 설계: `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`
> - 계획: `docs/superpowers/plans/2026-05-22-m1a-sse-infrastructure.md` (Task 0\~9)
> - 실행: Subagent-Driven Development. 10 commits `b36836b`\~`17dd70e`, 186 passed/1 skipped, ruff clean
> - 다음: Task 9 Step 3 = M1a Codex 묶음 리뷰
>
> **M1b [설계 완료, plan 대기]** — docx/pptx/xlsx/html 컨버터 + 골든 출력.
> - 설계: `docs/specs/2026-05-22-m1b-office-converters-design.md` (브레인스토밍 산출물)
> - 확정 결정: 4종 한 spec / 코드-생성 fixture / 전체-파일 골든 exact 매칭 / 컨버터에만 집중(cross-cutting defer) / docx=mammoth→HTML→markdownify / 이미지 드롭(alt는 markdownify 경로 best-effort)
> - 컨버터: `docx-mammoth`, `pptx-python-pptx`, `xlsx-openpyxl`, `html-trafilatura` + 공유 `_html_to_md` 헬퍼
> - 다음: 사용자 spec 검토 → `superpowers:writing-plans`로 구현 계획 작성 → subagent-driven 구현

- [x] **M1a** `/convert` SSE 핸들러 (`event: started | progress | cached | done | error`) + service lookup/run_conversion 분리 + cpu_executor 펌프 + url fetch 통합 — **구현 완료** (Task 0\~8). 새 파일 `src/mdflow/api/convert.py`
- [ ] DOCX 컨버터 (mammoth + python-docx 보강) — M1b
- [ ] DOCX 컨버터 (mammoth + python-docx 보강)
- [ ] PPTX 컨버터 (python-pptx, 노트 보존)
- [ ] XLSX 컨버터 (openpyxl, 시트별 표)
- [ ] HTML 컨버터 (trafilatura + markdownify + beautifulsoup4)
- [ ] `language_hint` 옵션 (Phase M0 R4 흡수)
- [ ] URL fetch temp file streaming (Codex 권고 #7 흡수)
- [ ] Cache publish atomicity 강화 (M0 follow-up #1 흡수) — sha별 lock 또는 first-writer-wins semantics 중 택일 + 회귀 테스트 (barrier 있는 동시 same-sha write)
- [ ] Cache `delete`/`purge`의 raw `OSError` → `CACHE_IO_ERROR` 정규화 + admin 매핑 (M0 API 리뷰 권고 #1 잔여분). write/read는 이미 wrap됨
- [x] `ConcurrencyPool` ↔ `ConversionService` 연결 (M0 API 리뷰 권고 #3) — **RESOLVED (M1a)**: `/convert` SSE handler가 `app.state.pool.cpu_executor`로 `service.lookup`/`run_conversion`/`fetch_url`을 offload. service 생성자 주입이 아니라 handler가 executor를 직접 사용하는 방식. GPU semaphore 경로는 M2(PDF)에서 합류
- [ ] shutdown 정책 (M0 API 리뷰 권고 #4) — CPU 변환이 executor에서 돌면 `shutdown(wait=False, cancel_futures=True)`가 in-flight를 안 기다림. Uvicorn shutdown lifecycle과 "끝까지 대기 vs 중단" 정책 정하고 테스트
- [ ] 골든 출력 파일 (`tests/golden/<converter>/<fixture>.md`) + diff 리뷰 강제

### Phase M1a — 알려진 제약 (최종 리뷰 식별, Codex 묶음 리뷰 대상)

opus holistic 최종 리뷰(`git diff v0.0.1-m0..HEAD`)가 식별. 모두 M1a 범위에서는 무해(TextConverter 한정)하나 다음 단계에서 판단 필요:

1. **비-MdflowError 미포착 → 스트림 절단 — RESOLVED** (`46ae469`+`dbc4269`). Codex 차단 1로 재분류: 설계 §6(line 96 "변환/fetch 중 MdflowError/예외 → error", line 111 "스트림 시작 후 모든 실패 → HTTP 200 + 스트림 내 error")이 **예외 전체** 처리를 요구하므로 defer가 아니라 미구현 버그였음. 수정: `run_conversion`이 converter raw 예외를 `MdflowError(CONVERSION_FAILED)`로 wrap + 라우트 3경계(fetch/lookup/task.result)에 broad `except Exception` → `Error(INTERNAL)` + `logger.exception`(traceback은 서버 로그만, 클라엔 generic 메시지). 회귀: fake converter `ValueError` → 마지막 이벤트 `error`/`CONVERSION_FAILED`
2. **클라이언트 중단 시 in-flight executor task 미취소** — 스트림 도중 클라이언트 disconnect해도 `cpu_executor` future는 끝까지 실행되고 cache write까지 수행 (orphan compute + thread 낭비). `request.is_disconnected()` 체크/`finally` 없음. 스펙 §8 shutdown drain DEFER와 일관. 후속 처리
3. **이벤트 펌프 race — 분석 완료, safe-by-construction** (코드 변경 불필요). progress 콜백은 worker 함수 **반환 전** 동기 실행되어 `call_soon_threadsafe(put_nowait)`가 future-완료 콜백(`task.done()` flip)보다 FIFO상 먼저 enqueue됨 → `task.done() and q.empty()` 가드는 race에서 이길 수 없음. 0.05s 폴링은 belt-and-suspenders(보조적). Task 8 순서 테스트로 실증. **버그 아님 — "분석됨, 안전"으로 기록**
4. **마이너 (Codex 참고)**: `_done_event(result, ...)`의 `result`가 `Any` 타입힌트(실제 `ConversionResult`); `q`/`task`가 파라미터 없는 `asyncio.Queue`/`asyncio.Future`. 둘 다 계획 명세대로이며 타입 강화는 선택

### Phase M1 — 이슈 / 노트 (사전)

- DOCX 표 변환·PPTX 노트 보존·HTML 시맨틱 보존이 LLM 소비 품질의 핵심. 직접 컨버터 정확도 비교 fixture 필요
- SSE 핸들러는 `ConversionService.convert(progress=...)` 시그니처를 그대로 활용. `asyncio.Queue` 기반 event publisher는 M0 service 인프라를 확장
- Codex 권고 #7 (URL fetch temp file streaming)은 M1 합류 명시 — 큰 URL 입력에서 메모리 압박 완화

---

## 8. Phase M2 — PDF [PENDING]

- [ ] Marker (GPU) 통합 — `marker-pdf` optional dependency (`[gpu]` extras)
- [ ] PyMuPDF (CPU) 폴백
- [ ] `Capabilities` 분기 (GPU detect 결과로 자동 라우팅)
- [ ] PaperFlow VRAM 정리 패턴 (`del model; gc.collect(); torch.cuda.empty_cache()`) 적용
- [ ] Registry first-wins → **fallback chain 실행 모델** (Codex 권고 #11 흡수)

### Phase M2 — 이슈 / 노트 (사전)

- **PaperFlow의 VRAM 누수 패턴 재활용 회피가 최우선 학습.** 단일 세마포어로 직렬화하므로 한 번에 한 모델만 살아있음을 강제
- Marker는 무거운 의존이므로 `pyproject.toml`에서 `[project.optional-dependencies] gpu = ["marker-pdf", "torch"]`로 분리
- Codex 권고 #11 (fallback chain) 흡수 — first-wins → ordered chain (Marker GPU → PyMuPDF CPU)

---

## 9. Phase M3 — LibreOffice 폴백 [PENDING]

- [ ] LibreOffice → PDF → Marker / PyMuPDF 폴백 체인 (doc·ppt·hwp)
- [ ] `pyhwp` optional dependency (`[hwp]` extras)
- [ ] Docker 이미지에 `libreoffice`, `tesseract-ocr-*`, `fonts-noto-cjk` 포함
- [ ] OS 의존 fixture는 integration marker로 분리

### Phase M3 — 이슈 / 노트 (사전)

- **LibreOffice CLI 실행**: OS 프로세스 분리·timeout·잔여 lockfile 정리가 까다로움. PaperFlow에 패턴 없음 — 신규 설계 필요
- **HWP**: 한국어 환경 특화. `pyhwp`는 별도 group으로 묶고 fallback 실패해도 다른 포맷에 영향이 없도록 격리

---

## 10. Phase M4 — MCP [PENDING]

- [ ] FastMCP stdio entrypoint (`mdflow-mcp`)
- [ ] FastMCP Streamable HTTP route (`/mcp`)
- [ ] 4개 MCP tool: `convert_file`, `convert_url`, `list_formats`, `get_cached`
- [ ] MCP 진행 알림 (FastMCP 메커니즘 사용)

### Phase M4 — 이슈 / 노트 (사전)

- 두 transport 모두 동일 코드(`ConversionService`)에 위임. FastMCP가 추상화를 제공
- MCP는 SSE와 달리 client가 progress 이벤트를 표현하는 방식이 transport별로 다름 — FastMCP API 위주로 검증

---

## 11. Phase M5 — 운영 도구 [PENDING]

- [ ] CLI (Typer 기반, 단일 파일 변환 + 배치)
- [ ] Dockerfile (LibreOffice + Marker GPU/CPU 분기)
- [ ] 메트릭 (`/capabilities` 카운터 — 요청 수, 캐시 적중률, 평균 지연, 변환 실패율)
- [ ] 통합 테스트 매트릭스 (포맷 × CPU/GPU × OS deps)

### Phase M5 — 이슈 / 노트 (사전)

- 본격 Prometheus 메트릭은 v2. v1은 in-process counter만
- Docker 이미지 크기 vs GPU/CPU 분기: GPU 이미지는 별도 태그 권장

---

## 12. 파일 시스템 / 코드 구조 (현재)

```text
~/workspace/mdflow/   ( = /media/restful3/data/workspace/mdflow ; symlinked )
├── CLAUDE.md                                            ← 운영 규칙
├── PROCESS_STATE.md                                     ← 이 문서 (정본 상태)
├── pyproject.toml                                       ← hatchling, fastapi/pydantic/httpx/...
├── .gitignore
├── .venv/                                               (gitignored)
├── archive/
│   └── STATE_20260522.md                                ← 이전 정본 (아카이브)
├── docs/
│   ├── specs/2026-05-21-mdflow-design.md                ← PRD (406줄, URL 합의 반영)
│   ├── reviews/                                         ← Codex 산출물 (6개)
│   │   ├── 2026-05-21-url-handling-claude-review.md
│   │   ├── 2026-05-21-url-handling-codex-round1.md
│   │   ├── 2026-05-21-url-handling-claude-meta-review.md
│   │   ├── 2026-05-21-url-handling-codex-round2.md
│   │   ├── 2026-05-21-url-handling-final-agreement.md   ★ 기준 문서
│   │   └── 2026-05-21-m0-task1-13-codex.md              ← Task 1~13 묶음 리뷰
│   └── superpowers/plans/2026-05-21-m0-skeleton.md      ← M0 plan (17 TDD task)
├── src/mdflow/
│   ├── __init__.py                                      (__version__)
│   ├── settings.py                                      (MDFLOW_* env vars 9개)
│   ├── api/__init__.py                                  (비어 있음 — Task 14 예정)
│   ├── core/
│   │   ├── errors.py                                    (ErrorCode 15개 + MdflowError)
│   │   ├── events.py                                    (Started/Queued/Progress/Cached/Done/Error)
│   │   ├── format_detect.py                             (ext + magic, magic 우선)
│   │   ├── cache.py                                     (sha256 atomic 디스크 캐시) [M*]
│   │   ├── registry.py                                  (register + select + list_formats)
│   │   ├── service.py                                   (ConversionService bytes-in)
│   │   ├── url_fetch.py                                 (합의안 §3.2 10단계)
│   │   └── url_pipeline.py                              (convert_from_url helper, 합의안 §3.7)
│   ├── converters/
│   │   ├── base.py                                      (Converter Protocol + Context/Result)
│   │   └── text.py                                      (TextConverter txt/md/csv)
│   └── runtime/
│       ├── capabilities.py                              (GPU detect + boot log)
│       └── concurrency.py                               (GPU 세마포어=1 + CPU pool)
└── tests/                                               (13 test files, 158 passed/1 skipped)
    ├── conftest.py                                      (fixtures_dir, tmp_cache_dir)
    ├── converters/{test_base.py, test_text.py}
    └── test_{smoke_import, errors, events, settings, format_detect, registry,
              cache, capabilities, concurrency, url_fetch, service, url_pipeline}.py
```

`[M*]` 표시: 권고 #5write + #6 코드 반영 (커밋 보류 상태)

---

## 13. 미결 사항 (다음 세션에서 처리)

- [x] ~~M1a 계획 실행~~ — **완료** (Subagent-Driven, Task 0\~8, 186 tests, 10 commits). opus 최종 리뷰 통과
- [ ] **M1a Codex 묶음 리뷰** (최우선, Task 9 Step 3) — `convert.py`/`service.py`(split)/`cache.py`(cached_at) + 테스트 deltas. 알려진 제약 3건(§7 M1a)을 명시 송부
- [x] ~~M0 Task 14\~17~~ — **완료** (`v0.0.1-m0` 태그). 차단 0건 Codex 리뷰 통과
- [ ] **M1b** (M1a Codex 리뷰 반영 후) — docx/pptx/xlsx/html 컨버터 + 골든 출력. brainstorming→plan 사이클
- [ ] **M0 API 리뷰 DEFER 항목** (M1 중 처리): cache delete/purge OSError 정규화(권고 #1 잔여), shutdown in-flight 정책(권고 #4). **pool↔service(권고 #3)는 M1a에서 해소됨**
- [ ] **PaperFlow 보안 이슈 시정**: "나중에 검토" 결정. 별도 세션. 핵심 발견은 path traversal · SSRF · 약한 기본값 (이전 세션 보고서 참조)
- [ ] **URL 처리 v1.1 항목** (PRD §13에 4개 항목):
  - SPA / Headless 대응
  - quality gate 고도화
  - 인증 fetch
  - 도메인 allowlist
  - → 별도 시점에 v1.1 PRD로 분리 검토
- [ ] **CLAUDE.md 정합성 패치 (선택)** — 현재 `CLAUDE.md`는 `STATE.md`를 정본으로 가리키는 부분이 3곳 있음 (§1 "정본 상태 파일", §4 "STATE.md에는 최소...", §5 "STATE.md가 가장 중요한 handoff 문서"). PROCESS_STATE.md로 갱신 필요

---

## 14. 다음 세션 시작 체크리스트

1. `cd ~/workspace/mdflow` (또는 `/media/restful3/data/workspace/mdflow` — 동일 디렉토리)
2. **이 파일(`PROCESS_STATE.md`)을 먼저 읽기**
3. M1a 설계+계획 읽기:
   - `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md` (설계)
   - `docs/superpowers/plans/2026-05-22-m1a-sse-infrastructure.md` (10 task TDD 계획 — 다음 액션 본문)
4. 진척 점검:
   - `git log --oneline | head -10` (가장 최근 `c1bd89b docs(m1): M1a ... plan`)
   - `git tag -l` (`v0.0.1-m0` 있어야 함)
   - `.venv/bin/python -m pytest` (175 passed / 1 skipped 기대)
   - `git status` (깨끗해야 함)
5. **다음 액션 — M1a 계획 실행**:
   - 먼저 실행 모드 선택: **Subagent-Driven (추천)** = `superpowers:subagent-driven-development`, 또는 **Inline** = `superpowers:executing-plans`
   - Task 0 (python-multipart 의존성) → Task 1 (Cache.cached_at) → … → Task 9 (PROCESS_STATE + Codex 리뷰)
   - 각 task TDD: failing test → fail 확인 → 최소 구현 → pass → commit
6. M1a 완료 후 Codex 묶음 리뷰(케이던스: milestone 완료 직전), 그 다음 M1b brainstorming→plan
7. 사용자가 작은 슬라이스를 원하는 패턴 유지 — 한 task를 여러 step으로 분할 가능

---

## 15. 작업 환경 / 자주 쓰는 명령

```bash
# 환경
cd ~/workspace/mdflow                            # = /media/restful3/data/workspace/mdflow

# 테스트
.venv/bin/python -m pytest -q                    # 전체 (158 passed, 1 skipped)
.venv/bin/python -m pytest tests/test_X.py -v    # 한 파일
.venv/bin/python -m pytest -m integration        # integration marker만

# 린트/포맷 (커밋 전 항상)
.venv/bin/ruff check --fix src tests
.venv/bin/ruff format src tests
.venv/bin/ruff check src tests                   # final check

# git
git status                                       # 작업 흐름 점검
git log --oneline | head -25                     # 진척

# Python 버전 / 의존성
.venv/bin/python --version                       # 3.12.3 (필요: >=3.11)
.venv/bin/pip install -e ".[dev]"                # 재설치 필요 시
```

---

## 16. 사용한 스킬 / 도구

- `sc:analyze` — PaperFlow 종합 검토 (Phase 0 초기)
- `superpowers:using-superpowers` — 세션 시작 시 자동 (skill discovery)
- `superpowers:brainstorming` — Phase 0 설계 정렬 (HARD-GATE: 승인 전 코드 작성 금지)
- `superpowers:writing-plans` — M0 implementation plan 작성 (브레인스토밍의 유일한 합법 후속)
- `codex-peer-reviewer` — URL 처리 4라운드 합의 + Task 1\~13 묶음 리뷰 + 권고 #5write/#6 슬라이스 리뷰
- **다음에 쓸 가능성 높은 스킬**:
  - `superpowers:test-driven-development` — M0 잔여 task / M1 컨버터 구현 시
  - `superpowers:verification-before-completion` — Task 17 태그 직전
  - `codex-peer-reviewer` — Task 14\~17 묶음 리뷰

---

## 17. 참조 문서 / 외부 컨텍스트

- **PRD 본문**: `docs/specs/2026-05-21-mdflow-design.md` (14섹션 / 406줄)
- **URL 합의안 (기준)**: `docs/reviews/2026-05-21-url-handling-final-agreement.md`
- **M0 plan**: `docs/superpowers/plans/2026-05-21-m0-skeleton.md` (17 TDD task)
- **Codex Task 1\~13 리뷰**: `docs/reviews/2026-05-21-m0-task1-13-codex.md`
- **운영 규칙**: `CLAUDE.md` (프로젝트 루트)
- **이전 정본 상태**: `archive/STATE_20260522.md` (19차 갱신본 보존)
- **PaperFlow (형제 프로젝트)**: `/media/restful3/data/workspace/paperflow/`
  - `CLAUDE.md` — 엔진 패턴 (Marker VRAM 정리, 번역 청크 분할) 재활용 시 참고
  - 별도 보안 분석 보고서 없음 — 이전 세션 대화 로그만 (path traversal · SSRF · 약한 기본값)
