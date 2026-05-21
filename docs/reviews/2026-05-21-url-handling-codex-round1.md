# mdflow URL 입력 처리 설계 검토 - Codex Round 1

작성일: 2026-05-21
대상:
- 검토 본문: `docs/reviews/2026-05-21-url-handling-claude-review.md`
- mdflow PRD: `docs/specs/2026-05-21-mdflow-design.md`
- PaperFlow 코드: `/media/restful3/data/workspace/paperflow/viewer/app/services/papers.py`

## 결론

Claude 검토의 큰 방향은 맞습니다. mdflow가 PaperFlow의 학술 PDF 발견 파이프라인을 흡수하지 않고, 범용 변환 게이트웨이로서 URL fetch의 안전성, 포맷 판별, provenance를 책임지는 방향이 타당합니다.

다만 v1 채택 권고 5개는 그대로는 필요충분하지 않습니다. 특히 DOI pre-resolve는 mdflow v1의 독립 단계로는 필수성이 약하고, SSRF 차단은 단순 "사설 IP 거부"보다 redirect/DNS/metadata IP까지 포함한 fetch 정책으로 정의되어야 합니다. 또한 `source_url`을 캐시 메타에 넣는 권고는 PRD의 현재 캐시 키(`sha256(input_bytes || options)`)와 충돌할 수 있습니다. 같은 바이트를 여러 URL이 반환하면 캐시 메타의 단일 `source_url`이 잘못된 provenance가 됩니다.

## 1. 사실 정확성 검증

### 대체로 정확한 항목

- PaperFlow의 URL 파이프라인이 `import_url_as_paper(url, title=None)`에 있고, docstring이 A-I 단계를 명시한다는 설명은 맞습니다. 실제 위치는 `papers.py:206-220`입니다.
- A URL 검증은 `papers.py:223-229`에 있습니다. 다만 구현은 `url.startswith(("http://", "https://"))`와 `urlparse(url).netloc` 검사입니다. "http(s) 스킴 + netloc"이라고 요약해도 큰 오류는 아니지만, 실제 구현은 정규 URL 파서의 scheme 검사가 아니라 문자열 prefix 검사입니다.
- B DOI pre-resolve는 `papers.py:231-236`, `_resolve_doi_redirect`는 `papers.py:157-168`입니다. `urlopen()`이 redirect를 따라가고 `resp.geturl()`을 반환합니다.
- C 파일명 생성은 `papers.py:238-243`입니다.
- E transformer 결과 다운로드는 `papers.py:251-259`이고, 호출 timeout은 35초입니다.
- F HTML fetch fallback은 `papers.py:261-293`이고, `_candidate_pdf_urls_from_page`는 `papers.py:171-203`입니다. `citation_pdf_url`, `og:pdf`, `.pdf`, `/pdf` anchor를 봅니다.
- G strict domain 검사는 `papers.py:295-314`이고, domain tuple은 11개입니다.
- H headless browser fallback은 `papers.py:316-350`입니다. `google-chrome`, `chromium`, `chromium-browser`를 찾고 `--virtual-time-budget=30000`, subprocess timeout 60초를 씁니다.
- I 품질 게이트는 `papers.py:352-389`입니다. 크기 < 1024B, PyPDF2 기반 2페이지 텍스트 추출, 봇/에러/약한 페이지 키워드 검사를 수행합니다.
- source URL sidecar 저장은 `papers.py:391-395`, `_write_source_sidecar`는 `papers.py:422-425`입니다.

### 수정이 필요한 사실 오류 또는 부정확한 표현

1. **bot keyword 개수는 14개가 아니라 13개입니다.**
   - Claude 검토: `docs/reviews/2026-05-21-url-handling-claude-review.md:29`
   - 실제 코드: `papers.py:358-364`
   - 실제 목록은 `verifying the device`, `verifying your browser`, `verify you are human`, `checking your browser`, `device verification`, `captcha`, `are you a robot`, `access denied`, `just a moment`, `ddos protection`, `cloudflare`, `attention required`, `unusual traffic`로 13개입니다.

