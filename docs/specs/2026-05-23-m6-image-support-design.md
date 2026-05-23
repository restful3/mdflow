# M6 설계 — 이미지 지원 (v2)

> mdflow Phase **M6**. 모든 9개 컨버터에 이미지 추출을 도입하고, `options.images = "none" | "embed" | "zip"`으로 출력 형식을 선택할 수 있게 한다.
> 기준 문서: `docs/specs/2026-05-21-mdflow-design.md` (PRD), `PROCESS_STATE.md`, `docs/reviews/2026-05-21-url-handling-final-agreement.md`.
> 사용자 인터뷰: 2026-05-23 brainstorming 세션 (스코프·출력 모드·HTTP/MCP/CLI 전송 방식·이미지 명명 모두 확정).

**작성일**: 2026-05-23
**대상 phase**: M6 (M0\~M5 + M2b `v0.7.0-m2b` 위)
**예상 태그**: `v2.0.0-m6` (sub-milestone들은 `v0.8.0-m6a` 등)

---

## 1. 목적 / 배경

현재 mdflow v1(M0\~M2b)은 모든 컨버터에서 이미지를 **항상 드롭**한다 (PRD §13 `preserve_images=false` 기본). 사용자 합의로 v2에서는 이미지를 1차 클래스 출력으로 다룬다.

핵심 가치 결정:

- **canonical-form invariant**: 컨버터는 mode를 모르고 항상 `figs/<sha>.<ext>` 상대경로로 markdown에 박는다. mode별 응답은 응답 합성 단계에서 view synthesis로 처리.
- **content-addressed dedup**: 이미지 파일명은 `sha256(image_bytes) + 원본확장자`. 컨버터·문서 경계를 넘어 자동 dedup.
- **canonical extraction + view synthesis** (사용자 합의안 A): 항상 이미지 추출 → 캐시에 figs/ 저장 → mode별 view 합성. 모드 전환 시 재변환 0.

핵심 비목표:

- HTML 외부 이미지 URL (`<img src="https://...">`) 의 자동 fetch — v1.1 옵션으로 보류
- 이미지 OCR / alt-text 생성 — v1.1+
- Headless browser / print-to-PDF (PaperFlow 방식) — v1 비목표 그대로

---

## 2. 범위

### 2.1 In scope (M6)

- `ConversionResult` 자료구조 확장 (`images: list[ImageAsset]`)
- 9개 컨버터 전부에 이미지 추출 + canonical markdown 박기
- 새 view synthesis package (`mdflow.views.{none,embed,zip}`)
- 캐시 디스크 레이아웃 확장 (figs/ + lazy bundle.zip)
- `options.images = "none" | "embed" | "zip"` 옵션 (default `"none"`)
- HTTP `done` 이벤트에 `bundle_url` 신규 + `GET /cache/<sha>/bundle.zip` 신규
- MCP tool result에 `bundle_b64` / `bundle_url` 신규 (transport별 분기)
- CLI `--images` flag + `-o` 타입 분기 매트릭스 + `--force` flag

### 2.2 Out of scope (M6)

- HTML 외부 URL 이미지 fetch — `<img src="data:...">` (data URI) 만 추출, 외부 URL은 ref 그대로 보존
- 이미지 형식 변환 (PNG↔JPEG 강제 변환 등) — 원본 포맷 preserve
- 별도 이미지 OCR 단계 — Marker 내장 OCR만 사용
- v1.1+로 미루는 후속:
  - `options.html_fetch_images=true` (외부 이미지 fetch + SSRF 검증)
  - `options.image_format=preserve|jpeg|png` (강제 변환)
  - 이미지 alt-text auto-generation
  - 작은 이미지 필터 (`min_image_bytes`)

---

## 3. 합의된 핵심 결정 (사용자 인터뷰 결과)

