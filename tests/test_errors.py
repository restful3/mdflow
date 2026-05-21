"""ErrorCode enum + MdflowError exception."""

import pytest

from mdflow.core.errors import ErrorCode, MdflowError


def test_error_code_members_exist():
    expected = {
        "UNSUPPORTED_FORMAT",
        "FORMAT_DETECT_FAILED",
        "INPUT_TOO_LARGE",
        "CONVERSION_FAILED",
        "LIBREOFFICE_UNAVAILABLE",
        "TIMEOUT",
        "CACHE_IO_ERROR",
        "INTERNAL",
        "URL_INVALID",
        "URL_BLOCKED",
        "URL_FETCH_FAILED",
        "URL_TIMEOUT",
        "URL_TOO_LARGE",
        "URL_REDIRECT_LIMIT",
        "URL_NON_2XX",
    }
    actual = {member.name for member in ErrorCode}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_error_code_retryable_mapping():
    assert ErrorCode.CONVERSION_FAILED.retryable is True
    assert ErrorCode.TIMEOUT.retryable is True
    assert ErrorCode.CACHE_IO_ERROR.retryable is True
    assert ErrorCode.URL_FETCH_FAILED.retryable is True
    assert ErrorCode.URL_TIMEOUT.retryable is True
    assert ErrorCode.UNSUPPORTED_FORMAT.retryable is False
    assert ErrorCode.URL_INVALID.retryable is False
    assert ErrorCode.URL_BLOCKED.retryable is False
    assert ErrorCode.URL_TOO_LARGE.retryable is False
    assert ErrorCode.URL_REDIRECT_LIMIT.retryable is False
    assert ErrorCode.URL_NON_2XX.retryable is False


def test_mdflow_error_carries_code_and_message():
    err = MdflowError(ErrorCode.URL_BLOCKED, "private IP rejected: 10.0.0.5")
    assert err.code is ErrorCode.URL_BLOCKED
    assert "private IP rejected" in str(err)
    assert err.retryable is False


def test_mdflow_error_is_exception():
    with pytest.raises(MdflowError) as exc_info:
        raise MdflowError(ErrorCode.INTERNAL, "boom")
    assert exc_info.value.code is ErrorCode.INTERNAL
