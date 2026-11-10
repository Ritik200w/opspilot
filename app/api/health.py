from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:  # noqa: B008
    """Liveness probe: the process is up. Does not check dependencies."""
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}
