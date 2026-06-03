from __future__ import annotations

from src.webapp_studio.backend.contracts.types import JsonLike


class StudioApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        retryable: bool = False,
        details: dict[str, JsonLike] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.retryable = retryable
        self.details = {} if details is None else details
