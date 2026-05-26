"""Health check endpoint. Intentionally unauthenticated."""

from fastapi import APIRouter

from transport.http.config import get_settings
from transport.http.models import HealthResponse


router = APIRouter(tags=["health"])

_VERSION = "0.7.0-dev"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=_VERSION,
        auth_enabled=settings.auth_enabled,
    )
