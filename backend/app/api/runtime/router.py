from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["runtime"])


@router.get("/", summary="Runtime API boundary")
async def runtime_boundary() -> dict[str, str]:
    """Expose only the skeleton boundary; business endpoints arrive in later tasks."""

    return {"scope": "runtime", "status": "skeleton"}