2. **site transformer는 "9종 패턴"이라기보다 10개 regex entry / 9개 사이트 계열입니다.**
   - Claude 검토: `docs/reviews/2026-05-21-url-handling-claude-review.md:21`
   - 실제 코드: `papers.py:125-146`
   - `_SITE_PDF_TRANSFORMERS`에는 arXiv new-style, arXiv old-style, ar5iv, OpenReview, ACL, HuggingFace, PMLR, Semantic Scholar, Papers with Code, bioRxiv/medRxiv의 10개 regex entry가 있습니다. arXiv 두 entry를 한 사이트 계열로 묶으면 9개 계열이라는 표현은 가능하지만, "9종 패턴"은 부정확합니다.
   - 또한 Papers with Code transformer는 `papers.py:113-114`에서 빈 리스트를 반환하므로, 실제 PDF URL 후보를 생성하지 않습니다.

3. **strict domain 매칭은 정확한 도메인 매칭이 아니라 substring 매칭입니다.**
   - 실제 코드: `papers.py:310`
   - `any(d in effective_host for d in _STRICT_PDF_DOMAINS)`이므로 `not-arxiv.org` 같은 host도 이론상 매칭될 수 있습니다. 검토 본문의 "도메인 매칭"은 구현의 느슨함을 놓쳤습니다.

4. **headless browser fallback은 DOI/redirect 후의 `effective_url`이 아니라 원래 `url`을 인자로 넘깁니다.**
   - `effective_url` 갱신: `papers.py:231-236`, `papers.py:270-272`
   - browser command URL: `papers.py:329-340`
   - G 단계는 주석대로 effective host를 보지만, H 단계는 최종적으로 `url`을 출력 대상으로 씁니다. Claude 검토에는 이 차이가 빠져 있습니다.

5. **PRD 섹션 번호 인용이 어긋나 있습니다.**
   - Claude 검토는 "§2 비목표"라고 쓰지만, 현재 PRD에서 비목표는 `### 1.2`이고 `## 2`는 사용 시나리오입니다.
   - 관련 위치: `docs/specs/2026-05-21-mdflow-design.md:26-33`, `docs/specs/2026-05-21-mdflow-design.md:34`

6. **PaperFlow의 HTML fetch는 HTML임을 검증하지 않습니다.**
   - `_fetch_url_html`은 `papers.py:22-27`에서 응답 body를 UTF-8로 decode할 뿐 Content-Type을 확인하지 않습니다. 검토 본문의 "HTML fetch"는 의도상 맞지만, 구현상으로는 임의 응답을 HTML처럼 디코딩합니다.

## 2. 채택 권고의 완전성 검토

Claude 검토의 5개 채택 권고는 좋은 출발점이지만, mdflow v1 URL 설계로는 부족합니다.

### A. URL 검증: 채택, 단 PaperFlow 구현 그대로는 부족

필요합니다. PRD는 URL 입력을 `application/json {url}`과 MCP `convert_url`에 노출합니다(`docs/specs/2026-05-21-mdflow-design.md:162`, `docs/specs/2026-05-21-mdflow-design.md:219`). URL 검증이 없으면 잘못된 입력이 fetch 계층 예외로 흘러갑니다.

mdflow에는 PaperFlow식 `startswith()`보다 강한 규칙이 필요합니다.

- `urlparse`/`httpx.URL` 기준 scheme이 정확히 `http` 또는 `https`
- host 존재
- userinfo 포함 URL 처리 정책 결정. 최소한 로그에는 자격증명 redaction
- fragment 제거
- IDNA/punycode, 대소문자, trailing dot 정규화
- redirect 후 URL도 같은 검증 재적용

### B. DOI pre-resolve: v1 필수 채택에는 반대