| # | 결정 영역 | 선택 | 비고 |
|---|---|---|---|
| D1 | 스코프 | 9 컨버터 동시 전면 개편 | 사용자 명시: "전 컨버터 동시 전면 개편" |
| D2 | 출력 모드 | `options.images = "embed" \| "zip" \| "none"`, default `"none"` | 명시적, transport 불변 |
| D3 | HTTP zip 전송 | SSE `done` 이벤트에 download URL + 기존 `/cache/<sha>` 확장 | 캐시 아키텍처와 자연스러운 통합 |
| D4 | MCP zip 전송 | tool result에 `bundle_b64` + `bundle_url` 둘 다 | HTTP-mount는 URL 유효, stdio는 base64만 의미 |
| D5 | CLI zip 전송 | `-o` 대상 타입 분기 (.zip / 디렉토리 / .md), `--force`로 비빈-디렉토리 덮어쓰기 | 단일 파일은 Unix 관례대로 항상 덮어쓰기 |
| D6 | 이미지 명명 | `figs/<sha256(image_bytes)>.<원본확장자>`, 문서 간 자동 dedup, 포맷 preserve | PaperFlow의 sha256 명명 + format 자유도 |
| D7 | HTML 외부 URL | data URI는 figs/로 추출, 외부 `https://` URL은 markdown ref 그대로 (fetch 안 함) | v1.1 후속 옵션 가능성 |
| D8 | 이미지 0개 + mode=zip | bundle 생략, markdown만 반환 (`bundle_url=null, bundle_b64=null`) | 직관적 표면 |
| D9 | 캐시 아키텍처 | Canonical extraction + view synthesis (옵션 A) | mode 전환 시 재변환 0 |

---

## 4. 아키텍처 & 자료구조

### 4.1 핵심 invariant

1. **컨버터 책임**: `(canonical_markdown, metadata, list[ImageAsset])` 반환. canonical markdown은 `figs/<sha>.<ext>` 상대경로 ref만 사용.
2. **mode는 컨버터에 보이지 않음**. 컨버터는 항상 이미지를 추출.
3. **응답 합성**: `views/{none,embed,zip}.synthesize()`가 canonical entry를 mode-specific 응답으로 변환.
4. **캐시 key는 이미지 옵션과 독립**. mode 전환은 재변환 0ms.

### 4.2 새 dataclass

```python
# src/mdflow/converters/base.py

@dataclass(frozen=True)
class ImageAsset:
    name: str          # e.g., "abc...def.png" (sha256(bytes) + ext)
    data: bytes        # raw image bytes (원본 포맷 preserve)
    content_type: str  # "image/png", "image/jpeg", "image/svg+xml", ...

@dataclass
class ConversionResult:
    markdown: str                                    # canonical form (figs/ refs)
    metadata: dict[str, Any]
    images: list[ImageAsset] = field(default_factory=list)
    # NOTE: `assets: list[str]` 필드는 M6a에서 제거.
    # 응답 schema에는 v2.0 호환 shim으로 `"assets": []` 잔존.
```

### 4.3 새 모듈 / 파일

| 위치 | 종류 | 책임 |
|---|---|---|
| `src/mdflow/converters/_image_util.py` | NEW | `sha_filename(data, content_type)`, `make_image_asset(data, content_type, alt?)`, `canonical_ref(asset, alt)`, `content_type_to_ext()` |
| `src/mdflow/converters/base.py` | EDIT | `ImageAsset` 도입, `ConversionResult` 확장, `assets` 필드 제거 |
| `src/mdflow/converters/{docx,pptx,xlsx,html,hwp,office,pdf,marker}.py` | EDIT | 이미지 추출 + canonical refs + `images` 채우기 |
| `src/mdflow/converters/text.py` | NO CHANGE | passthrough는 이미지 없음 |
| `src/mdflow/core/cache.py` | EDIT | `write_canonical/read_canonical/build_bundle/delete` 확장 |
| `src/mdflow/views/__init__.py` | NEW | package 마커 |
| `src/mdflow/views/none.py` | NEW | `synthesize(canonical_markdown) -> str` |
| `src/mdflow/views/embed.py` | NEW | `synthesize(canonical_markdown, figs_dir) -> str` |
| `src/mdflow/views/zip.py` | NEW | `synthesize(canonical_markdown, cache_dir, sha) -> (str, Path \| None)` |
| `src/mdflow/core/service.py` | EDIT | `ConversionService.convert()` 반환은 canonical, view 합성은 transport handler가 호출 |
| `src/mdflow/api/admin.py` | EDIT | `GET /cache/<sha>/bundle.zip` 신규 라우트 |
| `src/mdflow/api/convert.py` | EDIT | `done` 이벤트에 `bundle_url` 합성, options 검증 |
| `src/mdflow/mcp/tools.py` | EDIT | tool result에 `bundle_b64`/`bundle_url` 합성 |
| `src/mdflow/cli.py` | EDIT | `--images` flag, `-o` 타입 분기, `--force` |

### 4.4 캐시 디스크 레이아웃

```
~/.cache/mdflow/
  <sha256>/
    result.md         # canonical markdown (figs/ refs 그대로)
    meta.json         # converter metadata (image_count, image_drop_count 포함)
    figs/             # 이미지 0개면 디렉토리 자체 미생성
      <img_sha1>.png
      <img_sha2>.jpg
      <img_sha3>.svg
    bundle.zip        # lazy build, mode=zip 첫 요청 시 생성
```

