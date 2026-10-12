from fastapi import APIRouter

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/", summary="Admin API boundary")
async def admin_boundary() -> dict[str, str]:
    """Expose only the skeleton boundary; admin capabilities arrive in later tasks."""

    return {"scope": "admin", "status": "skeleton"}
