from fastapi import APIRouter

from app.api.admin.config import router as config_router

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(config_router)


@router.get("/", summary="Admin API boundary")
async def admin_boundary() -> dict[str, str]:
    """Expose only the skeleton boundary; admin capabilities arrive in later tasks."""

    return {"scope": "admin", "status": "skeleton"}
