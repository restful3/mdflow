# mdflow — 세션 핸드오프 상태

**작성일**: 2026-05-21 (1차) / 2026-05-22 갱신 (12차: blocker #2 slice 3 완료, blocker 3건 전부 코드 반영 — slice 3 Codex 리뷰 대기)
**다음 세션 사용법**: 이 파일을 먼저 읽고, `docs/specs/2026-05-21-mdflow-design.md`(406줄), `docs/superpowers/plans/2026-05-21-m0-skeleton.md`, `docs/reviews/2026-05-21-url-handling-final-agreement.md` 순으로 확인. 코드는 `git log --oneline`으로 진척 점검.

---

## 1. 한눈에 보기

- **현재 단계**: M0 plan 실행 중 — **Task 1\~13 완료**, **Codex 리뷰 차단 3건 코드 반영 전부 완료, slice 3 Codex 리뷰 대기**
- **Codex 리뷰 상태**: **반영 완료, slice 3 추가 리뷰 대기** — `docs/reviews/2026-05-21-m0-task1-13-codex.md`. Codex 자체 검증: `pytest -q` 148/1, `ruff check` 통과
- **분류**:
  - 🔴 차단 3건: 모두 ACCEPT 후 코드 반영 완료
    - **#1 DONE** — `5d53995 fix(m0): include detected_format in cache key`. detect_format을 cache lookup 이전으로 옮기고, `compute_cache_key(data, options, *, detected_format)`로 시그니처 확장. 회귀: `b"hello world\n"` `.txt` vs `.csv` distinct 출력
    - **#3 DONE** — `3e997d0 fix(m0): validate_url rejects malformed port`. `validate_url`에서 `parsed.port` 접근으로 ValueError를 `MdflowError(URL_INVALID)`로 wrap. 회귀: bad/-1/99999 parametrize 3건. CLAUDE.md "단순함이 먼저다" 원칙으로 fetch_url의 방어적 InvalidURL catch는 추가 안 함 (validate_url이 모든 진입점을 막음)
    - **#2 DONE (slice 1~3, slice 3는 Codex 리뷰 대기)**:
      - slice 1 DONE — `e096a7b feat(m0): detect_format accepts content_type_hint`. `_CT_TO_FORMAT`(+`text/plain`), `_content_type_format` 헬퍼, magic 부재 시 ct fallback. 회귀: `text/plain; charset=utf-8` + ext 없음 → `format=txt`, `source="content-type"`
      - slice 2 DONE — `d55ec03 feat(m0): ConversionService forwards content_type_hint`. `ConvertRequest.content_type_hint: str|None=None` 필드 + `service.convert` → `detect_format(..., content_type_hint=...)` 전달. 회귀: service-level end-to-end (bytes+ct만으로 txt 변환)
      - Codex review (slice 1+2) ACCEPT — `.agent_io/codex/output.md` (2026-05-22): 차단/권고 0건, focused tests 30 passed, ruff clean
      - slice 3 DONE — `bc87aaf feat(m0): url_pipeline forwards fetched.content_type`. `convert_from_url`에서 `ConvertRequest(content_type_hint=fetched.content_type)` 한 줄. 회귀: GET `https://example.com/` + `Content-Type: text/plain; charset=utf-8` + plain body → `detected_format="txt"`, TextConverter passthrough (이전엔 FORMAT_DETECT_FAILED)
  - 🟡 권고 5건: #8(회귀 테스트)는 차단 TDD에 흡수 완료, #10(Settings→UrlPolicy helper)는 Task 14에서 필요. #4/5/6/7은 차단 처리 후 별도 결정
  - 🟢 메모 3건: 모두 NOTED (v1.1/M1/M2 추후 작업)
- **다음 액션**: **blocker #2 slice 3 Codex 리뷰 핸드오프** → 리뷰 후 권고 재판단 → Task 14
- **테스트**: 155 passed, 1 skipped (blocker #2 slice 3 회귀 +1)
- **Task 13 산출물 (2개 슬라이스)**:
  - `src/mdflow/core/service.py` — `ConversionService.convert(req, progress)`: bytes 입력 cache key 계산 → cache hit/miss → format_detect → registry.select → converter.convert → metadata 보강 → cache write. `ConvertRequest`/`ConvertResponse` dataclass + `ProgressCallback` 타입 alias
  - `src/mdflow/core/url_pipeline.py` — `convert_from_url(url, policy, service, options, progress, transport)` helper. `fetch_url` → bytes → `service.convert`. 반환 `UrlConvertResponse(response, fetch dict)`. 합의안 §3.7 핵심 케이스(같은 bytes 두 다른 URL → cache 공유 + 응답별 fetch metadata) 명시 검증
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
~/workspace/mdflow/   ( = /media/restful3/data/workspace/mdflow ; symlinked )
├── .gitignore
├── .venv/                                               ← Python venv (gitignored)
├── STATE.md                                             ← 이 문서
├── pyproject.toml                                       ← hatchling, fastapi/pydantic/httpx/...
├── docs/
│   ├── specs/2026-05-21-mdflow-design.md                ← PRD (406줄, URL 합의 반영)
│   ├── reviews/                                         ← Codex 합의 산출물 (5개)
│   │   ├── 2026-05-21-url-handling-claude-review.md
│   │   ├── 2026-05-21-url-handling-codex-round1.md
│   │   ├── 2026-05-21-url-handling-claude-meta-review.md
│   │   ├── 2026-05-21-url-handling-codex-round2.md
│   │   └── 2026-05-21-url-handling-final-agreement.md   ★기준 문서
│   └── superpowers/plans/2026-05-21-m0-skeleton.md      ← M0 plan (17 TDD task)
├── src/mdflow/
│   ├── __init__.py                                      (__version__)
│   ├── settings.py                                      (MDFLOW_* env vars)
│   ├── api/__init__.py                                  (비어 있음 — Task 14 예정)
│   ├── core/
│   │   ├── errors.py                                    (ErrorCode 15 + MdflowError)
│   │   ├── events.py                                    (Started/Queued/Progress/Cached/Done/Error)
│   │   ├── format_detect.py                             (ext + magic, magic 우선)
│   │   ├── cache.py                                     (sha256 atomic 디스크 캐시)
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
└── tests/                                               (13 test files, 148 passed/1 skipped)
    ├── conftest.py                                      (fixtures_dir, tmp_cache_dir)
    ├── converters/{test_base.py, test_text.py}
    └── test_{smoke_import, errors, events, settings, format_detect, registry,
              cache, capabilities, concurrency, url_fetch, service, url_pipeline}.py
```

- git: 24 commits, master 브랜치, 태그 없음 (가장 최근 `8519a49 docs(m0): STATE.md — Task 13 complete`)
- venv 활성화: `source .venv/bin/activate` 또는 `.venv/bin/python -m pytest`로 직접 실행

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
13. **M0 Task 1\~13 TDD로 실행**:
    - Task 1 bootstrap, Task 2 errors(15코드), Task 3 events(6 이벤트), Task 4 settings(MDFLOW_* 9개)
    - Task 5 format_detect(ext+magic, magic 우선), Task 6 converters/base, Task 7 TextConverter(txt/md/csv)
    - Task 8 Registry(register+select+list_formats), Task 9 Cache(sha256 atomic), Task 10 Capabilities(GPU detect+boot log)
    - Task 11 ConcurrencyPool(GPU 세마포어=1 + CPU ThreadPool, gpu_lock async ctx + idempotent shutdown)
    - Task 12 url_fetch(합의안 §3.2의 10단계 — validate/fragment/SSRF/UA/redirect per-hop/timeout/size cap/2xx/filename hint/FetchResult metadata)
    - Task 13 ConversionService(bytes 입력 cache/detect/dispatch) + url_pipeline.convert_from_url(URL → fetch → service 통합 helper, 합의안 §3.7 적용)
    - 각 task TDD 사이클(fail→impl→pass→ruff→commit). 일부는 작은 슬라이스로 분할하여 단계별 commit
    - 두 곳에서 리스크 R4(chardet 짧은 텍스트), 그리고 libmagic over-classification 실현 → fix 커밋으로 처리

## 7. 미결 사항 (다음 세션에서 처리)

- [ ] **Codex 리뷰 결과 반영** — M0 Task 1\~13 묶음 리뷰 (`docs/reviews/2026-05-21-m0-task1-13-codex.md`). 도착 후 분류(차단/권고/메모) → 차단·권고는 작은 슬라이스로 반영 → 메모는 별도 메모. 반영 완료 후 STATE.md 다시 갱신
- [ ] **M0 Task 14\~17 진행**: FastAPI `/healthz`(14, lifespan에서 Settings+Capabilities+Registry+Cache+ConcurrencyPool+ConversionService 와이어) → admin endpoints(15) → smoke test(16) → 태그(17)
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

1. `cd ~/workspace/mdflow` (또는 `/media/restful3/data/workspace/mdflow` — 동일 디렉토리)
2. **이 파일(`STATE.md`)을 먼저 읽기**
3. 합의안 확인: `docs/reviews/2026-05-21-url-handling-final-agreement.md` (모든 URL 처리 결정의 기준)
4. plan 확인: `docs/superpowers/plans/2026-05-21-m0-skeleton.md` (남은 Task 14\~17 본문)
5. 진척 점검: `git log --oneline | head -25` + `.venv/bin/python -m pytest -q` (148 passed 1 skipped 기대)
6. **다음 액션 — Task 14** (FastAPI 앱 팩토리 + lifespan + `/healthz`):
   - 새 파일: `src/mdflow/api/app.py`, `tests/api/__init__.py`, `tests/api/test_app.py`
   - lifespan에서 와이어: `Settings()` → `detect()` Capabilities → `Registry()` + `TextConverter` register → `Cache(settings.cache_dir)` → `ConcurrencyPool(caps.cpu_workers)` → `ConversionService(registry, cache)`. 모두 `app.state.*`에 저장
   - `/healthz` 라우트: `{"ok": True, "uptime_s": ...}`
   - TDD: `tests/api/test_app.py`에 `test_healthz_returns_ok` + `test_app_lifespan_initializes_state`를 먼저 fail로 작성 → fastapi.testclient로 검증
7. 사용자가 작은 슬라이스를 원하는 패턴 유지 — 한 task를 여러 step으로 분할 가능

## 12. 작업 환경 / 자주 쓰는 명령

```bash
# 환경
cd ~/workspace/mdflow                            # = /media/restful3/data/workspace/mdflow

# 테스트
.venv/bin/python -m pytest -q                    # 전체 (148 passed, 1 skipped)
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

## 13. 절대 잊으면 안 되는 결정 (참조)

- **URL 처리는 합의안 §3 기준**: 사용자 헤더/쿠키/Authorization/follow_redirects 차단, SSRF v1 필수, cache key는 bytes 기준 + fetch metadata는 request별 합성. v1.1 항목 4개는 PRD §13 참조.
- **TDD 순서 엄수**: failing test → fail 확인 → impl → pass 확인 → ruff → commit. 각 commit 메시지는 "feat(m0): ..." 또는 "fix(m0): ..." 패턴.
- **PaperFlow 학술 transformer는 v1 비목표** (PRD §1.2 명시). mdflow는 범용 변환 게이트웨이.
- **모든 단계는 작게**: 사용자가 패턴으로 굳혀 둠. 한 task에 여러 책임이 묶여 있으면 분할 슬라이스로 commit.
