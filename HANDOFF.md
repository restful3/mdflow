# 세션 핸드오프 — M6a 완료, Codex round-1 차단 fix 대기
_최종 갱신: 2026-05-23_

## 🎯 목표

Phase M6 (이미지 지원 v2) 진행. M6a (인프라) 완료 + Codex 단독 묶음 리뷰 round-1 수신. 차단 1건(formatter) + 즉시 권고 2건(image/jpg test, spec template regex) 처리 후 재리뷰 → `===CODEX_FINAL_APPROVAL===` 받으면 채택 + 태그. 그 다음 M6b (PDF 컨버터 이미지 추출) plan 작성.

## ✅ 완료

- **M6a 9 task subagent-driven 실행 완료** (각 task에 implementer + spec compliance reviewer + code quality reviewer, 모두 ✅ approved). 9 commits `1489ab0..cbece1b`.
- 352 passed / 2 skipped (304 pre-M6a + 49 신규 − 1 제거된 assets test), `ruff check` clean
- PROCESS_STATE.md §4 로드맵에 Phase M6 IN PROGRESS 추가, 헤더에 M6a 완료 기록 (`fee7eae`)
- 모든 commits push 완료 (`origin/master`까지 sync)
- Codex round-1 리뷰 수신 — `docs/reviews/2026-05-23-m6a-image-infrastructure-codex.md` (14.6K)

## 🔄 진행 중

- **Codex round-1 결과 처리 단계**. Codex 판정: "차단 1건(formatter) 처리 후 채택. 권고는 M6b/M6e 전 보강하면 충분".
- 사용자에게 다음 조치 계획 제시했고("차단 1 + 권고 2 즉시 처리 후 재리뷰") 대답 대기 중이었음. 사용자가 "세션 클리어 준비" 요청.

## ⏭️ 다음 단계

새 세션에서 이어받을 순서:

1. **Codex 응답 파일 commit**: `docs/reviews/2026-05-23-m6a-image-infrastructure-codex.md` (현재 untracked).
   ```bash
   git add docs/reviews/2026-05-23-m6a-image-infrastructure-codex.md
   git commit -m "docs(reviews): M6a Codex round-1 review (block 1 + rec 6 + memo 6)"
   ```
2. **차단 1 처리** — `.venv/bin/ruff format src tests` 실행. 4 파일 재포맷됨: `src/mdflow/core/cache.py`, `src/mdflow/views/zip.py`, `tests/converters/test_image_util.py`, `tests/test_cache_canonical.py`. 검증: `.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/pytest -q` 모두 clean + 352 passed. commit:
   ```bash
   git commit -am "fix(m6a): apply ruff format (Codex round-1 blocking)"
   ```
3. **권고 5 처리** — `tests/converters/test_image_util.py`에 한 줄 test 추가:
   ```python
   def test_content_type_to_ext_jpg_alias():
       assert content_type_to_ext("image/jpg") == "jpg"
   ```
   commit: `test(m6a): add image/jpg alias lookup test (Codex round-1 rec 5)`
4. **권고 4 부분 처리** — `docs/specs/2026-05-23-m6-image-support-design.md` §5.3 의사코드의 regex `\[(.*?)\]` 두 곳 (views.none `_STANDALONE`/`_INLINE`, views.embed `_REF`) 을 `\[([^\]]*)\]` 로 패치. spec에 한 줄 추가: "alt 안에는 `]` 가 허용되지 않는다 (CommonMark 합치) — alt에 `]`가 필요한 컨버터 케이스는 v1.1 이후 escaping 정책 도입 시 확정". commit: `docs(specs): fix M6 alt regex template ((.*?) → [^\]]*) per Codex round-1 rec 4`
5. **Codex round-2 재리뷰 송부** — `docs/reviews/2026-05-23-m6a-image-infrastructure-codex-2.md`. 메시지에 포함할 것: 차단 1 fix commit hash, rec 5 commit hash, rec 4 spec patch commit hash, "더 이상 수정할 게 없다면 응답 첫 줄에 정확히 `===CODEX_FINAL_APPROVAL===` 한 줄만". 이전 M1a/M4/M2b 재리뷰 패턴과 동일.
6. **재리뷰 결과 처리** — `===CODEX_FINAL_APPROVAL===` 수신 시 M6a 채택:
   - 태그: `v0.8.0-m6a` (M3b의 `v0.4.0-m3b`, M4의 `v0.5.0-m4` 패턴 따라). 사용자 결정 가능.
   - PROCESS_STATE.md 갱신 (M6a 채택, round-2 final approval, 태그 명시)
   - push
