# M6a Codex Review — Image Infrastructure

**검토자**: codex (gpt-5.5)
**검토일**: 2026-05-23
**대상**: `git diff 547f4c6..cbece1b`

## 자체 검증

- `git log --oneline 547f4c6..cbece1b`: 요청된 9개 M6a commit 확인.
- `.venv/bin/pytest`: **352 passed / 2 skipped**, 2 warnings.
- `.venv/bin/ruff check src tests`: 통과.
- `.venv/bin/ruff format --check src tests`: **실패**. `src/mdflow/core/cache.py`, `src/mdflow/views/zip.py`, `tests/converters/test_image_util.py`, `tests/test_cache_canonical.py` 4개 파일이 재포맷 필요로 보고됨.

## 차단 (Blocking)

1. **Formatter check가 현재 워크트리에서 실패합니다.**
   - 근거: `ruff format --check`가 `src/mdflow/core/cache.py`, `src/mdflow/views/zip.py`, `tests/converters/test_image_util.py`, `tests/test_cache_canonical.py`를 `Would reformat`으로 보고했습니다. 대표 위치는 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:84), [zip.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/zip.py:15), [test_image_util.py](/media/restful3/data/workspace/mdflow/tests/converters/test_image_util.py:63), [test_cache_canonical.py](/media/restful3/data/workspace/mdflow/tests/test_cache_canonical.py:65)입니다.
   - 왜 문제인가: 프로젝트의 milestone 채택 조건이 계속 `ruff clean`이었고, 이번 요청도 최종 상태를 ruff clean으로 제시했습니다. 실제 검증 결과와 다르므로, M6a 태그 전에는 재포맷 후 동일 명령 재실행이 필요합니다.
   - 제안: `ruff format src tests` 적용 후 `ruff check src tests && ruff format --check src tests`를 다시 통과시키면 됩니다. 동작 차단은 아니지만 CI/품질 게이트 차단으로 분류합니다.

## 권고 (Recommendations)

1. **`Cache.read`가 malformed canonical image metadata를 raw 예외로 노출할 수 있습니다.**
   - 근거: [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:156)에서 `OSError`/`JSONDecodeError`만 `CACHE_IO_ERROR`로 감싸고, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:167)의 `for img_meta in meta.get("images", [])`, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:168)의 `img_meta["name"]`, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:181)의 `img_meta["content_type"]`은 `KeyError`/`TypeError`/잘못된 `images` 타입을 그대로 낼 수 있습니다.
   - 왜 문제인가: JSON corruption과 missing image bytes는 이미 `CACHE_IO_ERROR`로 표준화되어 있습니다. 같은 캐시 부패 범주인 schema corruption만 raw 예외로 빠지는 것은 에러 계약의 균일성을 약하게 합니다.
   - 제안: `images`가 list인지, 각 원소가 dict인지, `name`/`content_type`이 str인지 검증하고 실패 시 `MdflowError(ErrorCode.CACHE_IO_ERROR, ...)`로 감싸세요. M6a에서는 컨버터가 아직 이미지를 쓰지 않으므로 채택 차단은 아니지만, M6b에서 실제 image-bearing cache가 생기기 전 보강하는 편이 좋습니다.

2. **`ImageAsset.name` 경로 안전성은 헬퍼 사용 관례에 의존합니다.**
   - 근거: [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:127)에서 `(figs / img.name).write_bytes(img.data)`를 직접 수행합니다. `make_image_asset` 경로는 [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:36)와 [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:31) 덕분에 안전한 sha 파일명을 만듭니다. 하지만 `ImageAsset` 자체는 public dataclass라 [base.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/base.py:35)에 별도 validation이 없습니다.
   - 왜 문제인가: 내부 컨버터가 실수로 `../x.png` 같은 name을 구성하면 cache tmp tree 밖이나 `figs/` 밖으로 쓰기를 시도할 수 있습니다. 현재는 모든 M6a 테스트가 헬퍼를 통하므로 드러나지 않습니다.
   - 제안: `Cache.write`에서 `img.name == Path(img.name).name`이고 sha 기반 파일명 패턴에 맞는지 검증하거나, `ImageAsset` 생성 API를 헬퍼로 사실상 고정하고 컨버터 구현 규칙에 명시하세요. 실제 컨버터가 이미지를 만들기 시작하는 M6b 전 처리 권장입니다.

