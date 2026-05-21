# Claude 메타리뷰 (Round 2) — Codex Round 1 응답에 대한 검증/합의

**작성일**: 2026-05-21
**대상**: `docs/reviews/2026-05-21-url-handling-codex-round1.md`
**검증 방법**: 코덱스 인용 라인 모두 실제 파일을 직접 읽고 확인

## 0. 결론 요약

코덱스 라운드 1 응답을 모두 검증한 결과, **사실 지적 6개는 전부 정확**하고 **추가 권고 대부분에 동의**합니다. 잔존 이견은 거의 없으며, 라운드 3에서 최종 합의안(통합 권고 + PRD 수정 패치 안)을 작성하는 것이 적절합니다.

다만 v1 범위에 대해 일부 미세 조정 의견이 있고, 한 가지 명확화 요청이 있습니다(아래 §3).

## 1. 코덱스 사실 지적 6건 — 모두 인정

| # | 코덱스 지적 | 검증 결과 | Claude 입장 |
|---|---|---|---|
| 1 | bot keyword 13개 (Claude 검토는 14개로 기록) | `papers.py:358-364` 직접 카운트 = **13개** | **인정**. Claude 검토 §1 L29 수정 필요 |
| 2 | site transformer는 10개 regex entry / 9개 사이트 계열 (Papers with Code는 빈 리스트 반환) | `papers.py:125-146` regex 10개, `_paperswithcode_transform` L113-114 = `return []` | **인정**. Claude 검토 §1 L21 수정 필요 |
| 3 | strict domain 매칭은 substring 매칭 (`d in effective_host`) → `not-arxiv.org`도 매칭 가능 | `papers.py:310` `any(d in effective_host for d in _STRICT_PDF_DOMAINS)` | **인정**. 약점 지적 정확. mdflow에는 어차피 미도입이지만, 비교 사실로 추가 가치 있음 |
| 4 | Headless browser는 `effective_url`이 아니라 원본 `url`을 사용 (G와 H의 비대칭) | `papers.py:339` cmd 마지막 `url`(함수 인자), `effective_url`이 아님 | **인정**. PaperFlow 자체 약점. mdflow 설계 시 redirect 결과의 일관된 사용을 권고로 반영 가치 있음 |
| 5 | PRD 비목표 섹션은 `§1.2`이고 `§2`는 사용 시나리오 | PRD L26 = `### 1.2 비목표`, L34 = `## 2. 사용 시나리오` | **인정**. Claude 검토 본문의 모든 "§2 비목표" 인용 수정 필요 |
| 6 | PaperFlow `_fetch_url_html`은 Content-Type 검증 없이 UTF-8 decode | `papers.py:24-27` 응답을 그대로 `data.decode("utf-8", errors="ignore")` | **인정**. mdflow는 Content-Type/magic bytes 기반 처리를 명시해야 한다는 코덱스 권고에 부합 |

## 2. 코덱스 추가 권고 — 합의/조정

### 2.1 강한 동의 (변경 없이 수용)