7. **M6b plan 작성** — `superpowers:writing-plans` 스킬 호출. 범위: `pdf-pymupdf4llm` + `pdf-marker` 두 컨버터에 이미지 추출 활성화. Plan에 Codex round-1 권고 1·2 **반드시 통합** (M6b 시작 직전 처리 → 컨버터가 실제 image-bearing cache를 만들기 전 보강):
   - **권고 1**: `Cache.read`에서 malformed `meta["images"]` schema (list 아닌 경우, dict 아닌 element, `name`/`content_type` str 아닌 경우) → `MdflowError(CACHE_IO_ERROR)`로 wrap
   - **권고 2**: `Cache.write`에서 `img.name == Path(img.name).name` (path traversal 차단) 검증. 또는 `ImageAsset.name` 생성을 헬퍼로 사실상 고정하고 컨버터 구현 규칙에 명시
8. **M6b 실행** — subagent-driven 진행 (M6a 패턴 일관)

## 🧠 대화에만 있던 핵심 컨텍스트

### Codex round-1 분류 (재리뷰 송부 시 참고)

- **차단 1**: `ruff format --check` 4 파일 실패 — 우리가 `ruff check`만 확인하고 `format --check`는 안 했음. milestone 채택 조건 "ruff clean"에 format check 포함된다는 invariant 확인됨.
- **권고 1 (M6b 직전)**: `Cache.read`의 schema validation gap — `img_meta["name"]` 등 raw KeyError 가능
- **권고 2 (M6b 직전)**: `ImageAsset.name` path safety — `../x.png` 같은 name이 컨버터에서 들어오면 figs/ 탈출
- **권고 3 (M6e)**: `options.images` cache-key 제외 — `compute_cache_key` 내부 또는 `canonical_cache_options(options)` 같은 단일 helper 중앙화. **위치**: `src/mdflow/core/cache.py:38` `compute_cache_key`, `src/mdflow/core/service.py:76`이 호출. M6e가 handler에서 `images`를 options에 넣기 시작하기 전에 처리.
- **권고 4 (즉시 — spec doc + plan template)**: spec의 view synthesis 의사코드 regex가 `(.*?)`로 적혀있음 → `[^\]]*`로 패치 필요. 그렇지 않으면 M6b\~M6d implementer가 같은 backtracking 버그를 다시 만남.
- **권고 5 (즉시)**: `test_content_type_to_ext_jpg_alias` 한 줄 추가
- **권고 6 (M6f PRD 패치)**: code fence 보호의 제한 ("4+ space indented fence도 fence로 본다 / `~~~` fence 미보호") spec에 명시

### 발견 (디버깅·실험에서 알아낸 것)

- **regex `(.*?)` backtracking bug**: Task 6 implementer가 multi-image line(`![a](figs/1.png) and ![b](figs/2.png)`)에서 `_STANDALONE.fullmatch()`가 잘못 매칭함을 발견. `[^\]]*` (alt cannot contain `]` per CommonMark)로 fix. Task 7도 같은 fix 자동 적용. Spec template은 미패치 → 다음 단계 4번에서 처리.
- **Cache.read post-rename stats semantics**: Codex memo 3에서 PASS 확인. miss는 absent entry만, hit은 성공만, corruption은 어느 카운터도 안 건드림.
- **legacy M0 entry 호환**: Codex memo 4에서 PASS — `meta.get("images", [])` 덕분에 `assets`만 있는 old meta.json도 `images=[]`로 round-trip.
- **5 transport 라이브 e2e (이전 세션)**: HTTP + MCP stdio + MCP HTTP + GPU(Marker) + CLI 모두 그린. PROCESS_STATE 헤더에 기록됨.

### 결정 (왜)

- **subagent-driven 패턴 success**: 각 task에 implementer + spec reviewer + code quality reviewer = 3 subagent. 메인 컨텍스트 보호 + TDD discipline 자동. M6b\~M6f도 같은 패턴 유지.
- **`ConversionResult.assets` 즉시 제거 vs shim**: 우리 선택 = dataclass에서 제거 + JSON 응답(`Done.assets`, admin route) 에서 `"assets":[]` shim 유지. v2.0 major니까 정당한 breaking. Codex memo 1에서 동의.
- **Cache.write/read rename (canonical → 기본)**: 두 method를 하나로 통일. `build_bundle`은 별개. Codex memo 6에서 commit 분해 합리 판정.
- **5 transport 검증 끝남 → 인프라 강화 (M6)**: M0\~M5 채택 후 사용자가 "프로젝트 전면 수정"으로 이미지 지원 명시. spec §3 D1\~D9 합의된 결정.