PaperFlow에서는 DOI pre-resolve가 의미 있습니다. DOI URL을 실제 publisher URL로 바꿔야 site transformer와 strict domain 로직이 작동하기 때문입니다(`papers.py:231-249`, `papers.py:295-314`).

하지만 mdflow는 "URL이 반환한 문서를 변환"하는 범용 게이트웨이입니다. 일반 HTTP 클라이언트가 redirect를 따라가면 `https://doi.org/...`도 최종 URL의 응답 바이트를 받을 수 있습니다. 즉 mdflow v1에서 필요한 것은 DOI 전용 pre-resolve가 아니라 **일반 redirect 처리 + per-hop SSRF 차단 + `effective_url` 기록**입니다.

권고:
- `doi.org`만 특별 취급하는 B 단계는 v1 필수에서 제외합니다.
- 대신 fetch 정책에 "최대 N회 redirect를 따르고, 각 hop의 URL/IP를 검증하며, 최종 `effective_url`을 metadata에 기록"을 v1 필수로 넣습니다.
- DOI 편의 기능을 넣더라도 host가 정확히 `doi.org` 또는 `www.doi.org`인지 파서 기준으로 검사해야 합니다. PaperFlow처럼 `"doi.org/" in url` 방식(`papers.py:158`, `papers.py:233`)은 범용 서비스에는 너무 느슨합니다.

### SSRF 차단: v1로 끌어올리는 권고에 강하게 동의

PRD는 현재 `convert_url`을 제공하면서(`docs/specs/2026-05-21-mdflow-design.md:219`) SSRF 방지를 v1.1 검토/문서 위임으로 둡니다(`docs/specs/2026-05-21-mdflow-design.md:339-340`). v1이 무인증이라는 점(`docs/specs/2026-05-21-mdflow-design.md:336`)까지 고려하면 위험합니다.

v1 필수 최소 범위:

- `file://`, `ftp://`, `gopher://` 등 비 http(s) scheme 거부
- loopback, private, link-local, multicast, unspecified IP 거부
- IPv4/IPv6 literal 모두 처리
- `169.254.169.254` 등 cloud metadata 주소 명시 거부
- DNS 이름은 연결 직전 resolve 결과 전체를 검사
- redirect마다 재검사
- redirect 최대 횟수 제한
- 가능하면 config allowlist/blocklist 제공

단순 "사설 IP/loopback/file:// 거부"라고만 PRD에 쓰면 redirect-to-private, DNS rebinding, IPv6 literal, metadata IP가 빠지기 쉽습니다.

### I. 품질 게이트: 제한적으로 채택

봇/404 페이지를 Markdown으로 변환하는 것을 막는 목적은 맞습니다. 다만 PaperFlow의 품질 게이트는 "PDF 논문 import"에 맞춘 휴리스틱입니다.

mdflow에 그대로 가져오면 문제 되는 지점:

- `len(norm) < 220`이면 weak keyword 없이도 실패합니다(`papers.py:382-389`). 짧은 정상 문서, 영수증, 한 페이지 공지, 이미지 중심 PDF가 false negative가 될 수 있습니다.
- PyPDF2 2페이지 텍스트 추출(`papers.py:42-51`, `papers.py:356`)은 OCR 전 이미지 PDF를 빈 문서로 볼 수 있습니다. mdflow는 Marker/OCR 경로가 있으므로 fetch 단계에서 텍스트 길이만으로 PDF를 탈락시키면 안 됩니다.
- mdflow는 HTML, DOCX, PPTX, XLSX, HWP도 처리합니다. PDF 텍스트 기준 품질 게이트는 URL 입력 전체에 일반화되지 않습니다.

권고:
- v1에는 HTTP status, Content-Type, magic bytes, min/max bytes, 명백한 bot/error page keyword 정도만 fetch 품질 게이트로 둡니다.
- 텍스트 길이 기반 reject는 PDF 변환 후 converter metadata의 warning으로 낮추거나, content type별로 별도 적용합니다.
- 404/403은 키워드보다 HTTP status를 우선합니다. 단, custom 200 error page를 잡기 위한 보조 keyword는 유용합니다.

