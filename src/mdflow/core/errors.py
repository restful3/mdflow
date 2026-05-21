"""Standard error codes and exception type for mdflow."""

from __future__ import annotations

from enum import Enum


class ErrorCode(Enum):
    UNSUPPORTED_FORMAT = ("UNSUPPORTED_FORMAT", False)
    FORMAT_DETECT_FAILED = ("FORMAT_DETECT_FAILED", False)
    INPUT_TOO_LARGE = ("INPUT_TOO_LARGE", False)
    CONVERSION_FAILED = ("CONVERSION_FAILED", True)
    LIBREOFFICE_UNAVAILABLE = ("LIBREOFFICE_UNAVAILABLE", False)
    TIMEOUT = ("TIMEOUT", True)
    CACHE_IO_ERROR = ("CACHE_IO_ERROR", True)
    INTERNAL = ("INTERNAL", False)
    URL_INVALID = ("URL_INVALID", False)
    URL_BLOCKED = ("URL_BLOCKED", False)
    URL_FETCH_FAILED = ("URL_FETCH_FAILED", True)
    URL_TIMEOUT = ("URL_TIMEOUT", True)
    URL_TOO_LARGE = ("URL_TOO_LARGE", False)
    URL_REDIRECT_LIMIT = ("URL_REDIRECT_LIMIT", False)
    URL_NON_2XX = ("URL_NON_2XX", False)

    def __new__(cls, code: str, retryable: bool) -> ErrorCode:
        obj = object.__new__(cls)
        obj._value_ = code
        obj._retryable = retryable
        return obj

    @property
    def retryable(self) -> bool:
        return self._retryable


class MdflowError(Exception):
    """Error with a structured code carried alongside the message."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message

    @property
    def retryable(self) -> bool:
        return self.code.retryable
