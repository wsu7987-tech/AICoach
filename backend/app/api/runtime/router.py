import json

from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.core.errors import AppError, ErrorCode
from app.schemas.intent import IntentAnalyzeRequest, IntentResult

router = APIRouter(prefix="/api/v1", tags=["runtime"])


@router.get("/", summary="Runtime API boundary")
async def runtime_boundary() -> dict[str, str]:
    """Expose only the skeleton boundary; business endpoints arrive in later tasks."""

    return {"scope": "runtime", "status": "skeleton"}


@router.post("/intent/analyze", response_model=IntentResult)
async def analyze_intent(request: Request) -> IntentResult:
    """The stable public Runtime endpoint; all diagnostics remain in Trace."""

    settings = request.app.state.settings
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > settings.max_request_body_bytes
    ):
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "request body too large", 413)
    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "request body too large", 413)
    try:
        payload = json.loads(body)
        parsed = IntentAnalyzeRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        raise AppError(ErrorCode.INVALID_INPUT, "request validation failed", 422) from None
    if len(parsed.text) > settings.max_text_chars:
        raise AppError(ErrorCode.INVALID_INPUT, "text exceeds MAX_TEXT_CHARS", 422)
    context_bytes = len(json.dumps(parsed.context, ensure_ascii=False).encode("utf-8"))
    if context_bytes > settings.max_context_bytes:
        raise AppError(ErrorCode.INVALID_INPUT, "context exceeds MAX_CONTEXT_BYTES", 422)
    service = getattr(request.app.state, "intent_service", None)
    if service is None:
        raise AppError(ErrorCode.CONFIG_NOT_READY, "runtime configuration is not ready", 503)
    return await service.analyze(
        text=parsed.text,
        context=parsed.context,
        request_id=parsed.request_id or request.state.request_id,
        execution_mode="runtime",
    )