### source_url 캐시 메타 기록: 채택하되 캐시 모델을 먼저 정리해야 함

source provenance는 필요합니다. PaperFlow도 sidecar를 통해 source URL을 후속 조회에 활용합니다(`papers.py:391-395`, `papers.py:596-600`).

하지만 mdflow PRD의 캐시 키는 `sha256(input_bytes || canonical_options_json)`입니다(`docs/specs/2026-05-21-mdflow-design.md:164`, `docs/specs/2026-05-21-mdflow-design.md:256`). 이 구조에서 `meta.json`에 단일 `source_url`을 저장하면 다음 문제가 생깁니다.

- URL A와 URL B가 같은 바이트를 반환하면 같은 캐시 항목을 공유합니다.
- 첫 요청의 `source_url`이 캐시에 박히면 두 번째 URL 요청의 결과 metadata가 틀릴 수 있습니다.
- 반대로 매번 `source_url`을 덮어쓰면 기존 캐시 provenance가 흔들립니다.

권고:
- 변환 캐시와 fetch provenance를 분리합니다. 예: conversion cache는 bytes hash 기준, URL 요청 응답 metadata에는 request별 `source_url`, `effective_url`, `fetched_at`, `http_status`, `content_type`, `content_length`를 합성해서 반환.
- 또는 URL 입력만 cache key에 canonical URL/effective URL을 포함합니다. 이 경우 dedupe 이점은 줄지만 provenance는 단순해집니다.
- `source_url`만이 아니라 `effective_url`도 기록해야 합니다. PaperFlow sidecar는 원본 URL만 저장합니다(`papers.py:393`).

## 3. 거부 권고의 정확성 검토

### D/F/G 학술 사이트 transformer, meta tag 추출, strict 도메인: 대체로 거부가 맞음

D와 G는 명확히 mdflow에 부적합합니다.

- D는 arXiv, OpenReview, ACL, HuggingFace Papers, PMLR 등 학술 사이트별 URL 규칙입니다(`papers.py:125-146`). mdflow PRD는 PaperFlow와 달리 범용 변환 게이트웨이를 목표로 합니다(`docs/specs/2026-05-21-mdflow-design.md:13-15`).
- G는 학술 publisher domain을 hardcode합니다(`papers.py:297-310`). 범용 서비스의 라우팅 정책으로 넣으면 도메인별 제품 정책이 core에 섞입니다.

F는 조금 더 미묘합니다. `citation_pdf_url`은 학술 관습이지만, `.pdf` anchor나 `og:pdf` 발견은 일반 웹에도 있을 수 있습니다(`papers.py:178-194`). 그래도 v1 mdflow에는 넣지 않는 편이 맞습니다. 이유는 mdflow의 URL 의미가 "그 URL의 응답을 변환"이어야 하기 때문입니다. HTML 페이지 안의 다른 PDF를 찾아 변환하기 시작하면 `convert_url`의 계약이 "문서 발견기"로 확장됩니다. 이는 PaperFlow 같은 상위 워크플로우의 책임입니다.

권고 표현은 다음처럼 다듬는 것이 좋습니다.

- D/G: v1 명시적 비목표.
- F: v1 비목표. 단, 미래에 `discover=none|pdf` 같은 명시 옵션으로만 검토 가능. 기본 동작에는 넣지 않음.

### H Headless browser fallback: v1.1 연기 권고에 동의

PRD는 v1에서 임의 URL 크롤링/SPA 렌더링을 비목표로 둡니다(`docs/specs/2026-05-21-mdflow-design.md:32`) and headless Chrome 도입 여부를 추후 결정으로 둡니다(`docs/specs/2026-05-21-mdflow-design.md:339`). v1.1 연기가 맞습니다.