### 4.5 캐시 키 정책

- `compute_cache_key(content_bytes, options, detected_format)`에서 `options`의 `"images"` 키는 **무시**한다.
- 정규화: `options_minus_images = {k: v for k, v in options.items() if k != "images"}` 후 기존 알고리즘 (JSON sorted_keys hash).
- 결과: M0\~M5의 기존 캐시 entry는 그대로 hit. 마이그레이션 스크립트 불필요.

---

## 5. 데이터 흐름

### 5.1 한 호출 흐름 (HTTP `POST /convert` 기준)

```
[1] options.images 검증 (= "none" | "embed" | "zip" | absent)
       │ invalid → pre-stream 400 (M1a Codex 권고 1 패턴)
       ↓
[2] cache_key = sha256(content_bytes + options_minus_images + detected_format)
       ↓
[3] cache.read_canonical(sha) hit? ─── 예 ──→ event: cached → view 합성 → event: done
       ↓ 아니오
[4] event: started → 컨버터 변환 (스레드풀, M1a event pump)
       │ canonical_markdown, metadata, images = converter.convert(...)
       ↓
[5] cache.write_canonical(sha, markdown, images, metadata)
       │ figs/ 디렉토리에 ImageAsset 들을 sha 명명으로 atomic write
       ↓
[6] view 합성:
       │ mode=none  → views.none.synthesize(canonical_md)
       │ mode=embed → views.embed.synthesize(canonical_md, entry/figs/)
       │ mode=zip + len(images) > 0
       │            → views.zip.synthesize(canonical_md, root, sha)
       │            → cache.build_bundle(sha) lazy 호출
       │            → bundle_url 생성
       │ mode=zip + len(images) == 0 → mode=none 흐름과 동일
       ↓
[7] event: done with {markdown, metadata, sha256, bundle_url, assets: []}
```

### 5.2 Canonical markdown 사양

- 단독 줄 image: `![alt text](figs/<sha>.<ext>)` (alt가 있으면 보존, 없으면 빈 alt)
- 인라인 image: `텍스트 ![alt](figs/<sha>.<ext>) 텍스트`
- 모든 ref는 상대경로 `figs/`로 시작
- ext는 content_type 기반: `png/jpg/jpeg/gif/svg/webp/bmp/tiff` 등
- 두 ref가 같은 sha를 가리키면 자동 dedup (디스크는 1번 저장, markdown은 N번 ref)

### 5.3 View synthesis 규칙

#### `views.none.synthesize(canonical_md) -> str`

```python
# 0) 코드 블록(``` ... ```) 내부 영역은 protect — 치환 제외 (fence detect 후 split)
# 1) 단독 줄 image: ^!\[(.*?)\]\(figs/.+?\)$
#    - alt 있음 → alt 텍스트만 한 줄
#    - alt 없음 → 줄 제거
# 2) 인라인 image: 텍스트 중 !\[(.*?)\]\(figs/.+?\)
#    - alt 있음 → alt로 치환
#    - alt 없음 → 빈 문자열로 치환
# 3) 연속 빈 줄 정리 (3개+ → 2개로)
```

#### `views.embed.synthesize(canonical_md, figs_dir) -> str`

```python
# 각 figs/<sha>.<ext> ref:
#   path = figs_dir / "<sha>.<ext>"
#   data = path.read_bytes()
#   b64 = base64.b64encode(data).decode("ascii")
#   치환: ![alt](data:<content_type>;base64,<b64>)
# figs/ 파일 missing → MdflowError(CACHE_IO_ERROR)
```

#### `views.zip.synthesize(canonical_md, cache_root, sha) -> tuple[str, Path | None]`

```python
# images=0 (canonical에 figs/ ref 없음) → (canonical_md, None) — bundle 미생성
# images>=1:
#   bundle_path = cache.build_bundle(sha)  # lazy, atomic
#   return (canonical_md, bundle_path)
#
# bundle.zip 내부 구조:
#   paper.md      # canonical markdown
#   figs/
#     <sha>.png
#     <sha>.jpg
#     ...
#   meta.json     # converter metadata
```

### 5.4 `cache.build_bundle` 동작

- 입력: sha
- 호출 시 entry_dir/bundle.zip이 이미 존재하면 그대로 반환 (cache hit on bundle)
- 없으면:
  - `.tmp-bundle-<rand>.zip` tmp file 생성
  - zipfile에 `paper.md` + `figs/*` + `meta.json` 기록 (DEFLATE 또는 STORED)
  - `os.replace(tmp, entry_dir/bundle.zip)` atomic
  - 동시 요청 race: first-writer-wins, outcome 무해
