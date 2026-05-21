# PaperFlow vs mdflow URL 처리 비교 검토 (Claude 작성)

**작성일**: 2026-05-21
**작성자**: Claude
**대상**: mdflow PRD (`docs/specs/2026-05-21-mdflow-design.md`) §2(비목표), §5(데이터 흐름), §6(API)
**참조 코드**: PaperFlow `viewer/app/services/papers.py` 특히 `import_url_as_paper` L206-397

## 0. 배경

- mdflow는 다양한 문서 포맷(PDF/DOCX/PPTX/HTML/HWP/XLSX 등)을 Markdown으로 변환하는 범용 게이트웨이. HTTP API(SSE 스트리밍) + MCP(stdio + Streamable HTTP) 제공.
- 현 PRD의 URL 입력 처리는 "v1 단순 GET 폴백만"으로 의도적으로 최소화 상태. PRD §2에서 "임의 URL 크롤링/SPA 렌더링은 비목표, URL 입력은 단순 GET 폴백만"으로 명시.
- PaperFlow는 PDF 논문 워크플로우 전용으로, URL → PDF 발견·다운로드 9단계 파이프라인을 보유.

## 1. PaperFlow 9단계 URL 파이프라인 (사실 정리)

`viewer/app/services/papers.py` `import_url_as_paper(url, title=None)` L206-397:

- **A. URL 검증** (L223-229): `http(s)` 스킴 + netloc 존재
- **B. DOI pre-resolve** (L231-236): `doi.org/...` → `urlopen()`로 실제 publisher URL 추적, `_resolve_doi_redirect` L157-168
- **C. PDF 파일명 생성** (L238-243): `web-{slug}-{ts}.pdf`로 `newones_dir`에 저장 예약
- **D. 사이트 transformer → PDF URL 후보** (L248-249, transformer 정의 L125-146): arXiv/ar5iv/OpenReview/ACL/HuggingFace/PMLR/Semantic Scholar/Papers with Code/bioRxiv·medRxiv 9종 패턴, **네트워크 0회**로 URL 변환
- **E. transformer 결과 다운로드** (L251-259): `_download_pdf` 35s timeout, 다중 후보 순차 시도
- **F. HTML fetch 폴백** (L261-293): HTML 본문 가져와서 `citation_pdf_url`/`og:pdf` meta + `.pdf`·`/pdf` anchor 정규식 추출(`_candidate_pdf_urls_from_page` L171-203), 리다이렉트 시 transformer 재적용
- **G. strict_pdf_required 검사** (L295-314): 11개 학술 도메인(arxiv/openreview/aclanthology/proceedings.mlr.press/biorxiv/medrxiv/acm/ieee/springer/nature/sciencedirect) 매칭 시 PDF 실패하면 종료
- **H. Headless 브라우저 print-to-pdf** (L316-350): `google-chrome/chromium --headless --print-to-pdf`, virtual-time-budget 30s, subprocess timeout 60s
- **I. 품질 게이트** (L352-389):
  - 크기 < 1024B → 실패
  - 본문 추출(`_extract_pdf_text_simple` 2페이지) 후 정규화
  - 봇 키워드 14개(captcha/cloudflare/verifying device 등) + 짧은 본문(< 600자) → 실패
  - 에러 키워드 11개(404/403 등) + 짧은 본문 → 실패
  - 약한 키워드 6개(privacy/terms/copyright 등) + 매우 짧은 본문(< 220자) 또는 3개 이상 매칭 → 실패
- **사이드카** (L392-395): `<filename>.url.txt`로 원본 URL 보존 (`_write_source_sidecar` L422-425)

## 2. 단계별 비교표

| 단계 | PaperFlow | mdflow PRD 현재 | 보편/특화 | mdflow 적용 권고 |
|---|---|---|---|---|
| A. URL 검증 | http(s) + netloc | 명시 없음 | 보편 | **채택** |
| B. DOI resolve | doi.org → publisher | 없음 | 보편(학술·일반) | **채택** |
| C. 파일명/경로 | `web-{slug}-{ts}.pdf` newones/ | 캐시 키(sha256)만 | 다름 | mdflow는 캐시 기반이라 직접 적용 X. 원본 URL은 캐시 메타로 |
| D. 사이트 transformer | 9개 학술 사이트 | 없음 | **학술 특화** | **거부** (포지셔닝 위반) |
| E. transformer URL 다운로드 | 다중 후보 + timeout | 단순 GET 1회 | 보편(다중 후보는 학술 특화) | 단일 GET + timeout만 채택 |
| F. HTML fetch 폴백 | meta tag + anchor 추출 | 없음 | 학술 특화(citation_pdf_url은 학술 관습) | **거부** (호출자/PaperFlow 책임) |
| G. strict_pdf 도메인 | 11개 도메인 | 없음 | 학술 특화 | **거부** |
| H. Headless 브라우저 | chromium print-to-pdf | LibreOffice 경로만 | 보편(SPA 흡수) | **v1.1 연기 권고** |
| I. 품질 게이트 | 봇/404/약한 페이지 키워드 | 없음 | 보편 | **채택**(키워드 셋 단순화) |
| 사이드카 | `.url.txt` | 없음 | 보편 | **채택**(캐시 메타 `source_url` 필드) |

