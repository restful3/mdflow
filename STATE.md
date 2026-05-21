# mdflow — 세션 핸드오프 상태

**작성일**: 2026-05-21 (1차) / 2026-05-21 갱신 (4차: M0 Task 1\~10 완료, Task 11 대기)
**다음 세션 사용법**: 이 파일을 먼저 읽고, `docs/specs/2026-05-21-mdflow-design.md`(406줄), `docs/superpowers/plans/2026-05-21-m0-skeleton.md`, `docs/reviews/2026-05-21-url-handling-final-agreement.md` 순으로 확인. 코드는 `git log --oneline`으로 진척 점검.

---

## 1. 한눈에 보기

- **현재 단계**: M0 plan 실행 중 — **Task 1\~10 완료** (bootstrap → events → settings → format_detect → converters/base → text → registry → cache → capabilities)
- **다음 액션**: Task 11(`ConcurrencyPool`: GPU 세마포어=1 + CPU ThreadPool) 진행
- **테스트**: 92 passed in 0.19s (스위트 전체)
- **PRD**: 406줄, URL 처리 v1 정책 반영
- **Plan**: `docs/superpowers/plans/2026-05-21-m0-skeleton.md` (17 task, TDD)

## 2. 프로젝트 컨텍스트

- **mdflow**는 PaperFlow(`/media/restful3/data/workspace/paperflow`)의 **형제 프로젝트**
- 다양한 문서 포맷(PDF, DOCX, PPTX, HTML, HWP, XLSX, 오래된 DOC/PPT 등)을 받아 LLM 소비용 Markdown으로 변환
- HTTP API + MCP 서버를 동시에 제공
- LLM/에이전트 입력용 (의미 구조 보존 우선, 시각 충실도는 비목표)
- PaperFlow가 PDF 논문 끝단(viewer 포함) 워크플로우라면, mdflow는 **범용 변환 게이트웨이**

## 3. 확정 설계 결정 (전체)

| 결정 영역 | 선택 | 비고 |
|---|---|---|
| 주 소비자 | LLM/에이전트 입력용 | 의미 보존 > 시각 재현 |
| 엔진 전략 | **하이브리드** | 직접 변환 우선 (mammoth, python-pptx 등), 어려운 포맷은 LibreOffice→PDF→Marker fallback |
| API 응답 모델 | **SSE 스트리밍** | 단일 호출로 진행률+결과, MCP·CLI·웹 모두 단순 |
| MCP transport | **stdio + Streamable HTTP 둘 다** | FastMCP, 동일 코드 두 transport |
| GPU 정책 | **자동 감지** | `torch.cuda.is_available()`, `MDFLOW_FORCE_CPU=1`로 override |
| 캐시 | **sha256(콘텐츠+옵션) 디스크 캐시** | `~/.cache/mdflow/<sha256>/result.md` |
| 실행 모델 | **단일 프로세스 + GPU 세마포어(=1) + CPU ThreadPool** | PaperFlow의 VRAM 누수 패턴 재활용 회피 |
| 인증 | **v1 비목표** | 후속 작업, 사용자 명시 "나중에 검토" |
| 결과 후처리 | **비목표** | 번역·요약은 호출자(혹은 PaperFlow) 책임 |

## 4. 파일 시스템 상태

```text
~/workspace/mdflow/
├── STATE.md                                              ← 이 문서
└── docs/
    ├── specs/
    │   └── 2026-05-21-mdflow-design.md                   ← PRD 본문 (406줄, URL 합의 반영)
    └── reviews/                                           ← URL 처리 코덱스 합의 산출물 (5개)
        ├── 2026-05-21-url-handling-claude-review.md      (7.9K)
        ├── 2026-05-21-url-handling-codex-round1.md       (22.9K)
        ├── 2026-05-21-url-handling-claude-meta-review.md (9.6K)
        ├── 2026-05-21-url-handling-codex-round2.md       (18.1K)
        └── 2026-05-21-url-handling-final-agreement.md    (18.1K) ★최종 합의안
```

- 빈 디렉터리 외 코드 없음
- `git init` 안 됨 (사용자 명시 지시 시 처리)

## 5. PRD 문서 구조 (14섹션)

`docs/specs/2026-05-21-mdflow-design.md` 안에:

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

## 6. 진행한 작업 (이번 세션)