추가 근거:

- chromium 의존성뿐 아니라 sandbox, seccomp/container, CPU/RAM 제한, font 설치, timeout, concurrent browser process 제한이 필요합니다.
- headless rendering은 인증/쿠키/세션/지역화/anti-bot에 따라 결과가 불안정합니다.
- "정적 문서 변환 게이트웨이"와 "웹 렌더링 서비스"는 운영 리스크가 다릅니다.
- PaperFlow의 browser fallback도 `--no-sandbox`를 씁니다(`papers.py:333`). 범용 서버 v1 기본값으로는 부담이 큽니다.

## 4. 합리적 반대 의견

### 반대 의견 1: DOI pre-resolve를 채택하지 말고 generic redirect만 채택해야 함

근거:
- mdflow에는 PaperFlow의 transformer/strict domain 단계가 없습니다.
- 일반 HTTP fetch가 redirect를 따르면 DOI URL은 별도 pre-resolve 없이 처리됩니다.
- DOI 특화는 "학술 특화 거부" 원칙과도 긴장합니다.

실제 반영안:
- "DOI pre-resolve"를 PRD v1 단계에서 제거하고 "redirect follow with per-hop SSRF validation"으로 대체합니다.
- metadata에는 `source_url`과 `effective_url`을 모두 남깁니다.

### 반대 의견 2: 품질 게이트를 강한 reject로 두면 mdflow의 범용성이 깨질 수 있음

근거:
- PaperFlow의 `len(norm) < 220` reject는 논문 PDF import에는 합리적이지만, mdflow의 짧은 문서에는 과합니다(`papers.py:382-389`).
- mdflow는 PDF OCR/Marker 경로를 가질 예정입니다(`docs/specs/2026-05-21-mdflow-design.md:83`, `docs/specs/2026-05-21-mdflow-design.md:129`). fetch 직후 텍스트가 적다고 reject하면 OCR 기회를 잃습니다.

실제 반영안:
- fetch 단계에서는 명백한 error/bot 페이지만 reject.
- 애매한 품질 문제는 `metadata.warnings`로 보고.
- converter별 후처리 품질 평가는 별도 설계.

### 반대 의견 3: source_url을 캐시 메타에 단일 필드로 저장하면 provenance가 틀릴 수 있음

근거:
- PRD의 캐시 키가 바이트+옵션 기준입니다(`docs/specs/2026-05-21-mdflow-design.md:256`).
- source URL은 바이트의 속성이 아니라 요청의 속성입니다.

실제 반영안:
- `meta.json`의 변환 불변 metadata와 요청별 fetch metadata를 분리합니다.
- `/cache/{sha256}`가 어떤 provenance를 보여줄지 명시합니다. 무인증 v1이면 URL query token 노출도 고려해야 합니다.

## 5. 검토 본문이 놓친 사항

1. **PaperFlow에는 URL fetch 크기 제한이 없습니다.**
   - `_fetch_url_html`과 `_download_pdf` 모두 `resp.read()`로 전체 body를 메모리에 읽습니다(`papers.py:24-27`, `papers.py:60-62`).
   - mdflow PRD에는 입력 크기 `MDFLOW_MAX_INPUT_MB`가 있습니다(`docs/specs/2026-05-21-mdflow-design.md:331`). URL 다운로드에도 동일하거나 더 낮은 streaming limit을 명시해야 합니다.

2. **PaperFlow에는 SSRF 방어가 전혀 없습니다.**
   - A 단계는 scheme/host만 봅니다(`papers.py:223-229`).
   - DOI resolve, HTML fetch, PDF download, headless browser 모두 내부망 URL을 막지 않습니다.
   - Claude 검토가 "PaperFlow도 막혀있지 않음"이라고 쓴 것은 맞지만, redirect별 검증 필요성까지는 빠져 있습니다.

