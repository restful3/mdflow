# mdflow 통합 테스트 매트릭스

> M5 산출물. 포맷 × 실행환경(CPU) × OS/optional 의존 × pytest 마커를 정리한다.
> 정본 상태는 `PROCESS_STATE.md`. 컨버터 집합은 `src/mdflow/runtime/composition.py: build_registry`가 단일 소스이며 `tests/test_composition.py`가 완전성을 잠근다 — 이 문서는 그와 일치해야 한다.

**기준 baseline**: `299 passed / 2 skipped` (`.venv/bin/pytest`, 이 호스트: LibreOffice 24.2.7.2 + pyhwp + torch 2.6+cu124 + marker-pdf 1.10.2 + RTX 3060 12GB). 2 skip = ① hwp 실제 fixture(`tests/fixtures/hwp/sample.hwp` 부재), ② URL redirect status(다른 스텝에서 커버). 호스트에 GPU/marker가 없으면 `tests/converters/test_marker.py::test_marker_real_gpu_smoke`도 skip된다.

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
| **pdf (GPU)** | **`pdf-marker`** | `test_marker.py` (게이팅 + monkeypatch 파이프라인 + 에러 전파) | `@pytest.mark.gpu` `test_marker_real_gpu_smoke` (실 inference) | **torch + CUDA GPU + marker-pdf (`[gpu]`, M2b)** | unit은 항상; 실 inference는 `@requires_gpu_runtime`(torch+CUDA+marker 없으면 skip) |

## 실행환경 축 (CPU / GPU)

- **CPU**: 위 모든 행. 이 호스트와 CPU-전용 Dockerfile에서 검증.
- **GPU**: `pdf-marker`(Marker) 한 행만 해당. **M2b 완료** — torch 2.6+cu124 + marker-pdf 1.10.2 + RTX 3060 12GB로 검증. `requires_gpu=True` + `can_handle` 게이팅(`MDFLOW_FORCE_CPU`/CUDA/marker 부재 시 False) + `gpu_semaphore(1)` 직렬화 + VRAM 정리(`del model; gc.collect(); torch.cuda.empty_cache()`) 동작 확인. 테스트 스위트에는 autouse `MDFLOW_FORCE_CPU=1`로 라우팅 결정성 유지(실 GPU smoke만 opt-out).

## OS/optional 의존 요약

| 의존 | 필요 포맷 | 부재 시 |
|---|---|---|
| LibreOffice (`soffice`) | doc, ppt | 해당 테스트 `@requires_soffice` skip; 런타임은 `LIBREOFFICE_UNAVAILABLE` |
| pyhwp (`[hwp]`, AGPL) | hwp | 실제-변환 테스트 skip; 런타임은 `HWP_UNAVAILABLE` |
| torch + CUDA GPU (`[gpu]`) | pdf(Marker) | `MarkerConverter.can_handle=False` → first-wins로 PyMuPDF 선택 |
| libmagic (`python-magic`) | format detect 보강 | best-effort (prefix probe로 자급) |

## 메트릭 / CLI / 컨테이너 (M5)

| 영역 | 테스트 |
|---|---|
| `/capabilities` metrics 카운터 | `tests/api/test_metrics.py` (requests/failures/failure_rate/avg_latency/cache_hit_rate) |
| CLI (`mdflow convert`/`serve`) | `tests/test_cli.py` (`typer.testing.CliRunner`) |
| Dockerfile (CPU) | pytest 비대상 — `docker build --check` 통과(경고 0). 전체 빌드/실행 검증은 별도 환경 후속 |

## GPU install (M2b)

`[gpu]` extra는 `marker-pdf>=1.0`과 `torch>=2.4`를 선언하지만, 일반 PyPI resolver는 marker-pdf 1.10.x의 `torch>=2.7` 요구로 CUDA 13 wheel을 가져올 수 있다. driver가 CUDA 12.x만 지원하는 호스트(예: NVIDIA driver 12.6)에서는 `"NVIDIA driver too old"`로 inference가 막힌다.

권장 절차 (CUDA 12.x driver 호스트):

```bash
# 1) Marker + 의존성 설치 (PyPI 기본 채널)
.venv/bin/pip install '.[gpu]'

# 2) torch를 driver 호환 wheel(cu124)로 강제 재설치
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cu124 \
  --force-reinstall 'torch==2.6.0+cu124'

# 3) 검증
.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# 기대: 2.6.0+cu124 True

.venv/bin/pytest -m gpu -v
# 기대: tests/converters/test_marker.py::test_marker_real_gpu_smoke PASS
#       tests/api/test_convert.py::test_convert_sse_routes_pdf_through_marker_when_gpu_enabled PASS
```

`pip`은 `"marker-pdf 1.10.2 requires torch<3.0.0,>=2.7.0, but you have torch 2.6.0+cu124"` 경고를 띄우지만 실 import/inference는 통과한다(이 호스트 RTX 3060 12GB로 검증). marker-pdf 안정 채널이 driver를 따라잡거나 호스트 driver를 12.8+로 업그레이드할 때까지 핀 유지.

## GPU 동시 실행 정책 (M2b)

- **HTTP `/convert`**: `requires_gpu=True` 컨버터는 `gpu_semaphore(1)`로 직렬화(M2a). VRAM 1-모델-1-프로세스 불변식 강제.
- **HTTP-mounted MCP `/mcp`**: 같은 FastAPI 프로세스에서 `gpu_semaphore`를 우회할 수 있어 `build_mcp(allow_gpu=False)`로 MarkerConverter를 등록 자체에서 제외 — PDF는 PyMuPDF로 처리(Codex M2b 차단 fix).
- **stdio MCP (`mdflow-mcp`)**: 별도 프로세스. GPU 허용(opt-in). 단, 같은 호스트에서 HTTP 서버와 동시에 GPU를 호출하지는 말 것.
- **CLI (`mdflow convert`)**: 별도 프로세스이며 `ConversionService.convert`를 직접 호출 — in-process semaphore 공유 불가. **서버(`mdflow serve`)가 GPU 변환 중일 때 CLI로 GPU 변환을 동시에 돌리지 말 것.** v1은 운영 정책으로 분리.

## 후속 (M2b 완료 시 추가 검토)

- GPU Docker 이미지/태그 분기 (현재는 CPU 단일 이미지).
- CLI `--gpu` opt-in 플래그 / 서버-CLI 간 GPU lockfile 등 동시 실행 방지 메커니즘 (현재는 운영 문서로만 분리).
