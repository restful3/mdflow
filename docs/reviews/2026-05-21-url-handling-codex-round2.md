# mdflow URL 입력 처리 설계 검토 - Codex Round 2

작성일: 2026-05-21
대상:
- Claude 메타리뷰: `docs/reviews/2026-05-21-url-handling-claude-meta-review.md`
- mdflow PRD: `docs/specs/2026-05-21-mdflow-design.md`
- Codex Round 1: `docs/reviews/2026-05-21-url-handling-codex-round1.md`

## Part A. Q1-Q3 답변

### Q1. v1 fetch quality gate에 키워드 셋을 둘 것인가

권장: **v1에서는 keyword 기반 hard reject를 넣지 않고, v1.1로 연기**합니다.

이유:
- v1의 목적은 URL이 반환한 단일 리소스를 안전하게 다운로드해 기존 변환 파이프라인에 넘기는 것입니다. `cloudflare`, `captcha` 같은 키워드 셋은 운영 중 계속 업데이트해야 하고, 언어권/서비스별 false positive가 큽니다.
- HTTP status, redirect 정책, max bytes, magic bytes/Content-Type 판별만으로 v1 fetch 계층의 핵심 실패는 충분히 구분됩니다.
- custom 200 error page는 실제로 완전히 잡기 어렵습니다. v1에서 애매한 본문을 reject하면 짧은 정상 문서, 로그인 안내문, 영수증, 이미지 중심 PDF를 잘못 막을 수 있습니다.
- 변환 후 결과가 비어 있거나 매우 짧은 문제는 converter metadata warning 또는 후속 품질 평가에서 다루는 편이 mdflow의 범용성에 맞습니다.

정리:
- v1 hard reject: invalid URL, SSRF 정책 위반, redirect limit, non-2xx, too large, unsupported/unknown format.
- v1 optional warning: 구현 부담이 낮다면 `fetch_warnings`에 "possible_bot_or_error_page" 정도를 기록할 수는 있지만, PRD v1 필수 요구로 두지는 않습니다.
- v1.1 검토: 키워드 기반 bot/error classifier, converter별 empty-output gate, 사용자 override 정책.

### Q2. cache key는 bytes 기준 유지인가, URL 포함인가

권장: **옵션 A, bytes 기준 cache key 유지 + request별 fetch metadata 외부 합성**입니다.

이유:
- PRD의 현재 캐시 철학은 `sha256(input_bytes || canonical_options_json)`이고, 변환 결과는 "바이트와 옵션"의 함수입니다. URL은 변환 결과의 본질적 입력이 아니라 fetch provenance입니다.
- 같은 문서가 CDN URL, presigned URL, DOI redirect, mirror URL 등 여러 경로로 들어올 수 있습니다. URL을 cache key에 넣으면 동일 바이트 중복 변환이 늘어납니다.
- provenance 문제는 cache key에 URL을 넣는 대신 request metadata를 분리하면 해결됩니다.

v1 정책:
- 변환 캐시 key는 계속 `sha256(input_bytes || canonical_options_json)`로 유지합니다.
- URL 요청의 `source_url`, `effective_url`, `http_status`, `content_type`, `content_length`, `fetched_at`, `filename_hint`는 캐시 불변 `meta.json`에 단일 source로 저장하지 않습니다.
- `event: done`과 MCP 응답에는 캐시 결과 metadata와 요청별 fetch metadata를 합성해 반환합니다.
- `/cache/{sha256}`는 변환 캐시의 불변 metadata만 반환하고, 기본적으로 `source_url`/`effective_url`을 보여주지 않습니다. URL provenance 조회가 필요하면 별도 request log 또는 v1.1 기능으로 분리합니다.

### Q3. 사용자 지정 header/cookie/follow_redirects v1 범위

권장:
- **사용자 지정 header/cookie는 v1에서 완전 차단**합니다.
- `follow_redirects=false`는 v1 API 옵션으로 노출하지 않습니다.

이유:
- 사용자 임의 header/cookie는 인증 우회, 내부 서비스 접근, 로그/캐시의 secret 노출, cache variance 증가를 만듭니다.
- limited allowlist도 v1에는 이점이 작습니다. `Accept-Language`조차 응답 바이트를 바꿀 수 있어 cache key와 재현성에 영향을 줍니다. 기존 `language_hint`는 OCR/변환 힌트로만 유지하고 fetch header로 쓰지 않습니다.
- redirect는 DOI, object storage, CDN에서 정상 동작에 필요합니다. 사용자가 끄는 옵션을 두면 동작 표면이 늘고, 보안적으로도 per-hop SSRF 검증 모델을 흐립니다.