- OSError → `MdflowError(CACHE_IO_ERROR)` + tmp 정리

---

## 6. API 표면

### 6.1 HTTP

#### `POST /convert`

- 옵션 추가: multipart `options` 필드 또는 JSON `options.images` 키
- 검증: `images ∈ {"none","embed","zip"}` 또는 absent. invalid → pre-stream **400** `{detail: "invalid options.images value"}`.
- `done` 이벤트 스키마 (변경):

```json
{
  "markdown": "...",                              // mode별 view 합성 결과
  "metadata": {
    "converter": "...",
    "format": "...",
    "image_count": 7,                             // NEW: canonical markdown 의 figs/ ref 개수 (dedup된 unique sha 수)
    "image_drop_count": 0,                        // NEW: 추출 실패 또는 컨버터 한계로 드롭한 이미지 개수
    "image_bytes_total": 1234567                  // NEW: figs/ 디스크 디렉토리에 저장된 unique image bytes 합
  },
  "sha256": "...",                                // 기존
  "bundle_url": "/cache/<sha>/bundle.zip" | null, // NEW (mode=zip+image≥1만 not-null)
  "assets": []                                    // 호환 shim (v2.1에서 제거)
}
```

#### `GET /cache/<sha256>/bundle.zip`

- 200 + `application/zip` + `Content-Disposition: attachment; filename="<sha>.zip"` + stream
- 404 cache miss (entry_dir 없음)
- 404 cache hit but no bundle (images=0, body: `"no bundle: 0 images"`)
- 503 corrupt cache (read 중 OSError → `MdflowError(CACHE_IO_ERROR)`)
- sha 검증: 64 hex char regex, 아니면 400

#### `DELETE /cache/<sha>`

- 기존 동작 + figs/ + bundle.zip 까지 정리 (entry_dir 통째 삭제로 이미 처리됨)

#### `POST /cache/purge`

- 기존 동작 그대로 (entry_dir 통째 삭제)

#### `GET /capabilities`

- 추가 필드:

```json
{
  "image_modes": ["none", "embed", "zip"],
  "image_dedup": "sha256-content"
}
```

### 6.2 MCP

#### tool input schema 확장

`convert_file` / `convert_url`의 `options` 객체:

```json
{
  "type": "object",
  "properties": {
    "images": {"type": "string", "enum": ["none", "embed", "zip"]},
    ...
  },
  "additionalProperties": false
}
```

#### tool result 확장

`convert_file` / `convert_url` / `get_cached` (캐시 hit 시):

```json
{
  "markdown": "...",                              // mode별 view
  "metadata": {...},
  "sha256": "...",
  "bundle_b64": null | "<base64-encoded zip>",   // NEW
  "bundle_url": null | "/cache/<sha>/bundle.zip" // NEW
}
```

- `bundle_b64` 채움 조건: mode=zip AND len(images)≥1. transport 무관 (stdio + HTTP 모두 채움).
- `bundle_url` 채움 조건: 위 + HTTP-mount일 때만. stdio는 base URL을 모르므로 항상 null.
- HTTP-mount에서 base URL은 FastAPI `Request.base_url`에서 추출 (Starlette 표준). reverse-proxy 환경에서는 운영자가 uvicorn `--proxy-headers` 와 `--forwarded-allow-ips`를 설정하면 자동 인식. 그 외 명시적 host override는 v1.1 후속.

`list_formats` 변경 없음.

#### MCP 권한 표면 분기 유지

- stdio: `allow_path=True`, `allow_gpu=True` (현재)
- HTTP-mount: `allow_path=False`, `allow_gpu=False` (M4 + M2b Codex blocker fix 그대로)
- `bundle_url` 채우는 로직만 transport 분기 추가

### 6.3 CLI

#### 새 flag

```
mdflow convert [FILE] [OPTIONS]

기존:
  --url TEXT
  -o, --output PATH

NEW:
  --images [none|embed|zip]   default: none
  --force                      비빈 디렉토리 덮어쓰기 허용 (-o가 디렉토리일 때만 의미 있음)
```

#### `-o` 분기 매트릭스