## 3. mdflow 누락 갭 (PaperFlow에 있지만 mdflow에 없는, 보편적 가치 있는 항목)

| # | 갭 | 영향 | 권고 | 근거 |
|---|---|---|---|---|
| G1 | URL 검증 부재 | 잘못된 입력에 500 가능 | **반드시 추가**(v1) | PaperFlow A 단순 채택 |
| G2 | DOI 미해결 | doi.org URL → 변환 실패 | **추가**(v1) | PaperFlow B 단순 채택 |
| G3 | SSRF 차단 부재 | 사설망 노출, 메타데이터 서비스 노출 | **v1 추가** (현 PRD §13에서 v1.1로 연기됐으나 재검토 필요) | PaperFlow도 막혀있지 않음(공통 약점). mdflow가 v1에 박는 게 가치 |
| G4 | 품질 게이트 부재 | 봇/404 페이지를 변환 시도 → 의미없는 Markdown | **추가**(v1, 키워드 단순화) | PaperFlow I 채택(키워드 일부) |
| G5 | source_url 추적 부재 | 변환 결과에서 원본 URL 역추적 곤란 | **추가**(v1) | PaperFlow 사이드카를 캐시 메타로 보편화 |
| G6 | Headless browser 폴백 부재 | JS-렌더링·SPA → 빈 HTML | **v1.1 연기** | PRD §2 비목표("SPA 렌더링")와 일관. 의존성(`chromium`) 무거움 |

## 4. PaperFlow에 있지만 mdflow에 부적합한 항목 (가져오지 말 것)

- **D + F + G (학술 사이트 transformer + meta tag 추출 + strict 도메인)**: mdflow는 "범용 변환 게이트웨이"이므로 학술 도메인 9개 + strict 11개를 박는 건 단일 책임 원칙(SRP) 위반. PaperFlow를 mdflow의 클라이언트로 두는 게 자연스러움.

## 5. mdflow가 추가로 책임져야 하는 부분 (PaperFlow에는 없음)

| 항목 | 이유 |
|---|---|
| **포맷 다양성**: URL 응답이 PDF뿐 아니라 DOCX/PPTX/HTML/XLSX/HWP일 수 있음 | mdflow는 범용 변환. PRD §5.2의 Content-Type + magic bytes 라우팅이 URL 경로에도 적용됨을 명시 필요 |
| **SSRF 최소 차단**: PaperFlow는 약점 보유. mdflow가 v1에 박지 않으면 약점 상속 | mdflow는 신규 설계. v1에 사설 IP·loopback·`file://` 차단 권고 |

## 6. PRD 수정 제안 (요약)

§5(데이터 흐름)의 URL 입력 분기에 다음 단계 추가:

```text
1. URL 검증 (스킴 http(s), netloc 존재)
2. DOI pre-resolve (doi.org → 실제 publisher)
3. SSRF 차단 (사설 IP/loopback/file:// 거부)        ← PaperFlow 갭 보완
4. GET (timeout 30s) + Content-Type/magic bytes로 포맷 결정
5. 다운로드 품질 게이트 (크기·봇 키워드)            ← PaperFlow I 채택(단순화)
6. 캐시 메타에 source_url 기록                       ← PaperFlow 사이드카 보편화
7. (이하 기존 변환 흐름 §5 1~7단계)
```

§2(비목표) 유지:
- "학술 사이트별 PDF URL 발견(arXiv/OpenReview 등)은 호출자/PaperFlow 책임" 명시
- "SPA/JS-렌더링 페이지 변환은 v1 비목표" 명시
- "Headless browser 폴백은 v1.1 이후" 명시

§13(미해결)에 있는 SSRF는 v1로 끌어올림.

## 7. 결정 필요 사항 (사용자 또는 코덱스가 답변)

| Q | 권고 |
|---|---|
| Q1. 권고 5개(A/B/SSRF/품질 게이트/source_url) PRD §5 반영? | YES |
| Q2. Headless browser 폴백 v1 vs v1.1? | v1.1 |
| Q3. 학술 사이트 transformer 명시적 비목표로 박을까? | YES (현재는 암묵적) |
| Q4. SSRF 차단 v1.1 → v1으로 끌어올릴까? | YES |

## 8. 코덱스에게 묻는 것

1. 위 권고의 **정확성** — 사실 인용(L번호) 오류 없는지
2. 권고의 **완전성** — PaperFlow 코드 또는 mdflow PRD에서 놓친 사항이 있는지
3. **반대 의견** — 학술 transformer를 mdflow에 흡수해야 한다거나, Headless를 v1에 넣어야 한다거나, SSRF를 v1.1로 둬도 된다는 입장이 있다면 근거와 함께
4. **추가 권고** — mdflow의 URL 처리에 PaperFlow 비교를 떠나 추가로 반영할 가치가 있는 사항