3. **PaperFlow의 strict domain 매칭은 보안/정확성 관점에서 느슨합니다.**
   - `d in effective_host` 방식입니다(`papers.py:310`). mdflow가 유사 정책을 만들 경우 suffix boundary 기반으로 해야 합니다. 다만 mdflow에는 이 정책 자체를 넣지 않는 편이 맞습니다.

4. **PaperFlow는 원본 URL만 sidecar에 저장하고 effective URL은 저장하지 않습니다.**
   - `_write_source_sidecar(pdf_name, url)` 호출이 원래 `url`을 넘깁니다(`papers.py:391-393`).
   - mdflow는 redirect 결과를 변환할 수 있으므로 `source_url`과 `effective_url`을 구분해야 합니다.

5. **PRD의 URL 입력 흐름은 fetch 단계 자체가 빠져 있습니다.**
   - §5는 `{url}` 수신을 언급한 뒤 바로 포맷 감지로 갑니다(`docs/specs/2026-05-21-mdflow-design.md:160-164`).
   - URL을 언제, 어떻게, 어떤 제한으로 다운로드하는지, filename/content-type/status를 어디에 담는지 명시가 없습니다.

6. **PRD의 에러 코드에 URL 계층 에러가 없습니다.**
   - 현재 에러 코드는 format/conversion/cache 중심입니다(`docs/specs/2026-05-21-mdflow-design.md:226-239`).
   - `URL_INVALID`, `URL_BLOCKED`, `URL_FETCH_FAILED`, `URL_TOO_LARGE`, `URL_REDIRECT_LIMIT`, `URL_UNSUPPORTED_SCHEME` 같은 구분이 필요합니다.

7. **URL metadata는 민감정보가 될 수 있습니다.**
   - v1은 무인증입니다(`docs/specs/2026-05-21-mdflow-design.md:336`).
   - URL query에는 signed URL, access token, presigned S3 parameter가 들어갈 수 있습니다. `source_url`을 cache metadata와 `/cache/{sha256}`에 그대로 노출할지 정책이 필요합니다.

8. **MCP stdio와 HTTP에서 URL fetch 권한의 의미가 다릅니다.**
   - PRD는 stdio `path`가 클라이언트 파일시스템 접근임을 설명하지만(`docs/specs/2026-05-21-mdflow-design.md:223`), `convert_url`은 실행 주체 서버의 네트워크 접근입니다.
   - 로컬 MCP stdio에서는 사용자의 로컬 네트워크 접근이 될 수 있고, HTTP 서버에서는 서버 내부망 접근이 됩니다. SSRF 정책과 문서화가 필요합니다.

9. **PaperFlow의 User-Agent 설정은 mdflow 검토에 빠져 있습니다.**
   - PaperFlow는 fetch마다 `"Mozilla/5.0 (PaperFlow URL Import)"`를 씁니다(`papers.py:22-24`, `papers.py:58-60`, `papers.py:161-162`).
   - mdflow도 기본 User-Agent와 override 허용 여부를 정해야 합니다. 무제한 사용자 지정 header/cookie는 v1에서 피하는 편이 안전합니다.

10. **HEAD/GET, Content-Disposition filename, extension hint 정책이 빠져 있습니다.**
    - mdflow의 format detect는 extension + magic bytes 합의입니다(`docs/specs/2026-05-21-mdflow-design.md:162-163`).
    - URL 입력에서는 로컬 filename이 없으므로 URL path, Content-Disposition, Content-Type, magic bytes의 우선순위를 정해야 합니다.

## 6. 추가 권고: mdflow v1 URL 처리에 반영할 사항

### v1 URL fetch 계약

PRD §5에 URL 입력 전처리 단계를 별도로 넣는 것이 좋습니다.

