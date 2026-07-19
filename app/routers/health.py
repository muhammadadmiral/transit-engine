from fastapi import APIRouter

from app.core.config import get_settings
from app.models.schema import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(environment=get_settings().app_env)