v1 정책:
- mdflow 고정 `User-Agent`와 보수적 `Accept`만 사용합니다.
- cookie, Authorization, 임의 header 전달은 v1 비목표입니다.
- redirect는 항상 mdflow 정책으로 처리합니다: 최대 횟수 제한, 각 hop URL 검증, 각 hop DNS/IP SSRF 검증, 최종 `effective_url` 기록.
- v1.1에서 인증이 들어간 HTTP fetch가 필요하면 별도 credential store/allowlist/감사 로그를 전제로 재설계합니다.

## Part B. 합의된 v1 URL 처리 권고 통합본 - PRD 패치 형태

아래는 실제 PRD 파일 `docs/specs/2026-05-21-mdflow-design.md` 기준 라인 번호입니다.

### 1. §1.2 비목표 추가/수정

현재 PRD:
- `L32`: `- 임의 URL 크롤링/SPA 렌더링 (HTML 입력은 정적 문서 가정, URL 입력은 v1 단순 GET 폴백만)`

교체 제안:

```md
- 임의 URL 크롤링/SPA 렌더링 (HTML 입력은 정적 문서 가정, URL 입력은 v1에서 단일 리소스 GET + 제한된 redirect 처리만 지원)
- URL 내 문서 발견/사이트별 변환 규칙 (예: HTML에서 PDF 링크 추출, arXiv/OpenReview/학술 publisher transformer, citation meta tag 해석은 호출자 또는 PaperFlow 책임)
- Headless browser/Chromium 기반 print-to-PDF, 사용자 지정 header/cookie 전달, 인증이 필요한 URL fetch
```

의도:
- PaperFlow D/F/G/H를 v1 비목표로 명시합니다.
- DOI 전용 pre-resolve도 별도 목표로 두지 않고 generic redirect 처리에 흡수합니다.

### 2. §5 데이터 흐름에 URL 입력 전처리 단계 삽입

현재 PRD:
- `L160`: `## 5. 데이터 흐름 — POST /convert`
- `L162-L177`: 1-7단계 데이터 흐름

패치 제안:
- `L162`의 1단계를 아래처럼 교체합니다.

```md
1. **수신**: `multipart/form-data` 파일 또는 `application/json` `{url}` / `{content_base64, filename}` 수신
```

- `L162` 직후, 즉 기존 1단계와 2단계 사이에 새 하위 섹션을 삽입합니다.

```md
### 5.0 URL 입력 전처리

`{url}` 또는 MCP `convert_url` 입력은 변환 전에 다음 fetch 단계를 통과한다. 이 단계의 출력은 "다운로드된 바이트/임시 파일 + fetch metadata"이며, 이후 흐름은 파일 입력과 동일하다.

1. URL을 파싱하고 scheme이 정확히 `http` 또는 `https`인지 확인한다. host가 없거나 userinfo(`user:pass@host`)가 있으면 `URL_INVALID`로 거부한다.
2. fragment는 fetch와 cache에 사용하지 않는다. 운영 로그에는 URL query를 기본 redaction한다.
3. DNS 이름 또는 IP literal을 연결 직전에 검증한다. `MDFLOW_ALLOW_PRIVATE_URLS=false`이면 loopback, private, link-local, multicast, unspecified, cloud metadata IP(예: `169.254.169.254`)를 `URL_BLOCKED`로 거부한다. IPv4와 IPv6 모두 적용한다.
4. mdflow 고정 `User-Agent`와 보수적 `Accept` header로 GET을 수행한다. 사용자 지정 header, cookie, Authorization 전달은 v1에서 지원하지 않는다.
5. redirect는 mdflow가 관리한다. 최대 `MDFLOW_URL_MAX_REDIRECTS`회까지 따르며, 각 hop마다 URL 파싱, scheme/host 검사, DNS/IP SSRF 검사를 반복한다. 초과 시 `URL_REDIRECT_LIMIT`.
6. connect/read timeout은 fetch 전용 환경변수로 제한한다. fetch timeout은 `URL_TIMEOUT`, 변환 timeout은 기존 `TIMEOUT`으로 구분한다.
7. 응답은 temp file로 streaming 저장하며 `MDFLOW_MAX_URL_INPUT_MB`를 넘으면 즉시 중단하고 `URL_TOO_LARGE`를 반환한다. Content-Length가 없거나 chunked 응답이어도 실제 수신 바이트 기준으로 제한한다.
8. 최종 HTTP status가 2xx가 아니면 `URL_NON_2XX`로 실패한다.
9. 포맷 감지는 magic bytes를 우선하고, 그 다음 `Content-Type`, `Content-Disposition` filename, URL path extension을 hint로 사용한다. 불일치 시 magic 우선이며 경고를 metadata에 기록한다.
10. `source_url`, `effective_url`, `http_status`, `content_type`, `content_length`, `content_disposition`, `filename_hint`, `fetched_at`, `redirect_count`, `fetch_warnings`를 request별 fetch metadata로 보존한 뒤 기존 포맷 감지/캐시/변환 흐름으로 넘긴다.
```