```text
URL input preprocessing:
1. Parse and canonicalize URL; allow only http/https.
2. Reject credentials in logs; redact sensitive query values in operational logs.
3. Resolve host and apply SSRF policy before connect.
4. GET with fixed User-Agent, connect/read timeout, max redirects, and per-hop SSRF checks.
5. Stream response to temp file with MDFLOW_MAX_INPUT_MB enforcement; do not resp.read() unbounded.
6. Require 2xx final status.
7. Capture response metadata: source_url, effective_url, status, content_type, content_length, content_disposition filename, fetched_at.
8. Detect format using magic bytes first, then Content-Type/filename as hints.
9. Apply narrow fetch quality gate for obvious bot/error pages.
10. Pass downloaded bytes/temp file into the existing ConversionService flow.
```

### v1 보안 기본값

- `MDFLOW_ALLOW_PRIVATE_URLS=false` 기본값.
- `MDFLOW_URL_MAX_REDIRECTS=5`.
- `MDFLOW_URL_CONNECT_TIMEOUT_S=10`, `MDFLOW_URL_READ_TIMEOUT_S=30` 같은 fetch 전용 timeout.
- `MDFLOW_MAX_URL_INPUT_MB`를 `MDFLOW_MAX_INPUT_MB`와 같거나 더 작게 둠.
- private URL 허용은 로컬 개발에서만 켤 수 있게 명시.

### v1 API/metadata 변경

`done.metadata` 또는 cache/request metadata에 다음을 권장합니다.

```json
{
  "input_kind": "url",
  "source_url": "https://doi.org/...",
  "effective_url": "https://publisher.example/file.pdf",
  "http_status": 200,
  "content_type": "application/pdf",
  "content_length": 1234567,
  "filename_hint": "file.pdf",
  "fetch_warnings": []
}
```

단, cache key가 bytes 기준이면 이 metadata는 캐시 불변값이 아니라 요청별 metadata로 합성해야 합니다.

### v1 에러 코드 추가

PRD §8.1에 URL 계층 에러를 추가하는 것을 권장합니다.

- `URL_INVALID`
- `URL_BLOCKED`
- `URL_FETCH_FAILED`
- `URL_TIMEOUT`
- `URL_TOO_LARGE`
- `URL_REDIRECT_LIMIT`
- `URL_NON_2XX`

기존 `TIMEOUT`과 합칠 수도 있지만, fetch timeout과 conversion timeout은 운영 대응이 다르므로 구분하는 편이 낫습니다.

### v1 테스트 추가

PRD §10에 URL fetch 테스트 축을 추가해야 합니다.

- invalid scheme, missing host
- localhost/private/link-local/metadata IP 차단
- public URL에서 private URL로 redirect 차단
- redirect limit 초과
- Content-Length 초과 및 chunked response 초과
- 404/403 status 처리
- Content-Type과 magic bytes 불일치
- 같은 bytes를 다른 URL에서 받을 때 provenance 처리
- short valid document가 품질 게이트에서 false positive로 탈락하지 않는지

## 7. Claude 검토에 대한 수정 제안 요약

1. PaperFlow 사실 정리에서 bot keyword를 13개로 수정합니다.
2. site transformer를 "10개 regex entry / 9개 사이트 계열"로 수정하고, Papers with Code는 빈 후보를 반환한다고 덧붙입니다.
3. PRD 비목표 섹션 번호를 `§1.2`로 수정합니다.
4. DOI pre-resolve는 v1 채택 필수에서 빼고, generic redirect handling으로 바꿉니다.
5. SSRF는 v1 필수로 올리되 redirect/DNS/IP literal/metadata IP까지 구체화합니다.
6. 품질 게이트는 PaperFlow식 텍스트 길이 reject를 그대로 채택하지 말고, 명백한 bot/error page만 좁게 적용합니다.
7. `source_url`은 `effective_url`과 함께 기록하되, bytes-hash cache와 충돌하지 않도록 요청별 provenance 모델을 명시합니다.
8. D/G는 명시적 비목표, F는 기본 비목표이되 향후 명시 옵션으로만 검토, H는 v1.1 이후로 유지합니다.