| `-o` 인자 | mode | 동작 |
|---|---|---|
| 없음 | none | stdout markdown |
| 없음 | embed | stdout markdown (data URI inline) |
| 없음 | zip + image=0 | stdout markdown + stderr "no images" 메모 |
| 없음 | zip + image≥1 | **exit 2** + stderr "use -o for images=zip" |
| `file.md` | none/embed | 파일 write (덮어쓰기) |
| `file.md` + zip | **exit 2** + stderr "use .zip or directory" |
| `file.zip` | zip + image≥1 | bundle.zip 복사 |
| `file.zip` + zip + image=0 | **exit 2** + stderr "no images" |
| `file.zip` + none/embed | **exit 2** + stderr "use .md for none/embed" |
| `dir/` (없거나 비어있음) | any | dir 생성 + dir/paper.md + (mode=zip이면) dir/figs/ 풀기 |
| `dir/` (비어있지 않음) | any + `--force` 없음 | **exit 2** + stderr "directory not empty; use --force" |
| `dir/` (비어있지 않음) | any + `--force=true` | 덮어쓰기 |

stdout/파일/디렉토리 모두 단일 파일 덮어쓰기는 Unix 관례대로 force 없이 허용.

#### `mdflow serve` 변경 없음

---

## 7. 컨버터별 이미지 API 매핑

| # | 컨버터 | 이미지 API | 비고 |
|---|---|---|---|
| 1 | `text-passthrough` | N/A | 텍스트만 |
| 2 | `docx-mammoth` | `convert_image=mammoth.images.img_element(handler)` callback. handler가 `image.open()`으로 bytes 얻고 `ImageAsset` list 누적, return `{"src": "figs/<sha>.<ext>"}`. alt는 `image.alt_text` 보존 | mammoth 표준 패턴 |
| 3 | `pptx-python-pptx` | 각 slide → shape iterate, `shape.shape_type == PP_SHAPE_TYPE.PICTURE` 또는 `shape.has_image` → `shape.image.blob + shape.image.ext`. canonical ref는 슬라이드 텍스트 블록 사이 한 줄로 삽입. alt: `shape.element.xpath('.//a:blip/@title')` best-effort | shape API |
| 4 | `xlsx-openpyxl` | `worksheet._images` iterate → openpyxl `Image` 객체. `image._data()` (private API) 또는 `image.ref` 파일 경로 → bytes. 표 위에 한 줄 ref | best-effort, xlsx는 이미지 흔치 않음 |
| 5 | `html-trafilatura` | `include_images=True` 설정. trafilatura가 `![](src_url)` 출력. 후처리 단계에서 `data:` URI 추출 → figs/ + canonical ref, 외부 URL은 ref 보존 | data URI만 추출 (D7) |
| 6 | `hwp-pyhwp` | pyhwp single-file transform이 bindata 미추출. 현재 그대로 드롭. metadata에 `image_drop_count` 만 카운트 (heuristic: HTML 내 `<img>` 태그 수) | v1 한계 그대로 |
| 7 | `office-libreoffice` (doc/ppt) | soffice→PDF → PdfConverter 합성. **PDF 컨버터의 이미지 추출 흐름이 자동으로 작동** | 무료 통합 |
| 8 | `pdf-pymupdf4llm` | `pymupdf4llm.to_markdown(doc, write_images=True, image_path=str(tmp), image_format="png")` → tmp dir에 PNG들 → 읽어서 sha 명명으로 ImageAsset 생성 + canonical refs는 to_markdown 출력의 경로 부분만 치환 | `image_size_limit`로 작은 이미지 필터 가능(v1.1) |
| 9 | `pdf-marker` (GPU) | `text, _, _images = _text_from_rendered(rendered)` 의 `_images` 활용. PIL Image dict (key=marker의 sha-jpg). bytes로 직렬화 + sha rename + canonical refs는 marker가 markdown에 박은 경로 치환 | PaperFlow 패턴 그대로 |

### 7.1 공통 헬퍼 — `_image_util.py`

```python
EXT_BY_CT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}

def sha_filename(data: bytes, content_type: str) -> str:
    ext = EXT_BY_CT.get(content_type, "bin")
    return f"{hashlib.sha256(data).hexdigest()}.{ext}"

def make_image_asset(data: bytes, content_type: str) -> ImageAsset:
    return ImageAsset(
        name=sha_filename(data, content_type),
        data=data,
        content_type=content_type,
    )

def canonical_ref(asset: ImageAsset, alt: str = "") -> str:
    return f"![{alt}](figs/{asset.name})"

def content_type_to_ext(ct: str) -> str:
    return EXT_BY_CT.get(ct, "bin")
```

---

## 8. 에러 처리

신규 ErrorCode는 추가하지 않는다. 기존 15개로 충분.