### 배제 (시도했지만 안 된 것 / 안 하기로 한 것)

- **HTML 외부 URL 이미지 fetch**: 옵션 4 (data URI는 figs/, 외부 URL은 markdown ref 그대로 두기) 채택. v1 SSRF surface 확장 회피. v1.1에서 `options.html_fetch_images=true` 옵션 추가 가능.
- **HWP 이미지 추출**: pyhwp가 bindata 추출 안 함. M6d에서 `metadata.image_drop_count` 카운터만 세팅 (사용자에게 "원래 이미지 N개 있었지만 컨버터 한계로 드롭" 신호).
- **권고 1·2를 M6a 안에서 즉시 처리**: 안 함. Codex도 "M6b 시작 전 처리 권장"이라 명시. 실제 컨버터가 image-bearing cache를 만들기 시작할 때 보강이 자연스러움.

## ⚠️ 클리어 전 주의

- **커밋 안 됨**: `docs/reviews/2026-05-23-m6a-image-infrastructure-codex.md` 1 untracked. **다음 단계 1**에서 commit하면 됨. 사용자가 미리 commit 하려면 `git add ... && git commit -m "docs(reviews): M6a Codex round-1 review"`.
- **백그라운드**: 없음.
  - 이 conversation에서 시작한 모든 `uvicorn` 인스턴스는 `pkill`로 종료 확인.
  - `poll_codex.sh` background poll은 completed.
  - tmux `md:codex` 윈도우는 살아있음 (Codex `--yolo` 프로세스) — 정상. 다음 세션에서 재리뷰 송부 시 그대로 사용.
- **미완료 todo**: 없음. 모든 TaskCreate items (#1\~#14) completed. 새 세션에서는 새로 만들면 됨.
- **Codex context**: Codex 측 컨텍스트는 round-1 답변 직후 그대로. Footer는 `Context 14% used · 5h 100% · weekly 86%` — 헤드룸 충분. 재리뷰 시 round-1 응답 파일 경로를 메시지에 포함하면 됨 (skill의 Iteration Pattern Round 2 패턴).

## 📂 관련 파일

- `PROCESS_STATE.md` — 헤더 "최종 갱신"에 M6a 완료 기록 (`fee7eae`). §4 로드맵에 Phase M6 IN PROGRESS. 새 세션의 정본 상태 문서.
- `docs/specs/2026-05-23-m6-image-support-design.md` — M6 전체 binding spec (630줄, 12 섹션, D1\~D9). **권고 4에서 §5.3 regex 패치 필요**.
- `docs/superpowers/plans/2026-05-23-m6a-image-infrastructure.md` — M6a 9 task TDD plan (1489줄). 향후 M6b/c/d/e/f 별도 plan 파일.
- `docs/reviews/2026-05-23-m6a-image-infrastructure-codex.md` — Codex round-1 (untracked, 14.6K). **commit 필요**.
- `src/mdflow/converters/base.py` — `ImageAsset` frozen dataclass + `ConversionResult.images`. `assets` field 제거됨.
- `src/mdflow/converters/_image_util.py` — `sha_filename`, `make_image_asset`, `canonical_ref`, `EXT_BY_CT`, `content_type_to_ext`. M6b\~M6d 컨버터들이 import할 헬퍼.
- `src/mdflow/core/cache.py` — `write`/`read` (canonical, rename 완료), `build_bundle` (lazy ZIP_STORED). 권고 1·2 보강 후보 위치.
- `src/mdflow/views/{none,embed,zip}.py` — 3 view synthesizer. `[^\]]*` regex 적용 완료. M6e가 transport handler에서 호출.
- `src/mdflow/api/{convert.py,admin.py}` — JSON 응답에 `"assets":[]` shim 유지.
- `src/mdflow/core/service.py` — `images=result.images` 전파.
- `src/mdflow/core/events.py` — `Done.assets: list[str]` SSE shim **미변경** (M6 동안 유지).
- `tests/converters/test_image_util.py` — **권고 5 처리 위치** (`test_content_type_to_ext_jpg_alias` 추가).
- `tests/test_cache_canonical.py`, `tests/views/test_{none,embed,zip}.py`, `tests/converters/test_base.py`, `tests/test_cache.py` — M6a 신규/마이그레이션된 테스트들.

## 🔁 재시작 메시지 (다음 세션에 복사)

```
/media/restful3/data/workspace/mdflow/HANDOFF.md 를 읽고, "⚠️ 클리어 전 주의"를 먼저 확인한 뒤 "⏭️ 다음 단계"부터 이어서 작업해줘.
```
