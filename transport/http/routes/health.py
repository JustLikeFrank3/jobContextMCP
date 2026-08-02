"""Health and readiness endpoints. Intentionally unauthenticated.

/health   liveness — is the process up? Never fails for a dependency, or a
          transient Entra outage would get the pod killed and restarted.
/ready    readiness — can this pod actually serve an authenticated request?
          False until Entra's signing keys are cached, because until then
          the only thing the pod can do with a valid token is fail to verify
          it.  Keeping traffic away during that window is what stops a fresh
          pod from answering good credentials with an error.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    """Readiness probe — 200 once tokens can be verified, else 503."""
    from lib.auth import jwks_ready

    warm = jwks_ready()
    return JSONResponse(
        {"status": "ready" if warm else "starting", "jwks": warm},
        status_code=200 if warm else 503,
    )