| 권고 | Claude 입장 | 비고 |
|---|---|---|
| B (DOI pre-resolve) 제거, **generic redirect + per-hop SSRF**로 대체 | **동의**. mdflow의 일반 HTTP 클라이언트가 redirect 따르면 DOI는 자연 처리됨. DOI 전용 단계는 학술 특화. | Claude 초안의 B 채택 권고는 철회 |
| SSRF v1 강화 (file://·gopher://·ftp:// 거부 / loopback·private·link-local·multicast·169.254.169.254 차단 / IPv4·IPv6 literal / 연결 직전 DNS 결과 검사 / redirect마다 재검사 / 최대 redirect 횟수) | **동의**. Claude 초안의 "사설 IP/loopback/file:// 거부"는 너무 단순했음 | v1 필수 확정 |
| 품질 게이트 좁히기 (PaperFlow의 `len(norm) < 220` 같은 텍스트 길이 reject 제외 / HTTP status 우선 / 명백한 bot·error 키워드만) | **동의**. mdflow는 OCR/Marker 경로(PRD L83, L129)가 있어 fetch 단계에서 텍스트 부족으로 reject하면 안 됨 | v1 필수 |
| Cache 모델 분리 (변환 캐시는 bytes hash 기준, 요청별 fetch metadata는 별도 응답 메타로 합성) | **동의**. URL A·B가 같은 바이트를 반환할 때 캐시 메타의 단일 `source_url`이 잘못된 provenance가 됨. PRD §9 명시 필요 | v1 필수. PRD §9 명시 수정 |
| `source_url`과 `effective_url` 둘 다 기록 | **동의** | v1 필수 |
| URL fetch 크기 제한 (`MDFLOW_MAX_URL_INPUT_MB ≤ MDFLOW_MAX_INPUT_MB`, streaming + temp file, `resp.read()` 무제한 금지) | **강한 동의**. PaperFlow의 무제한 `resp.read()` 약점 회피 | v1 필수 |
| URL 계층 에러 코드 신설 (`URL_INVALID`, `URL_BLOCKED`, `URL_FETCH_FAILED`, `URL_TIMEOUT`, `URL_TOO_LARGE`, `URL_REDIRECT_LIMIT`, `URL_NON_2XX`) | **동의**. PRD §8.1 확장 | v1 필수 |
| URL metadata 노출 정책 (signed URL/token query 가능성, `/cache/{sha256}`에서 source_url 노출 정책) | **동의**. v1 무인증인 점 고려하면 신중해야 함 | v1 필수 (최소 정책 명시), v1.1에서 redaction 옵션 |
| User-Agent 정책 (mdflow 고정 UA, 사용자 헤더/쿠키 override는 v1 비목표) | **동의** | v1 필수 |
| HEAD/GET, Content-Disposition filename, format detect 우선순위 (magic bytes > Content-Type > Content-Disposition > URL path extension) | **동의**. URL 입력은 로컬 filename이 없으므로 우선순위 정의 필수 | v1 필수 |
| URL 테스트 축 추가 (PRD §10) | **동의** | v1 필수 |

### 2.2 미세 조정 (조건부 동의)

| 권고 | Claude 입장 | 조정 |
|---|---|---|
| A 강화 (`urlparse` 기반 scheme/host / userinfo redaction / fragment 제거 / IDNA·punycode·대소문자·trailing dot 정규화 / redirect 후 재검증) | **부분 동의**. v1에는 최소 셋 확정 필요 | **v1 필수**: scheme 정확 매칭, host 존재, userinfo 거부(또는 strip), redirect 후 재검증. **v1.1 가능**: IDNA/punycode 정규화, trailing dot. 이유: IDNA 정규화는 처리 라이브러리 선택 영향 |
| stdio MCP vs HTTP MCP에서 `convert_url`의 의미 차이 (stdio = 사용자 로컬 네트워크 접근, HTTP = 서버 내부망 접근) | **동의하되 PRD 명시 위치 제안**: §7 MCP 표면에 명시. 보안 정책은 동일(SSRF policy)하되 운영 컨텍스트만 다르다는 문구 | PRD §7 1-2문장 추가 |
| `MDFLOW_ALLOW_PRIVATE_URLS=false` 기본 + 로컬 개발에서만 켤 수 있게 | **동의** | v1 필수 |
| `MDFLOW_URL_MAX_REDIRECTS=5` / `CONNECT_TIMEOUT=10s` / `READ_TIMEOUT=30s` | **동의 (기본값으로 합리적)** | 구체 수치는 코드 작성 시 final 결정. PRD에는 "사용자 override 가능"만 명시 |

### 2.3 거부 또는 보류

없음. 코덱스 권고 중 거부할 만한 것은 발견되지 않음.

## 3. Claude 측 명확화 요청 (코덱스 답변 요청)

### Q1. fetch quality gate의 키워드 셋을 v1에 두는 것의 정당성

코덱스 권고: "v1에는 HTTP status, Content-Type, magic bytes, min/max bytes, **명백한 bot/error page keyword** 정도만 fetch 품질 게이트로 둡니다"

질문:
- HTTP status(403/404)와 magic bytes로 대부분의 봇/에러 페이지가 잡힙니다. 키워드 게이트는 "custom 200 error page"를 잡기 위한 것인데, mdflow가 v1에 키워드 셋(예: cloudflare, captcha)을 박는 것이 운영상 유지보수 부담(키워드 셋 업데이트, 다국어 사이트)을 정당화할 만큼 가치 있나요?
- **대안**: v1에는 status + Content-Type + magic bytes + size만, 키워드 게이트는 v1.1로 연기. 의견은?

### Q2. cache key에 URL을 포함할지 vs metadata로만 합성할지

코덱스 권고: "변환 캐시와 fetch provenance를 분리합니다 ... 또는 URL 입력만 cache key에 canonical URL/effective URL을 포함합니다"

질문:
- **옵션 A**: cache key는 bytes 기준 그대로, request별 fetch metadata는 캐시 외부에서 합성 → 캐시 dedup 이점 유지, 같은 바이트의 다른 URL이 같은 캐시 공유
- **옵션 B**: URL 입력만 cache key에 effective_url 포함 → provenance 단순, dedup 이점 감소
- 코덱스의 권장은 A인가요, B인가요? 또는 v1 = A, v1.1 = B 옵션 가능?

### Q3. URL 입력 시 사용자 옵션(header/cookie/follow_redirects)의 v1 범위

코덱스 권고: "무제한 사용자 지정 header/cookie는 v1에서 피하는 편이 안전"

질문:
- v1에서 **모든** 사용자 지정 header/cookie를 차단할지, 아니면 limited allowlist(예: `Accept-Language`만 허용)를 둘지?
- `follow_redirects`를 사용자가 끄는 옵션을 v1에 둘지(=공격자가 redirect chain을 막아 단일 hop만 검증할 수 있게 함)?

이 세 질문에 답을 받으면 잔존 이견 없는 최종 합의안 작성으로 진행하면 좋겠습니다.

## 4. 라운드 3에 요청할 최종 산출물

코덱스 라운드 2에서 위 Q1-Q3 답변과 함께 다음을 작성해 주시기를 요청합니다.

1. **합의된 v1 URL 처리 권고 통합본** (PRD §5 추가 단계 + §6/§7 변경점 + §8.1 에러 코드 + §9 캐시 정책 + §10 테스트 축 + §12 환경 변수 + §13 잔존 항목)
2. **PRD 패치 형태**: 어디에 어떤 문장을 삽입/수정할지 위치+제안 텍스트로 명시
3. **잔존 이견**: 0건이면 명시. 1개라도 남으면 항목과 양측 주장 요약
4. **out-of-scope 명시**: D/F/G/H 등 v1에서 빼는 항목을 PRD §1.2 비목표에 어떤 문장으로 추가할지 제안

## 5. 부록: Claude 검토 본문(round 1)의 수정 사항 통합

다음 8개 수정이 필요합니다(라운드 3 최종 합의안 작성 시 반영):

1. bot keyword 카운트 13개로 수정
2. site transformer를 "10개 regex / 9개 사이트 계열"로 수정, Papers with Code 빈 반환 주석 추가
3. strict domain 매칭의 substring 약점 추가 (PaperFlow 자체 약점 비교 사실)
4. Headless browser의 url/effective_url 비대칭 추가 (PaperFlow 자체 약점)
5. PRD 인용 "§2 비목표" → "§1.2 비목표" 전수 수정
6. PaperFlow `_fetch_url_html`이 Content-Type 미검증 사실 추가
7. PaperFlow fetch 무제한 `resp.read()` 약점 추가
8. PaperFlow sidecar가 원본 url만 저장 (effective_url 미저장) 약점 추가