3. **`options.images` cache-key 제외 정책은 아직 구현 지점이 열려 있습니다.**
   - 근거: 스펙은 [design.md](/media/restful3/data/workspace/mdflow/docs/specs/2026-05-23-m6-image-support-design.md:135)에서 `options["images"]`를 cache key에서 무시한다고 명시합니다. 현재 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:38)의 `compute_cache_key`는 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:44)에서 전달된 `options` 전체를 JSON hash에 포함하고, [service.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/service.py:76)는 `req.options`를 그대로 넘깁니다.
   - 왜 문제인가: M6a는 API 변경 없음이므로 당장 `options.images`가 들어오지 않는다는 전제에서는 문제 없습니다. 다만 M6e에서 handler가 `images`를 options에 넣는 순간, 기존 M0-M5 cache entry hit와 mode 전환 무재변환 invariant가 깨집니다.
   - 제안: M6e에서만 처리해도 무방하지만, 위치는 `compute_cache_key` 내부 또는 `canonical_cache_options(options)` 같은 단일 helper가 적절합니다. 호출자별 수동 제거보다 중앙화하는 편이 HTTP/MCP/CLI drift를 줄입니다.

4. **view regex와 `canonical_ref`의 alt escaping 정책을 M6b 전에 확정하세요.**
   - 근거: `canonical_ref`는 [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:44)에서 alt를 그대로 `![{alt}]`에 삽입합니다. view regex는 [none.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/none.py:15), [embed.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/embed.py:25)에서 `[^\]]*`를 사용합니다.
   - 왜 문제인가: 현재 regex는 multi-image line backtracking 문제를 피하고, 빈 alt도 처리합니다. 그러나 CommonMark의 모든 합법 케이스를 파싱하지는 않습니다. 특히 escaped `\]`가 포함된 alt는 매치되지 않거나 일부만 처리될 수 있습니다. M6a에서는 canonical markdown을 아직 새 컨버터가 만들지 않으므로 실질 위험은 낮습니다.
   - 제안: 컨버터가 실제 이미지 alt를 가져오기 전, `canonical_ref`에서 `]`와 `\` escaping을 명시적으로 처리하거나 "canonical alt는 `]`를 포함하지 않는다"는 제한을 스펙에 적으세요. 스펙의 예시 regex도 [design.md](/media/restful3/data/workspace/mdflow/docs/specs/2026-05-23-m6-image-support-design.md:187), [design.md](/media/restful3/data/workspace/mdflow/docs/specs/2026-05-23-m6-image-support-design.md:190)의 `(.*?)`에서 구현과 같은 `[^\]]*` 계열로 고쳐야 다음 task가 잘못된 template을 복사하지 않습니다.

5. **`image/jpg` alias 직접 lookup 테스트를 추가하세요.**
   - 근거: alias 자체는 [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:18)에 있고, [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:27)의 lowercase lookup 때문에 동작합니다. 테스트는 [test_image_util.py](/media/restful3/data/workspace/mdflow/tests/converters/test_image_util.py:63)에서 set membership만 확인하고, `content_type_to_ext("image/jpg") == "jpg"` 직접 assertion은 없습니다.
   - 왜 문제인가: 기능 결함은 아닙니다. 다만 이미 reviewer follow-up으로 식별된 gap이고, external producer가 `image/jpg`를 넘기는 케이스를 고정하는 값싼 회귀 테스트입니다.
   - 제안: M6b 시작 전 `test_content_type_to_ext_jpg_alias` 하나를 추가하면 충분합니다.

6. **code fence 보호 로직의 의도된 축약을 스펙에 남기는 편이 좋습니다.**
   - 근거: [none.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/none.py:23), [embed.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/embed.py:38)는 `line.lstrip().startswith("```")`로 fence를 토글합니다.
   - 왜 문제인가: CommonMark 기준으로 4칸 이상 들여쓴 fence는 indented code block에 가까운데, 현재 구현은 그것도 fence로 봅니다. 또한 `~~~` fence는 보호하지 않습니다. mdflow의 canonical markdown 생성 범위에서는 실용상 충분하지만, "full CommonMark parser"는 아닙니다.
   - 제안: M6a 코드 변경은 필요하지 않습니다. §5.3에 "generated canonical markdown 대상의 lightweight fence protection"이라고 명시하거나, 필요하면 M6e 전 `markdown-it-py` 같은 parser 도입 여부를 별도 판단하세요.

## 메모 (Notes)

1. **자료구조와 wire compatibility는 스펙과 일치합니다.**
   - [base.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/base.py:35)의 frozen `ImageAsset`와 [base.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/base.py:49)의 `ConversionResult.images`는 §4.2와 맞습니다. `ConversionResult.assets` 제거도 [design.md](/media/restful3/data/workspace/mdflow/docs/specs/2026-05-23-m6-image-support-design.md:98)의 v2.0 정책과 일치합니다.
   - API 응답의 `"assets":[]` shim은 [convert.py](/media/restful3/data/workspace/mdflow/src/mdflow/api/convert.py:36)와 [admin.py](/media/restful3/data/workspace/mdflow/src/mdflow/api/admin.py:53)에 유지되어 wire-format 영향이 없습니다. `Done.assets`를 즉시 제거하는 것보다 v2.0 호환 shim으로 남기는 현재 선택이 낫습니다. 직접 `ConversionResult(assets=...)`를 쓰던 외부 라이브러리 코드는 깨질 수 있지만, M6가 v2.0 major인 점을 고려하면 정당한 breaking change입니다.

2. **content-addressed dedup invariant는 구현되어 있습니다.**
   - [\_image_util.py](/media/restful3/data/workspace/mdflow/src/mdflow/converters/_image_util.py:31)의 sha256 filename과 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:106)의 name 기준 first-wins dedup가 맞물립니다. 컨버터 경계가 달라도 같은 bytes/content-type 조합은 같은 파일명으로 수렴합니다.
   - `image/jpeg`와 `image/jpg`가 모두 `jpg`로 매핑되는 결정도 합리적입니다. [embed.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/embed.py:20)의 reverse map은 first-wins라 `.jpg`를 `image/jpeg`로 canonicalize합니다. 상호운용 관점에서도 `image/jpeg`가 더 표준적인 MIME이므로 문제로 보지 않습니다.

3. **Cache.read stats semantics는 post-rename 후에도 보존되어 있습니다.**
   - absent entry는 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:153)에서만 `miss_count`를 올립니다. 성공 read는 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:185)에서만 `hit_count`를 올립니다. JSON corruption과 missing image bytes는 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:159), [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:172)에서 예외로 빠져 어느 counter도 갱신하지 않습니다.
   - 이 동작은 user가 확인 요청한 "Cache.read post-rename stats semantics 보존" 항목에 대해 PASS입니다.

4. **Legacy M0 cache entry는 마이그레이션 스크립트 없이 읽힙니다.**
   - [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:143)는 legacy `assets` meta를 명시하고, 실제 구현은 [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:167)의 `meta.get("images", [])` 덕분에 `images=[]`로 round-trip합니다. 회귀 테스트도 [test_cache_canonical.py](/media/restful3/data/workspace/mdflow/tests/test_cache_canonical.py:101)에 있습니다.

5. **`build_bundle`의 lazy ZIP_STORED 설계는 M6a 범위에 적합합니다.**
   - [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:192)는 cache miss 또는 zero-image entry에서 `None`을 반환하고, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:208)의 existing bundle fast path, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:218)의 `ZIP_STORED`, [cache.py](/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:223)의 `os.replace`가 스펙과 맞습니다.
   - [zip.py](/media/restful3/data/workspace/mdflow/src/mdflow/views/zip.py:15)의 thin adapter는 handler symmetry를 위한 정당한 adapter로 보입니다. 이 정도 추상화는 YAGNI로 보지 않습니다.

6. **Commit 분해는 합리적입니다.**
   - 첫 8개 commit은 additive infra와 tests 중심이고, `cbece1b`에서 final migration을 수행한 구조가 좋습니다. `tests/views/test_zip.py` 추가는 plan 외 발견 사항을 보완한 것으로 자연스럽습니다. Task 9가 여러 파일을 만졌지만 `assets -> images` API 전환의 단일 절단점이라 더 쪼개야 할 필요는 낮습니다.

## 6개 in-scope 영역별 판정

1. **자료구조 (§4.2)**: PASS. Wire shim 유지가 맞고, `Done.assets` 즉시 제거는 권하지 않습니다. 직접 dataclass API break는 v2.0 major에서 허용 가능한 범위입니다.
2. **공통 헬퍼 (§7.1)**: PASS with recommendation. `image/jpg` alias는 코드상 동작하나 직접 테스트를 추가하세요. `canonical_ref` alt escaping 정책은 M6b 전 확정이 필요합니다.
3. **캐시 디스크 레이아웃 + 트랜잭션 (§4.4, §5.4)**: PASS with recommendations. Legacy compat와 stats semantics는 보존되었습니다. `Cache.read` malformed image metadata wrapping, `ImageAsset.name` validation, `options.images` cache-key 중앙화가 남아 있습니다.
4. **View synthesis (§5.3)**: PASS with recommendations. `[^\]]*` regex는 M6a canonical refs에는 적절하고 multi-image line bug를 피합니다. full CommonMark alt/fence parser는 아니므로 제한을 문서화하거나 M6b 전 escaping helper를 두세요.
5. **마이그레이션 & 호환성 (§10)**: PASS. Response JSON의 `"assets":[]` shim 덕분에 wire-format은 유지됩니다. `ConversionResult.assets` 제거는 v2.0 major breaking change로 수용 가능합니다.
6. **TDD discipline + commit hygiene**: PASS, 단 formatter check 실패는 별도 차단입니다.

## 종합 의견

동작 설계 기준으로는 M6a 단독 채택이 가능합니다. 다만 현재 워크트리에서 `ruff format --check`가 실패하므로 **차단 1건(formatter) 처리 후 채택**으로 판단합니다. 권고 사항은 모두 M6b/M6e 전 보강하면 충분하며, 이미지 인프라 설계 자체를 다시 쪼갤 필요는 없습니다.