- 기존 `L163-L177`의 번호를 다음처럼 재번호화합니다.

```md
2. **포맷 감지**: 확장자/filename hint + Content-Type + magic bytes 교차검증. 불일치 시 magic 우선, 경고를 메타데이터에 기록
3. **캐시 키 계산**: `sha256(input_bytes || canonical_json(options))`
4. **캐시 적중**: `event: cached` → request별 metadata를 합성한 `event: done` 발행 후 스트림 닫음
5. **캐시 미스**:
   - 컨버터 라우팅: `Registry.select(format, capabilities)` → 가장 우선 순위 높은 `Converter`
   - `event: started` 발행
   - GPU 컨버터면 `gpu_semaphore.acquire()` — 즉시 못 잡으면 `event: queued` 발행
   - 변환 실행은 `loop.run_in_executor(cpu_pool, converter.convert, ctx, on_progress)`
   - 컨버터의 `on_progress` 콜백이 `event: progress` 발행
   - 완료 시 변환 결과를 캐시에 원자적으로 저장(tmp + os.replace)
   - `event: done` (markdown 본문 + 변환 metadata + request별 fetch metadata 포함) 발행 후 스트림 닫음
6. **컨버터 실패**:
   - 라우터에 정의된 fallback 체인을 순서대로 시도(상세는 §8.2)
   - 모든 단계가 실패하면 마지막 시도의 코드/메시지를 `event: error`로 보고
7. **에러**: SSE는 HTTP 200 유지(스트림 안에서만 에러). 클라이언트는 마지막 이벤트 종류로 성공/실패 판단.
```

품질 게이트 결정:
- v1 PRD에는 keyword 기반 bot/error hard reject를 넣지 않습니다.
- `fetch_warnings`는 optional field로만 둡니다. v1.1에서 classifier 또는 keyword gate를 별도 검토합니다.

### 3. §5.1 SSE 이벤트 스키마 수정

현재 PRD:
- `L186`: `event: done      data: {"markdown":"# ...","metadata":{...},"assets":[]}`

교체 제안:

```text
event: done      data: {"markdown":"# ...","metadata":{"input_kind":"url","fetch":{...},"conversion":{...}},"assets":[]}
```

추가 문장 삽입 위치:
- `L190` 뒤에 삽입.

```md
URL 입력의 `done.metadata.fetch`는 request별 metadata이며, 캐시된 변환 결과를 반환할 때도 현재 요청의 `source_url`/`effective_url`을 기준으로 합성된다.
```

### 4. §6 API 표면 변경점

현재 PRD:
- `L204-L212`: 요청 옵션 목록

삽입 위치:
- `L212` 코드 블록 직후에 삽입.

```md
URL 입력 v1 제약:

- `url`은 `http`/`https`만 허용한다.
- 사용자 지정 header, cookie, Authorization 전달 옵션은 v1에서 제공하지 않는다.
- `follow_redirects` 옵션은 제공하지 않는다. mdflow가 고정 redirect 정책과 per-hop SSRF 검증을 적용한다.
- URL fetch 한도와 private network 허용 여부는 요청 옵션이 아니라 서버 환경변수로만 제어한다.
```

API endpoint 자체는 추가하지 않습니다. `/convert`의 JSON `{url}`와 MCP `convert_url`만 명확히 합니다.

### 5. §7 MCP 표면 문구 추가

