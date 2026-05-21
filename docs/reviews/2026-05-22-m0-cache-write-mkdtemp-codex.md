# mdflow M0 cache.write OSError wrap + mkdtemp 리뷰 - Codex

작성일: 2026-05-22
대상:
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py`
- `/media/restful3/data/workspace/mdflow/tests/test_cache.py`

검증:
- `.venv/bin/python -m pytest -q tests/test_cache.py` -> 16 passed
- `.venv/bin/ruff check src/mdflow/core/cache.py tests/test_cache.py` -> All checks passed

## Findings

### 1. #6의 "last os.replace wins" invariant는 현재 코드에서 보장되지 않습니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:94`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:96`
- `/media/restful3/data/workspace/mdflow/tests/test_cache.py:164`

문제:
- `tempfile.mkdtemp()`로 tmp clobber 위험은 줄었지만, publish 단계는 여전히 동시 writer에 안전하지 않습니다.
- `os.replace(tmp, entry)`는 비어 있지 않은 디렉터리 destination을 원자적으로 덮어쓰지 못합니다. 현재 코드는 이를 피하려고 `shutil.rmtree(entry)` 후 `os.replace()`를 호출하는데, 이 두 동작은 하나의 atomic operation이 아닙니다.
- 같은 sha에 대해 두 writer가 동시에 실행되면 다음 상황이 가능합니다.
  - 둘 다 `entry.exists()`를 false로 보고 skip
  - writer A가 `os.replace(tmp_a, entry)` 성공
  - writer B가 `os.replace(tmp_b, entry)`를 호출하지만 destination이 이미 비어 있지 않은 디렉터리라 `OSError` 발생
- 즉 실제 outcome은 "last replace wins"가 아니라 "한 writer는 성공하고 다른 writer는 `CACHE_IO_ERROR`로 실패할 수 있음"입니다.

영향:
- 권고 #6의 핵심 목표가 "동일 key 동시 write는 deterministic이므로 publish race가 사용자 오류로 새지 않게 한다"라면 아직 미충족입니다.
- 주석도 현재 코드가 보장하는 invariant보다 강하게 말하고 있습니다.
- 새 테스트는 sequential write에서 tmp path가 다르다는 점만 검증하므로 이 publish race를 잡지 못합니다.

권고:
- `cache.write()` 전체에 sha별 lock을 두면 기존 overwrite semantics와 `test_cache_write_overwrites_existing`를 유지하면서 "last writer wins"를 실제로 보장할 수 있습니다.
- lock을 두지 않을 계획이라면 정책을 "first complete writer wins; later same-key writer discards tmp if entry already exists"로 바꾸고, `os.replace()`가 destination 존재로 실패했을 때 최종 entry가 완성되어 있으면 tmp만 정리하고 성공 처리하는 방식을 고려하세요. 이 경우 sequential overwrite 테스트와 API semantics도 함께 조정해야 합니다.
- 어느 쪽이든 barrier를 둔 동시 write 회귀 테스트가 필요합니다. 현재 spy 테스트는 unique tmp allocation만 덮습니다.

### 2. `mkdtemp()` 실패는 아직 `MdflowError(CACHE_IO_ERROR)`로 wrap되지 않습니다

위치:
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:82`
- `/media/restful3/data/workspace/mdflow/src/mdflow/core/cache.py:97`
- `/media/restful3/data/workspace/mdflow/tests/test_cache.py:122`

문제:
- `tmp = Path(tempfile.mkdtemp(...))`가 `try` 블록 밖에 있습니다.
- cache root 권한 변경, root 삭제, 디스크/FS 오류 등으로 `mkdtemp()`가 `OSError`를 던지면 raw `OSError`가 그대로 전파됩니다.
- #5write의 목표가 `cache.write`의 OSError path를 `CACHE_IO_ERROR`로 정규화하는 것이라면 범위가 약간 좁습니다.

권고:
- `tmp: Path | None = None`으로 초기화한 뒤 `mkdtemp()`도 같은 `try/except OSError` 안으로 넣으세요.
- cleanup은 `tmp is not None and tmp.exists()`일 때만 수행하면 됩니다.
- 회귀 테스트는 `mdflow.core.cache.tempfile.mkdtemp`를 monkeypatch해 `OSError("...")`를 던지게 하고, `MdflowError(CACHE_IO_ERROR)` 및 `__cause__` 보존을 확인하면 됩니다.

## 질문별 답변

1. `try/except OSError` 범위는 write payload 생성, 기존 entry 제거, publish 단계에는 적절하지만 `mkdtemp()`가 빠져 있어 #5write 기준으로는 약간 좁습니다.

2. tmp dir 정리에서 `ignore_errors=True`를 쓰는 정책은 합리적입니다. 원래 I/O 실패를 표준 retryable error로 올리는 것이 중요하고, cleanup 실패가 주 예외를 가리면 더 나쁩니다. 다만 cleanup 대상 tmp가 만들어지기 전의 실패까지 고려하려면 `tmp is not None` guard가 필요합니다.

3. "last `os.replace` wins" 주석은 현재 코드가 보장하는 invariant를 정확히 기술하지 않습니다. unique tmp dir은 tmp clobber만 막고, destination directory publish race는 별도 lock이나 first-writer 정책 없이는 남습니다.

4. 두 테스트는 각각 "write_text OSError wrap"과 "mkdtemp가 호출마다 unique path를 반환함"은 확인하지만, 놓친 케이스가 있습니다.
   - `mkdtemp()` 자체의 `OSError` wrap
   - 예외 chain `__cause__` 보존
   - 실패 후 `.tmp-{sha}-...` 정리
   - barrier를 둔 동일 sha 동시 write publish race

5. #5read와 #5write는 catch된 예외에 대해서는 일관적입니다. 둘 다 `ErrorCode.CACHE_IO_ERROR`를 쓰고 `raise ... from e`로 chain을 보존합니다. 다만 write 쪽은 `mkdtemp()` 실패가 아직 catch 범위 밖이라 완전한 일관성은 아닙니다.

## 요약

방향은 맞습니다. `Path.write_text` 실패 wrap, `from e` 보존, best-effort tmp cleanup, fixed tmp path 제거는 모두 유효한 개선입니다. 다만 #6은 아직 "동시 writer가 사용자 오류로 새지 않는다"까지 보장하지 못하고, #5write는 temp dir 생성 실패가 빠져 있습니다. commit 전이라면 위 두 지점을 보완하는 편이 좋습니다.
