"""Typed error model — structured payloads, never raw exception text."""
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    INTERNAL = "INTERNAL"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    QUERY_DENIED = "QUERY_DENIED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_EXISTS = "CONNECTION_EXISTS"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
    PLAN_INVALID = "PLAN_INVALID"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"


class DatahekError(Exception):
    """Expected, typed application error."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ):
        self.code = code
        self.details = details or {}
        self.http_status = http_status
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": str(self), "details": self.details}