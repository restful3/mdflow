# M5 운영 도구 리뷰 (Codex)

범위: `git diff v0.5.0-m4..HEAD`

검증:
- `.venv/bin/python -m pytest -q` -> 286 passed / 2 skipped
- `.venv/bin/ruff format --check src tests && .venv/bin/ruff check src tests` -> pass
- `docker build --check .` -> Check complete, no warnings found
- focused: `.venv/bin/python -m pytest tests/api/test_metrics.py tests/test_cli.py -q` -> 9 passed

## Blocking

없음. M5 채택을 막을 차단급 정확성/보안 문제는 발견하지 못했습니다.

## Recommend

### 1. `Metrics`의 "단일 이벤트 루프라 락 불요" 설명은 현재 FastAPI 라우팅과 약간 다릅니다

근거:
- `/convert`의 `_metered`는 async SSE generator에서 `metrics.record(...)`를 호출합니다: `src/mdflow/api/convert.py:91-109`.
- `/capabilities`는 `def` sync route라 FastAPI가 threadpool에서 실행할 수 있고, 여기서 `state.metrics.snapshot()`을 읽습니다: `src/mdflow/api/admin.py:30-40`.
- `Metrics.record()`는 여러 필드를 순차 갱신합니다: `src/mdflow/core/metrics.py:18-23`.

판단:
- 쓰기는 `/convert` event loop 쪽에서만 발생하고, Python GIL 아래의 단순 int/float 갱신이라 M5 in-process counter로는 충분합니다. 차단은 아닙니다.
- 다만 "단일 이벤트 루프에서만 갱신/접근하므로 락 불요"로 읽히면 `/capabilities` threadpool read와 다릅니다. 순간적으로 `requests`와 `_latency_count`가 한 record 중간값으로 보일 수는 있지만, 치명적이지 않고 다음 snapshot에서 수렴합니다.

권장:
- 주석을 "single-process best-effort counter; writes are non-awaiting and reads may be eventually consistent" 정도로 낮추거나, 더 엄밀한 snapshot이 필요하면 `/capabilities`를 async route로 바꾸거나 `threading.Lock`을 넣으세요.

### 2. 현재 metrics의 `requests`는 "StreamingResponse까지 도달한 변환 시도"만 셉니다

근거:
- 입력 검증 실패는 `_metered(...)`로 감싸기 전 `HTTPException`으로 반환됩니다: `src/mdflow/api/convert.py:127-156`.
- `_metered`는 `StreamingResponse(_metered(stream(), ...))` 이후의 SSE stream에서만 기록합니다: `src/mdflow/api/convert.py:259-262`.

판단:
- 설계가 "terminal SSE 이벤트 관찰" 기준이라면 맞습니다. 성공, 변환 실패, fetch/lookup 실패, cache hit(`cached` 후 `done`) 모두 하나의 terminal event로 집계됩니다.
- 다만 운영자가 `requests`를 모든 `/convert` HTTP request로 이해하면 400/413 같은 pre-stream rejection은 빠집니다.

권장:
- 이름/문서에서 "conversion_requests" 또는 "streamed convert attempts" 의미를 분명히 하거나, 모든 `/convert` 요청 수가 필요하면 pre-stream 검증 실패도 별도 counter로 기록하세요.

### 3. CLI 출력 파일 쓰기 오류가 `MdflowError`/`OSError` 매핑 밖에 있습니다

근거:
- 입력 read와 변환은 try/except 안에 있지만, `output.write_text(...)`는 try 블록 밖입니다: `src/mdflow/cli.py:45-61`.

영향:
- 권한 없음, 디렉터리 경로, 디스크 오류 등 출력 쓰기 실패 시 Typer가 raw exception을 처리하게 되어, 문서화한 "OSError -> exit 1" 계약과 다소 어긋납니다.

권장:
- `output.write_text`도 `OSError` 처리 범위에 넣고 `cannot write output: ...` + exit 1로 표준화하세요.

### 4. CLI file input은 HTTP/MCP와 달리 `MDFLOW_MAX_INPUT_MB` cap을 적용하지 않습니다

근거:
- HTTP file path는 bounded read + 413을 적용합니다: `src/mdflow/api/convert.py:121-156`.
- MCP `convert_file`도 size cap을 적용합니다.
- CLI는 `file.read_bytes()` 후 바로 `service.convert(...)`로 넘깁니다: `src/mdflow/cli.py:49-52`.

판단:
- CLI는 로컬 단발 도구라 서버 보호 목적의 cap을 그대로 적용하지 않아도 됩니다. 차단은 아닙니다.
- 그래도 세 transport의 사용자 계약을 맞추려면 같은 설정을 적용하는 편이 예측 가능성이 좋습니다.

## Notes

- `_metered`의 terminal event 감지는 현재 `_sse()` 포맷과 일치합니다. `_sse()`는 `event: <name>\n...`로 시작하고(`src/mdflow/api/convert.py:32-33`), `_metered`는 `event: done`/`event: error` prefix를 관찰합니다(`src/mdflow/api/convert.py:101-107`).
- cache hit 경로는 `cached` 후 `done`을 yield하므로 성공으로 집계됩니다: `src/mdflow/api/convert.py:227-230`.
- client disconnect를 terminal event 없음 -> failure로 집계하는 기본값은 운영상 보수적인 선택입니다: `src/mdflow/api/convert.py:99-109`.
- 단일 기록 지점도 잘 지켜져 있습니다. 기존 stream 내부 분기는 그대로 두고 route return에서 wrapper만 씌웠습니다: `src/mdflow/api/convert.py:158-262`.
- `Metrics.snapshot()`의 `failure_rate`와 `avg_latency_ms`는 0-division guard가 있습니다: `src/mdflow/core/metrics.py:25-31`. `cache_hit_rate`도 hit+miss 0일 때 0.0입니다: `src/mdflow/api/admin.py:24-26`.
- CLI exactly-one 검증과 exit code 매핑은 의도와 맞습니다: `src/mdflow/cli.py:36-58`. `serve`는 module-level `uvicorn` import라 monkeypatch test가 가능합니다: `src/mdflow/cli.py:13-14`, `src/mdflow/cli.py:66-69`.
- B008 per-file-ignore는 Typer의 `typer.Argument/Option` default idiom에 대한 합리적인 예외입니다: `pyproject.toml:69-72`.
- Dockerfile은 CPU 범위에 맞습니다. LibreOffice writer/impress/calc, CJK fonts, `.[hwp]`, no GPU가 명확합니다: `Dockerfile:7-27`. `.dockerignore`도 wheel build에 필요한 `pyproject.toml`/`src`를 남기고 무거운 테스트/문서를 제외합니다.
- `docs/test-matrix.md`의 converter set은 `build_registry(Settings()).list_formats()`와 일치합니다: text/docx/pptx/xlsx/html/pdf/office/doc,ppt/hwp + deferred `pdf-marker`.
