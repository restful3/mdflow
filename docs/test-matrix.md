# mdflow 통합 테스트 매트릭스

> M5 산출물. 포맷 × 실행환경(CPU) × OS/optional 의존 × pytest 마커를 정리한다.
> 정본 상태는 `PROCESS_STATE.md`. 컨버터 집합은 `src/mdflow/runtime/composition.py: build_registry`가 단일 소스이며 `tests/test_composition.py`가 완전성을 잠근다 — 이 문서는 그와 일치해야 한다.

**기준 baseline**: `286 passed / 2 skipped` (`.venv/bin/pytest`, 이 호스트: LibreOffice 24.2.7.2 + pyhwp 설치, GPU 없음). 2 skip = ① hwp 실제 fixture(`tests/fixtures/hwp/sample.hwp` 부재), ② URL redirect status(다른 스텝에서 커버).

## 포맷 × 컨버터 × 테스트 × 의존 × 마커

| 포맷 | 컨버터 (`name`) | 단위 테스트 | 통합/SSE | OS·optional 의존 | 마커 / skip 조건 |
|---|---|---|---|---|---|
| txt, md, csv | `text-passthrough` | `tests/converters/test_text.py` | `tests/api/test_convert.py` | 없음 | 항상 실행 |
| docx | `docx-mammoth` | `test_docx.py` (+golden) | `test_convert.py` | 없음 | 항상 |
| pptx | `pptx-python-pptx` | `test_pptx.py` (+golden) | `test_convert.py` | 없음 | 항상 |
| xlsx | `xlsx-openpyxl` | `test_spreadsheet.py` (+golden) | `test_convert.py` | 없음 | 항상 |
| html | `html-trafilatura` | `test_html.py` (+golden) | `test_convert.py` | 없음 | 항상 |
| pdf | `pdf-pymupdf4llm` | `test_pdf.py` (+golden) | `test_convert.py` | 없음 (pymupdf4llm 번들) | 항상 (CPU) |
| doc, ppt | `office-libreoffice` | `test_office.py` (구조 assert + monkeypatch 에러) | `test_convert.py` | **LibreOffice (`soffice`)** | `@requires_soffice` (없으면 skip). 손상-입력 에러는 `subprocess.run` monkeypatch 결정적 unit |
| hwp | `hwp-pyhwp` | `test_hwp.py` (`_hwp_to_xhtml` monkeypatch + `sys.modules` import 차단) | `test_convert.py` (monkeypatch SSE + 실제 fixture) | **pyhwp (`[hwp]` extra, AGPL)** | monkeypatch 테스트 항상; 실제 변환은 pyhwp+`tests/fixtures/hwp/sample.hwp` 있을 때만 (skip-if-absent) |
| URL 입력 | (포맷별 컨버터로 위임) | `test_url_pipeline.py`, `test_url_fetch.py` | `test_convert.py` (JSON url) | 없음 | 항상 (redirect status 1건 skip) |
| MCP 4 tool | (`ConversionService` 래핑) | `tests/mcp/test_tools.py` (in-memory `Client`) | `tests/mcp/test_http_mount.py` (`/mcp` 마운트 스모크) | 없음 | 항상 |
| **pdf (GPU)** | **`pdf-marker`** | **—** | **—** | **torch + CUDA GPU + marker-pdf (`[gpu]`)** | **DEFERRED — M2b (GPU 호스트 필요)** |

## 실행환경 축 (CPU / GPU)

- **CPU**: 위 모든 행. 이 호스트와 CPU-전용 Dockerfile에서 검증.
- **GPU**: `pdf-marker`(Marker) 한 행만 해당. **M2b 보류** — GPU 호스트에서 `torch`/`marker-pdf` 설치 후 `requires_gpu` 게이팅 + VRAM 직렬화(`gpu_semaphore`) 경로와 함께 검증 예정. 현재 등록된 컨버터는 모두 `requires_gpu=False`.

## OS/optional 의존 요약

| 의존 | 필요 포맷 | 부재 시 |
|---|---|---|
| LibreOffice (`soffice`) | doc, ppt | 해당 테스트 `@requires_soffice` skip; 런타임은 `LIBREOFFICE_UNAVAILABLE` |
| pyhwp (`[hwp]`, AGPL) | hwp | 실제-변환 테스트 skip; 런타임은 `HWP_UNAVAILABLE` |
| torch + CUDA GPU (`[gpu]`) | pdf(Marker) | M2b 보류 — 미등록 |
| libmagic (`python-magic`) | format detect 보강 | best-effort (prefix probe로 자급) |

## 메트릭 / CLI / 컨테이너 (M5)

| 영역 | 테스트 |
|---|---|
| `/capabilities` metrics 카운터 | `tests/api/test_metrics.py` (requests/failures/failure_rate/avg_latency/cache_hit_rate) |
| CLI (`mdflow convert`/`serve`) | `tests/test_cli.py` (`typer.testing.CliRunner`) |
| Dockerfile (CPU) | pytest 비대상 — `docker build --check` 통과(경고 0). 전체 빌드/실행 검증은 별도 환경 후속 |

## 후속 (M2b 시 추가될 행)

- `pdf-marker` (GPU) 행을 활성화: `[gpu]` extra(`torch`, `marker-pdf`), `requires_gpu=True`, `can_handle`에서 GPU 게이팅, PyMuPDF 앞 등록, VRAM 정리(`del model; gc.collect(); torch.cuda.empty_cache()`). GPU Docker 이미지/태그 분기.