| 시나리오 | 처리 | 표면화 |
|---|---|---|
| 한 이미지 추출 실패 (전체는 OK) | WARNING 로그 + `metadata.image_drop_count++` + 해당 ref만 canonical에 미박음 | 에러 아님 |
| 컨버터 한계로 이미지 원천 드롭 (hwp) | 위와 동일 | 에러 아님 |
| 컨버터 전체 실패 | 기존 `CONVERSION_FAILED` (retryable=true) | 기존 흐름 |
| `cache.write_canonical` 디스크 쓰기 실패 | `MdflowError(CACHE_IO_ERROR)` + tmp 정리 | HTTP 503 / MCP ToolError / CLI exit 1 |
| `cache.build_bundle` zip 빌드 실패 | 동일 | 동일 |
| `views/embed.synthesize`에서 figs/ missing (캐시 corrupt) | `CACHE_IO_ERROR` | 동일 |
| `options.images` invalid 값 | pre-stream 검증 → HTTP 400 / MCP ToolError / CLI typer choice exit 2 | 표준 검증 |
| `GET /cache/<sha>/bundle.zip` cache miss | 404 + "cache miss" | 기존 admin 패턴 |
| `GET /cache/<sha>/bundle.zip` no bundle (images=0) | 404 + "no bundle: 0 images" | 명시적 |
| mode=zip + 컨버터가 이미지 드롭 (hwp) | image=0 케이스와 동일 — bundle 없이 markdown만 + metadata.image_drop_count | 클라이언트 메타로 알 수 있음 |

SSE error 이벤트 패턴 (§6 M1a) 그대로 유지.

---

## 9. 테스트 전략

### 9.1 새 fixture (`tests/fixtures/images.py`)

| 함수 | 출력 |
|---|---|
| `make_docx_with_image() -> bytes` | inline image 포함 docx |
| `make_pptx_with_image() -> bytes` | shape.image 추출 가능 pptx |
| `make_xlsx_with_image() -> bytes` | worksheet._images 포함 xlsx |
| `make_html_with_data_uri() -> str` | `<img src="data:image/png;base64,...">` 포함 HTML |
| `make_html_with_external_url() -> str` | `<img src="https://example.com/x.png">` 포함 HTML (fetch 안 함 검증) |
| `make_pdf_with_image() -> bytes` | PyMuPDF로 이미지 박은 PDF |

각 fixture는 결정적 출력 (같은 시드 → 같은 sha).

### 9.2 컨버터별 unit tests

`tests/converters/test_<format>_image.py` 패턴. 각 컨버터 5 케이스:

1. 추출 성공 → `images` 리스트 채워짐 + canonical markdown에 ref
2. 이미지 없음 → `images=[]`, markdown에 ref 없음
3. dedup → 같은 이미지 2회 등장 → `images` unique 1개, markdown ref 2개
4. 부분 실패 → 손상된 이미지 → 드롭 + `image_drop_count++`, 전체 변환 성공
5. alt text 보존 (mammoth, html 만) → `![alt text](figs/...)`

대상: docx, pptx, xlsx, html, pdf-pymupdf4llm, pdf-marker (6 컨버터 × 5 = ~30 tests).
text/hwp/office는 케이스 1·2만 (~6 tests).

### 9.3 View synthesis tests (`tests/views/test_synthesis.py`)

- `none`: 단독 줄 제거, alt 치환, inline 치환, 연속 빈 줄 정리 (5 케이스)
- `embed`: 각 ext의 data URI 매핑, figs/ missing → CACHE_IO_ERROR (6 케이스)
- `zip`: 내부 구조 검증, images=0 → bundle 미생성 (4 케이스)
- canonical → view → re-parse 라운드트립 invariant (1 케이스)

### 9.4 Cache layer tests (`tests/test_cache_canonical.py`)

- `write_canonical` atomic (mkdtemp + os.replace), tmp 정리, OSError → CACHE_IO_ERROR
- figs/ dedup — 같은 sha 두 ImageAsset → disk write 1번
- `read_canonical` round-trip
- `build_bundle` lazy 첫 호출 / 두 번째 호출 cache hit
- `build_bundle` 동시 호출 first-writer-wins
- `delete(sha)` → figs/ + bundle.zip 청소
- `purge()` → 그대로

### 9.5 API surface tests

#### HTTP
- `POST /convert` + options=multipart/JSON
- `done.bundle_url` mode별 (none/embed → null, zip+image≥1 → "/cache/.../bundle.zip")
- 모드 전환 e2e: none → embed → zip 순서, 재변환 0
- `GET /cache/<sha>/bundle.zip`: 200 / 404 (miss) / 404 (no images) / 503 (corrupt)
- `DELETE /cache/<sha>` → GET bundle.zip → 404
- `GET /capabilities` → image_modes 노출

#### MCP
- tool result `bundle_b64` / `bundle_url` 필드 (stdio vs HTTP-mount 분기)
- `tools/list` inputSchema에 options.images enum
- `get_cached` 도 합성

