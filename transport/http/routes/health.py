"""Health check endpoint. Intentionally unauthenticated."""

from fastapi import APIRouter

from lib.version import __version__ as _VERSION
from transport.http.models import HealthResponse
from transport.http.security import get_auth_provider


router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/healthz", include_in_schema=False)  # desktop-shell / k8s probe alias
async def health() -> HealthResponse:
    # Ask the active provider, not settings.auth_enabled — that flag only
    # reflects API_KEY, so Entra deployments would report auth_enabled=false.
    return HealthResponse(
        version=_VERSION,
        auth_enabled=get_auth_provider().auth_enabled,
    )
