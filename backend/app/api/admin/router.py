from fastapi import APIRouter

from app.api.admin.config import router as config_router
from app.api.admin.debug import router as debug_router
from app.api.admin.evaluation import router as evaluation_router
from app.api.admin.models import router as models_router

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(config_router)
router.include_router(debug_router)
router.include_router(models_router)
router.include_router(evaluation_router)


@router.get("/", summary="Admin API boundary")
async def admin_boundary() -> dict[str, str]:
    """Expose only the skeleton boundary; admin capabilities arrive in later tasks."""

    return {"scope": "admin", "status": "skeleton"}