1. PaperFlow 전체 코드 리뷰/감사 보고서 작성 (architecture·security·quality·performance) — 분석 완료, 사용자가 "보안 이슈는 나중에 검토" 결정
2. 새 프로젝트 이름 후보 4개 제시 (mdforge / markdrop / docflow / anymd) → 사용자가 **mdflow** 선택
3. `~/workspace/mdflow` 디렉터리 생성
4. `superpowers:brainstorming` 스킬 호출 → 6개 핵심 설계 결정 인터뷰 → 1개 재조정 (engine strategy 하이브리드로)
5. 7개 섹션 설계 초안 제시 → 사용자 승인
6. `docs/specs/2026-05-21-mdflow-design.md` 작성 + self-review (PDF/HWP 폴백 체인 정합성 한 곳 수정)
7. URL 입력 처리에 대해 PaperFlow의 9단계 `import_url_as_paper` 파이프라인과 비교 검토 작성
8. `codex-peer-reviewer` 스킬로 4라운드 코덱스 합의 루프 진행 (Claude 검토 → Codex R1 사실 지적 6건 / 권고 11개 → Claude 메타리뷰 + Q1-Q3 → Codex R2 답변 + PRD 패치 11개 → Codex Final Agreement)
9. **잔존 이견 0건 합의 도달.** 5개 산출물 `docs/reviews/`에 보존
10. PRD에 합의된 패치 11개 적용 (§1.2, §5, §5.1, §6, §7, §8.1, §8.3, §9, §10, §11, §12, §13)
11. M0 implementation plan 작성 (`docs/superpowers/plans/2026-05-21-m0-skeleton.md`, 17 TDD task + TL;DR phases/scope/risks)
12. git init + 첫 커밋 (PRD + reviews + plan)
13. **M0 Task 1\~10 TDD로 실행**:
    - Task 1 bootstrap, Task 2 errors(15코드), Task 3 events(6 이벤트), Task 4 settings(MDFLOW_* 9개)
    - Task 5 format_detect(ext+magic, magic 우선), Task 6 converters/base, Task 7 TextConverter(txt/md/csv)
    - Task 8 Registry(register+select+list_formats), Task 9 Cache(sha256 atomic), Task 10 Capabilities(GPU detect+boot log)
    - 각 task TDD 사이클(fail→impl→pass→ruff→commit). 일부는 작은 슬라이스로 분할하여 단계별 commit
    - 두 곳에서 리스크 R4(chardet 짧은 텍스트), 그리고 libmagic over-classification 실현 → fix 커밋으로 처리

## 7. 미결 사항 (다음 세션에서 처리)

- [ ] **M0 Task 11\~17 진행**: `ConcurrencyPool`(11) → `url_fetch`(12, 합의안 §3.2의 10단계 직접 반영) → `ConversionService`(13) → FastAPI `/healthz`(14) → admin endpoints(15) → smoke test(16) → 태그(17)
- [ ] **PaperFlow 보안 이슈 시정**: 사용자가 "나중에 검토" 결정. 별도 세션에서 다룰 수 있음. 핵심 발견은 path traversal·SSRF·약한 기본값 (이전 세션 보고서 참조)
- [ ] **URL 처리 v1.1 항목**: PRD §13에 4개 항목 등록됨 (SPA/Headless 대응, quality gate 고도화, 인증 fetch, 도메인 allowlist). 별도 시점에 v1.1 PRD로 분리 검토

## 8. 트레이드오프 메모 — 검토했지만 채택하지 않은 옵션

다음 세션에서 "왜 이렇게 정했지?" 질문 시 참고:

- **엔진**: MarkItDown 단일 wrapper 옵션 거부 — per-format 직접 변환이 LLM용으로 더 정확
- **엔진**: 순수 PDF 단일경로 옵션 (모든 포맷→LibreOffice→PDF→Marker) 거부 — DOCX 표·PPTX 노트·HTML 시맨틱 손실, 속도 저하, 무거운 의존
- **API**: 완전 동기 거부 — 대용량 PDF 시 게이트웨이 타임아웃
- **API**: Job 큐 + 폴링 거부 — MCP에서 에이전트가 폴링 구현 부담, YAGNI 위반
- **MCP**: stdio만/HTTP만 거부 — FastMCP로 둘 다 큰 비용 없이 가능
- **실행 모델**: API+워커 프로세스 분리 거부 — Redis 등 인프라 복잡도. 단순함 우선, GPU 누수 등 문제 발생 시 B로 점진 이전 (인터페이스만 유지)
- **GPU**: GPU 필수 거부 — 노트북·CPU 환경 사용 차단
- **캐시**: 캐시 없음 거부 — Marker PDF는 비싸서 재사용 가치 큼

## 9. 사용한 스킬 / 도구

- `sc:analyze` — PaperFlow 종합 검토 (이번 세션 초반)
- `superpowers:using-superpowers` — 세션 시작 시 자동
- `superpowers:brainstorming` — 설계 정렬 (HARD-GATE: 승인 전 코드 작성 금지)
- **다음 단계 스킬**: `superpowers:writing-plans` (브레인스토밍의 유일한 합법 후속)

## 10. 관련 참조

- **PaperFlow CLAUDE.md**: `/media/restful3/data/workspace/paperflow/CLAUDE.md` — 엔진 패턴(Marker VRAM 정리, 번역 청크 분할) 재활용 시 참고
- **PaperFlow 분석 보고서**: 이전 세션 대화 로그 (Path traversal·SSRF·Settings 기본값 등). 별도 파일 없음
- **PRD 본문**: `~/workspace/mdflow/docs/specs/2026-05-21-mdflow-design.md`

## 11. 다음 세션 시작 체크리스트

1. `cd ~/workspace/mdflow`
2. 이 파일(`STATE.md`) 읽기
3. `docs/specs/2026-05-21-mdflow-design.md` 읽기
4. 사용자에게: "PRD 검토 결과 알려주세요. 수정 사항 있나요?"
5. 응답에 따라:
   - 승인 → `superpowers:writing-plans` 스킬 호출, M0+M1 범위로 시작
   - 수정 → 해당 섹션 재설계, 합의 후 PRD 업데이트
   - git init 요청 → 처리 후 진행
