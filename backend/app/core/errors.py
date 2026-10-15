from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    CONFIG_NOT_READY = "CONFIG_NOT_READY"
    SERVICE_BUSY = "SERVICE_BUSY"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MODEL_AUTH_FAILED = "MODEL_AUTH_FAILED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_PROVIDER_ERROR = "MODEL_PROVIDER_ERROR"
    MODEL_OUTPUT_PARSE_ERROR = "MODEL_OUTPUT_PARSE_ERROR"
    MODEL_OUTPUT_SCHEMA_ERROR = "MODEL_OUTPUT_SCHEMA_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