#### CLI
- `-o` 분기 매트릭스 9 케이스
- `--force`: 비빈 디렉토리 + force=false → exit 2, force=true → 덮어쓰기
- 단일 파일은 force 없이도 덮어쓰기

### 9.6 통합 e2e (`tests/test_m6_smoke.py`)

1. HTTP + image-bearing PDF + images=zip → bundle_url → GET → unzip → 검증
2. MCP stdio + same PDF + images=zip → bundle_b64 → decode → 검증
3. CLI `mdflow convert in.pdf --images zip -o /tmp/out/` → out/paper.md + out/figs/
4. 같은 sha 파일 mode 전환 (none→embed→zip) → markdown 의미 동등 + hit_count 증가

### 9.7 기존 304 tests 호환성

- default mode=none → markdown 출력은 기존과 동일 (canonical refs 제거 후) → 골든 그대로 통과
- `r["assets"] == []` assertion이 있으면 그대로 통과 (호환 shim)
- 캐시 sha 키 unchanged → 기존 캐시 hit 동작

### 9.8 예상 신규 tests

| 영역 | 추가 tests |
|---|---|
| converter image extract | ~30 |
| view synthesis | ~15 |
| cache canonical | ~12 |
| HTTP options + bundle endpoint | ~10 |
| MCP fields + 분기 | ~8 |
| CLI -o matrix + --force | ~10 |
| M6 smoke | ~5 |
| **총** | **~90** |

기존 304 + ~90 ≈ **~390 tests** 예상.

---

## 10. 마이그레이션 & sub-milestone 분할

### 10.1 Sub-milestone 6개

| Sub | 범위 | 산출물 | Codex 리뷰 |
|---|---|---|---|
| **M6a** | 자료구조·`_image_util`·canonical form 사양·view synthesis 3 module·cache `write/read_canonical`·`build_bundle` lazy. **API 변경 없음**, 컨버터 변경 전이라 항상 images=[] | 기반 인프라. 기존 304 tests + ~30 신규 tests 통과 | **권장**: 단독 묶음 리뷰 (다른 sub의 기반) |
| **M6b** | PDF 둘 (`pdf-pymupdf4llm`, `pdf-marker`) 이미지 추출 활성화 | image-bearing PDF fixture + tests. canonical refs 디스크 dedup | 묶음 가능 (M6c와) |
| **M6c** | Office 셋 (`docx-mammoth`, `pptx`, `xlsx`) | per-converter image tests + golden 확장 (M1b 패턴) | 위 |
| **M6d** | `html-trafilatura` (data URI만), `hwp-pyhwp` (image_drop_count metadata만), `office-libreoffice` (PDF 단계 자동 동작 검증) | 잔여 컨버터 | 위 |
| **M6e** | API surface 확장: HTTP options + bundle endpoint + done.bundle_url. MCP tool result. CLI --images + -o matrix + --force | 4 transport 라이브 e2e 가능 | **권장**: API surface 단독 묶음 (권한 표면 변경 큼) |
| **M6f** | 통합 e2e + PRD 패치 + PROCESS_STATE 갱신 + 최종 Codex 묶음 리뷰 + 태그 `v2.0.0-m6` | 채택 완료 | **필수**: 최종 통합 |

각 sub는 별도 implementation plan 작성 (M1a/M2b 패턴).

### 10.2 호환성 매트릭스

| 영역 | 변화 | breaking? |
|---|---|---|
| `options.images` 미지정 호출 | default `"none"` → mode=none view → image refs 제거된 markdown | non-breaking |
| `ConversionResult.markdown` 출력 (이미지 없는 입력) | 글자 단위 동일 | non-breaking |
| `done` 이벤트 `bundle_url` 신규 | 항상 키 존재 (null 가능) | additive |
| MCP tool result `bundle_b64`/`bundle_url` 신규 | 항상 키 존재 (null 가능) | additive |
| `ConversionResult.assets` 필드 제거 | dataclass에서 즉시 삭제. 응답 schema에는 `"assets": []` shim 유지 (v2.1에서 제거) | non-breaking (응답 기준) |
| 캐시 디스크 레이아웃 figs/ 추가 | 기존 entry에 figs/ 없으면 read_canonical이 images=[]로 해석 | forward-compatible |
| 캐시 sha 키 | `options.images`를 제외하고 계산 → 기존 알고리즘과 동일 결과 | non-breaking |

### 10.3 PRD 패치 항목 (M6f에서 일괄)

`docs/specs/2026-05-21-mdflow-design.md`:

