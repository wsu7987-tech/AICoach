from typing import Literal

from pydantic import BaseModel

from app.core.errors import ErrorCode


class ErrorEnvelope(BaseModel):
    request_id: str
    status: Literal["failed"] = "failed"
    error_code: ErrorCode
    message: str