현재 PRD:
- `L223`: `- stdio 모드에서 path 입력은 클라이언트 파일시스템 접근을 의미한다...`
- `L224`: SSE 진행 이벤트 문장

삽입 위치:
- `L223` 다음에 삽입.

```md
- `convert_url`은 mdflow 프로세스가 실행되는 환경의 네트워크에서 URL을 fetch한다. stdio MCP에서는 사용자의 로컬 실행 환경 네트워크, HTTP/Streamable HTTP에서는 서버 네트워크가 기준이다. 두 transport 모두 동일한 URL 검증과 SSRF 정책을 적용한다.
```

### 6. §8.1 에러 코드 enum 항목 추가

현재 PRD:
- `L230-L239`: 표준 에러 코드 표

삽입 위치:
- `L234 INPUT_TOO_LARGE` 다음 또는 URL 계층 구분을 위해 `FORMAT_DETECT_FAILED` 다음에 삽입.

```md
| `URL_INVALID` | URL scheme/host/userinfo 등 기본 검증 실패 | false |
| `URL_BLOCKED` | SSRF 정책 또는 private network 정책으로 차단 | false |
| `URL_FETCH_FAILED` | DNS, 연결 실패, TLS 오류 등 fetch 실패 | true |
| `URL_TIMEOUT` | URL fetch connect/read timeout 초과 | true |
| `URL_TOO_LARGE` | URL 응답이 `MDFLOW_MAX_URL_INPUT_MB` 초과 | false |
| `URL_REDIRECT_LIMIT` | redirect 최대 횟수 초과 | false |
| `URL_NON_2XX` | 최종 HTTP status가 2xx가 아님 | false |
```

추가 설명 삽입 위치:
- `L247-L252`의 `### 8.3 타임아웃 정책` 아래에 URL fetch timeout 설명을 추가합니다.

```md
- URL fetch timeout은 변환 timeout과 별도다. fetch 단계의 connect/read timeout은 `URL_TIMEOUT`, 변환 실행 timeout은 `TIMEOUT`으로 보고한다.
```

### 7. §9 캐시 정책에 source_url/effective_url 분리 문구 추가

현재 PRD:
- `L256`: `- 키: sha256(input_bytes || canonical_options_json) ...`
- `L262`: `meta.json # converter, gpu, duration_ms, version, options, sha256`

교체 제안:

```md
- 키: `sha256(input_bytes || canonical_options_json)` — 입력 바이트와 변환 옵션이 모두 같아야 적중. URL 입력도 다운로드된 바이트 기준으로 캐시하며 URL 문자열은 캐시 키에 포함하지 않는다.
```

`L262` 교체 제안:

```text
    meta.json         # converter, gpu, duration_ms, version, options, sha256 등 변환 불변 metadata
```

삽입 위치:
- `L268` 뒤에 삽입.

```md
- URL provenance: `source_url`, `effective_url`, HTTP status/header, `fetched_at` 등은 request별 fetch metadata로 취급한다. 동일 바이트를 여러 URL에서 받은 경우 하나의 변환 캐시를 공유하되, `event: done`/MCP 응답에서는 현재 요청의 fetch metadata를 변환 metadata와 합성한다.
- `/cache/{sha256}`는 기본적으로 변환 캐시의 불변 metadata만 반환한다. signed URL이나 query token 노출을 피하기 위해 request별 `source_url`/`effective_url`은 캐시 조회 응답에 저장/노출하지 않는다.
```

### 8. §10 테스트 전략에 URL fetch 축 추가

현재 PRD:
- `L274-L278`: `### 10.1 계층` 테스트 bullet

삽입 위치:
- `L278` 다음에 삽입.

```md
- **URL fetch**: invalid scheme/host/userinfo 거부, localhost/private/link-local/metadata IP 차단, public URL에서 private URL로 redirect 차단, redirect limit 초과, Content-Length 및 chunked 응답 크기 초과, non-2xx status 처리, Content-Type과 magic bytes 불일치, Content-Disposition filename hint, 같은 bytes를 다른 URL에서 받을 때 request별 provenance 합성 검증
```

추가 삽입 위치:
- `L287-L289` `### 10.3 회귀 방지` 아래에 추가.

```md
- URL fetch 테스트는 실제 외부 네트워크에 의존하지 않고 `httpx` mock transport 또는 로컬 테스트 서버로 재현한다. SSRF 테스트는 DNS/IP resolution을 모킹해 redirect별 검증을 포함한다.
```