- §1.3 v1 비목표: "HTML 외부 이미지 URL fetch"를 v1.1로 명시
- §3 architecture 다이어그램에 `figs/` 박스 추가
- §6 옵션 키: `preserve_images=false` → **`images=none|embed|zip` 신규**
- §6 응답 스키마: `bundle_url`, `bundle_b64` 신규
- §8 에러 처리: 변경 없음 (5.1 결정)
- §10 테스트 전략: M6 추가 ~90 tests
- §13 미해결 항목 "이미지/asset 반환" 제거 (해결됨)
- §14 마일스톤: M6 sub 6개 추가

### 10.4 PROCESS_STATE.md 갱신 (M6 각 sub 시점)

§0.1 자율 갱신 트리거 그대로:
- sub 시작/종료
- implementation plan 작성/수정
- Codex 리뷰 송부/수신
- 주요 commit 직후
- handoff 직전

§4 로드맵 표에 Phase M6 추가.

---

## 11. 위험 & 미해결

### 11.1 위험 매트릭스

| 위험 | 영향 | 완화 |
|---|---|---|
| 디스크 사용 폭증 (모든 변환에 figs/ 강제 저장) | 중 | mode=none이 default — 응답엔 빠짐, figs/는 캐시에만. `/cache/purge`로 청소 가능 |
| embed mode 응답 폭증 (LLM 컨텍스트) | 중 | capabilities + 운영 doc에 명시. 대용량은 zip 권장 |
| GPU 변환 시간 증가 (Marker 이미지 추출 활성화) | 중 | M6b 라이브 e2e에서 cold/warm 시간 비교 (현재 cold 4s 기준). 차이 큼 → v1.1 sub-option 검토 |
| 이미지 sha 충돌 (다른 이미지 같은 sha) | 무시 | sha256 — 사실상 0 |
| HTML data URI 디코딩 부담 | 저 | trafilatura 출력 후 정규식 detect + 한 번 decode |
| `--force` 미지정 시 dir 덮어쓰기 차단의 사용자 혼란 | 저 | typer 에러 메시지 + CLI doc + tests 매트릭스 |
| `pymupdf4llm` `write_images=True`의 tmp 디렉토리 IO 오버헤드 | 저 | 내부적으로 tempfile.mkdtemp → 변환 후 즉시 정리 |
| MCP `bundle_b64`가 큰 PDF에서 JSON 응답 폭발 | 중 | 운영 doc에 "MCP zip은 작은 이미지 문서에 적합" 명시. 클라이언트가 sha만 받고 별도 `get_cached`로 후속 호출하는 패턴 권장 |
| `xlsx._images` private API 의존 | 저 | openpyxl 버전 명시 + 호환성 코멘트 + 테스트 |

### 11.2 미해결 (v1.1 후속)

- `options.html_fetch_images=true` (외부 URL fetch + SSRF 검증) — D7 결정에서 보류
- `options.image_format=preserve|jpeg|png` (강제 변환)
- 이미지 alt-text auto-generation (LLM 보조)
- `options.min_image_bytes` 작은 이미지 필터
- bundle.zip 내부 markdown 파일명 사용자 지정 (`paper.md` 고정 → 옵션화)
- HTML 외부 URL 이미지를 fetch한 결과의 cache key 정책 (현재는 mdflow가 fetch 안 하므로 N/A)

### 11.3 spec에서 확정한 디테일 (구현 가이드)

- MCP `bundle_url` base URL: FastAPI `Request.base_url` (Starlette 표준). reverse-proxy는 uvicorn `--proxy-headers` 설정 (운영 가이드 명시).
- `views.none.synthesize`: 코드 블록(` ``` ... ``` `) 내부는 fence detect 후 치환 제외 — `views/none.py` 구현 시 protected-region split 패턴 사용.
- `bundle.zip` 압축 알고리즘: `ZIP_STORED` (이미지는 이미 압축됨, markdown은 작음 — DEFLATE 오버헤드 회피).

---

## 12. 참고 자료

- PRD: `docs/specs/2026-05-21-mdflow-design.md`
- PaperFlow 이미지 처리 패턴: `/media/restful3/data/workspace/paperflow/main_terminal.py` (`text_from_rendered`), `viewer/app/services/papers.py:206` (`import_url_as_paper`)
- Marker 이미지 출력: `marker.output.text_from_rendered` (`(text, images_dict, metadata)`)
- M1a 설계 (SSE event pump + event ordering): `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`
- M2b 설계 (Marker GPU): `docs/specs/2026-05-22-m2b-marker-design.md`
- M4 설계 (MCP + allow_path): `docs/specs/2026-05-22-m4-mcp-design.md`

---
