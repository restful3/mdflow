# CLAUDE.md — mdflow 프로젝트 지침

> 이 파일은 Claude Code 가 mdflow 루트에서 작업할 때 따르는 운영 규칙이다.

---

## 1. 현재 상태

- 정본 상태 파일: `PROCESS_STATE.md` (이전: `STATE.md` → `archive/STATE_20260522.md`)
- 현재 단계 / 다음 액션 / 테스트 상태는 `PROCESS_STATE.md` §2 "한눈에 보기" 참조 (CLAUDE.md에는 휘발성 상태를 중복 기록하지 않는다)

작업 시작 전 최소 확인 순서:
1. `PROCESS_STATE.md`
2. `docs/specs/2026-05-21-mdflow-design.md`
3. 최신 Codex 합의 문서 (`docs/reviews/2026-05-21-url-handling-final-agreement.md` 등)

## 2. 기본 작업 흐름

1. 설계/구현/문서 작업을 현재 phase 또는 체크포인트 단위로 진행한다.
2. **의미 있는 체크포인트**(implementation plan, 설계 패치, 구현 묶음, 테스트 통과 단위)가 생기면 Codex 리뷰 대상으로 넘긴다.
3. Codex 리뷰 결과를 반영한 뒤에만 해당 체크포인트를 사실상 채택된 것으로 본다.
4. 각 phase 또는 리뷰 라운드가 끝날 때 `PROCESS_STATE.md`를 즉시 갱신한다.

## 3. Codex 리뷰 규칙

- 구현 코드뿐 아니라 아래도 기본적으로 Codex 리뷰 대상이다.
  - implementation plan
  - PRD의 의미 있는 패치
  - 아키텍처 결정 문서
  - 테스트 전략 변경
- 예외는 사용자가 **명시적으로 리뷰 생략**을 지시한 경우뿐이다.
- 리뷰 산출물은 `docs/reviews/YYYY-MM-DD-*.md`에 남긴다.

## 4. 상태 파일 업데이트 규칙

자율 갱신 트리거 + 최소 유지 항목의 **단일 기준**은 `PROCESS_STATE.md` §0 "문서 운영 규칙"이다. 별도 지시 없이도 다음 시점에 갱신한다:

1. phase 또는 sub-phase 시작/종료
2. implementation plan 작성/수정 완료
3. Codex 리뷰 요청 송부 직후 / 결과 수신 직후
4. **주요 기능 구현·버그 수정 commit 직후**
5. handoff가 필요한 세션 종료 직전

최소 유지 항목(현재 phase, 마지막 끝난 작업, Codex 리뷰 상태, 다음 액션 1\~3개, 사용자 결정 필요 항목)은 `PROCESS_STATE.md` §0.1 / §2에 그대로 명시되어 있다.

## 5. mdflow 특이사항

- 현재는 `PROCESS_STATE.md`가 가장 중요한 handoff 문서다.
- 구현 시작 전에는 PRD와 최신 리뷰 합의 문서를 먼저 우선시한다.
- 새 코드 작성 단계로 들어가면 테스트/검증 결과도 `PROCESS_STATE.md`에 짧게 남긴다.