### 9. §11 의존성 변경

현재 PRD:
- `L304`: `httpx`가 이미 포함되어 있음

변경 필요:
- 새 패키지 추가는 v1 PRD 기준으로 필수 아님. `httpx`가 이미 있으므로 URL fetch에 사용합니다.

삽입 위치:
- `L293` 직후 또는 dependency 블록 전 설명에 추가.

```md
URL fetch는 기존 `httpx` 의존성을 사용한다. SSRF 검증은 표준 라이브러리(`ipaddress`, `socket`, `urllib.parse`)와 얇은 내부 helper로 구현하고, v1에서는 별도 crawler/browser 의존성을 추가하지 않는다.
```

### 10. §12 운영 고려사항에 URL fetch 환경 변수 추가

현재 PRD:
- `L331`: `- 리소스 한도: 입력 크기 MDFLOW_MAX_INPUT_MB(기본 200MB)`

교체/확장 제안:

```md
- **리소스 한도**: 입력 크기 `MDFLOW_MAX_INPUT_MB`(기본 200MB). URL 입력은 별도 `MDFLOW_MAX_URL_INPUT_MB`를 적용하며 기본값은 `MDFLOW_MAX_INPUT_MB` 이하로 둔다.
```

삽입 위치:
- `L331` 다음에 삽입.

```md
- **URL fetch 보안 기본값**:
  - `MDFLOW_ALLOW_PRIVATE_URLS=false` (기본). true는 로컬 개발/폐쇄망 배포에서만 사용한다.
  - `MDFLOW_URL_MAX_REDIRECTS=5`
  - `MDFLOW_URL_CONNECT_TIMEOUT_S=10`
  - `MDFLOW_URL_READ_TIMEOUT_S=30`
  - `MDFLOW_URL_USER_AGENT="mdflow/1.0 (+https://github.com/...)"` 형태의 고정 UA
  - URL query는 운영 로그에서 기본 redaction한다.
```

주의:
- 구체 UA의 URL은 실제 repository가 정해지면 채웁니다.
- timeout 수치는 PRD 기본값으로 두되, 코드 작성 시 설정 객체에서 검증합니다.

### 11. §13 미해결/추후 결정 사항 정리

현재 PRD:
- `L339`: `- URL 입력의 SPA/봇 차단 대응: PaperFlow의 헤드리스 Chrome 폴백 도입 여부 — v1은 단순 GET만 지원`
- `L340`: `- MCP convert_url의 도메인 화이트리스트: SSRF 방지용 — v1은 documentation 차원에서 사용자에게 위임, v1.1에서 정책 검토`

교체 제안:

```md
- **URL 입력의 SPA/Headless 대응**: Headless Chrome/Chromium 기반 렌더링 또는 print-to-PDF는 v1 비목표. v1.1 이후 별도 sandbox/resource-limit 설계와 함께 검토
- **URL 품질 게이트 고도화**: custom 200 bot/error page 감지, keyword/classifier 기반 reject, converter별 empty-output 품질 평가는 v1.1에서 검토. v1은 HTTP status, size, format detect 중심
- **인증이 필요한 URL fetch**: 사용자 지정 header/cookie/Authorization 전달은 v1 비목표. v1.1 이후 credential store, allowlist, 감사 로그와 함께 재검토
- **도메인 allowlist/blocklist 정책**: v1은 기본 SSRF 차단과 `MDFLOW_ALLOW_PRIVATE_URLS`만 제공한다. 운영자 정의 allowlist/blocklist는 v1.1에서 검토
```

삭제/정리:
- 기존 `L340`의 "SSRF 방지용 — v1은 documentation 차원에서 사용자에게 위임" 문구는 제거합니다. SSRF는 v1 필수 구현으로 끌어올렸기 때문입니다.

## Part C. 잔존 이견

잔존 이견은 **0건**입니다.

다만 Round 1 대비 조정된 최종 결정은 1건 있습니다.

- fetch quality gate: Round 1에서는 "명백한 bot/error keyword 정도는 v1"이라고 제안했지만, Claude의 운영 부담 지적을 반영해 v1 hard reject에서는 제외합니다. 최종 합의안은 "v1은 HTTP status/size/format detect 중심, keyword/classifier 기반 custom 200 error page 탐지는 v1.1"입니다.

