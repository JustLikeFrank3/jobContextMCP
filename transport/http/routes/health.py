"""Health check endpoint. Intentionally unauthenticated."""

from fastapi import APIRouter

from lib.version import __version__ as _VERSION
from transport.http.config import get_settings
from transport.http.models import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/healthz", include_in_schema=False)  # desktop-shell / k8s probe alias
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=_VERSION,
        auth_enabled=settings.auth_enabled,
    )
