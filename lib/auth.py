"""Entra ID JWT validation middleware and OIDC discovery for jobContextMCP.

Environment variables (injected from k8s secret jcmcp-app-secrets):
    ENTRA_TENANT_ID  — Azure AD tenant ID
    ENTRA_CLIENT_ID  — App registration client ID (== audience claim)

When either variable is unset the middleware is a no-op, preserving
local / stdio operation with no env vars required.
"""

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Callable

import jwt
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — resolved once at import time (module-level constants).
# A pod restart is required to pick up rotated secrets or new env vars.
# ---------------------------------------------------------------------------
TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")

JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

# Paths that bypass auth (discovery + health + OAuth callback)
_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-authorization-server",
    "/health",
    "/callback",
    "/dashboard/login",
    "/dashboard/callback",
})

# ---------------------------------------------------------------------------
# JWKS client — PyJWT handles caching and refresh internally
# ---------------------------------------------------------------------------
_jwks_client: PyJWKClient | None = None


_JWKS_LIFESPAN = 3600

# True once the JWKS has been fetched at least once.  The cache is
# process-local, so this is False on every fresh pod until warm_jwks()
# succeeds.  Readiness is gated on it (see transport/http/routes/health.py):
# a pod that cannot yet verify a signature must not receive traffic, because
# the only thing it can do with a valid token is reject it.
_jwks_warm: bool = False


class SigningKeyUnavailable(Exception):
    """The token's signing key could not be resolved, and that is not (yet) a
    verdict on the token.

    Distinct from `InvalidTokenError`: this says "ask again shortly", and
    callers must map it to 503 + Retry-After, never to 401.  See
    `_resolve_signing_key` for when a key miss stops being retryable.
    """


# ---------------------------------------------------------------------------
# Unknown-`kid` handling
#
# A token whose `kid` is absent from the key set has two very different
# causes, and PyJWT reports both as the same `PyJWKClientError`:
#
#   1. The token is not ours — signed by another tenant, or forged.
#   2. Entra just rotated its signing keys and the key set we fetched
#      predates the new key.  `PyJWKClient` fetches over plain urllib and
#      Entra serves its JWKS through a CDN, so even a forced re-fetch can be
#      answered by an edge node holding a copy from before the rotation.
#      There is no request we can make that proves we saw the newest set.
#
# The costs are lopsided.  Calling (2) invalid returns 401 + a
# WWW-Authenticate challenge, which invalidates a hosted MCP connector and
# makes the user reconnect by hand — the exact failure #196 exists to
# remove.  Calling (1) unavailable costs a client one automatic retry.
#
# So: a kid miss is reported unavailable at first, and only hardens into
# "invalid" if the same kid keeps missing from freshly fetched key sets for
# longer than any plausible CDN propagation lag.  A rotation self-heals; a
# foreign token gets a definitive answer inside a minute instead of retrying
# forever.
# ---------------------------------------------------------------------------

# How long the same kid must keep missing before we call the token foreign.
_KID_PROPAGATION_GRACE = 60.0

# A key set older than this cannot support a rejection.  Freshness that
# cannot be established is treated exactly like a fetch failure: 503.
_FRESH_FETCH_WINDOW = 30.0

# Floor between forced fetches.  `kid` comes off an unverified token header,
# so without this a stream of made-up kids would turn into one blocking
# JWKS fetch per request against login.microsoftonline.com.
_MIN_FORCED_FETCH_INTERVAL = 10.0

# Bounds on the miss ledger.  Entries expire, and the map is capped, because
# its keys are attacker-chosen.
_KID_MISS_TTL = 900.0
_KID_MISS_MAX = 256

# kid digest -> monotonic timestamp of the first miss for that kid.
# Insertion order is first-miss order, which is what makes expiry a walk from
# the front and eviction a pop from the front.
_kid_misses: "OrderedDict[str, float]" = OrderedDict()
_kid_lock = threading.Lock()

# Monotonic timestamp of the last forced fetch that actually *succeeded*
# (None if none has).  Only fetches we made ourselves count — this is the
# whole basis for calling a key set "fresh".
_last_forced_fetch: float | None = None

# Monotonic timestamp of the last forced fetch we *attempted*.  Separate from
# the above so that a failing endpoint still throttles: otherwise every
# request during an Entra outage would open its own blocking connection.
_last_fetch_attempt: float | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URI, cache_jwk_set=True, lifespan=_JWKS_LIFESPAN)
    return _jwks_client


def jwks_ready() -> bool:
    """Whether Entra's signing keys are cached and tokens can be verified.

    Always True when Entra is not configured (local / API-key mode), where
    there is no JWKS to fetch.
    """
    if not TENANT_ID or not CLIENT_ID:
        return True
    return _jwks_warm


def warm_jwks() -> None:
    """Fetch and cache Entra's signing keys.

    Blocking (PyJWKClient uses urllib), so callers on the event loop must
    hand this to a thread.  Raises on failure; the caller decides whether to
    retry.

    Always fetches (`refresh=True`) rather than accepting whatever is cached,
    so a periodic call reliably resets the cache clock.  That is what keeps
    the inline validation path a guaranteed cache hit — and therefore free of
    network I/O on the event loop.
    """
    global _jwks_warm
    _mark_fetch_attempt()
    _get_jwks_client().get_signing_keys(refresh=True)
    _mark_forced_fetch()
    _jwks_warm = True


def _reset_jwks_state_for_tests() -> None:
    """Drop the cached client, warm flag and kid ledger (tests only)."""
    global _jwks_client, _jwks_warm, _last_forced_fetch, _last_fetch_attempt
    _jwks_client = None
    _jwks_warm = False
    _last_forced_fetch = None
    _last_fetch_attempt = None
    with _kid_lock:
        _kid_misses.clear()


def _mark_fetch_attempt() -> None:
    """Record that we are about to go to the network, before we know whether
    it works — a failing endpoint has to throttle too."""
    global _last_fetch_attempt
    _last_fetch_attempt = time.monotonic()


def _mark_forced_fetch() -> float:
    """Record that we just pulled the key set over the network."""
    global _last_forced_fetch
    stamped = time.monotonic()
    _last_forced_fetch = stamped
    return stamped


def _kid_digest(kid: str) -> str:
    """Ledger key for a kid.

    Hashed rather than stored verbatim: the kid is read from an unverified
    token header, so its length is chosen by whoever sent the token.  A fixed
    64-char digest keeps every entry the same small size.
    """
    return hashlib.sha256(kid.encode("utf-8", "replace")).hexdigest()


def _kid_for_log(kid: str) -> str:
    """Short, bounded rendering of a kid for log lines."""
    return kid[:32] + "…" if len(kid) > 32 else kid


def _expire_kid_misses(now: float) -> None:
    """Drop entries past their TTL.  Caller holds `_kid_lock`."""
    while _kid_misses:
        digest, first_seen = next(iter(_kid_misses.items()))
        if now - first_seen > _KID_MISS_TTL:
            _kid_misses.pop(digest)
        else:
            break  # insertion order == age order, so the rest are younger


def _record_kid_miss(kid: str, now: float) -> float:
    """Note a miss for `kid` and return when it was *first* seen missing."""
    digest = _kid_digest(kid)
    with _kid_lock:
        _expire_kid_misses(now)
        first_seen = _kid_misses.get(digest)
        if first_seen is None or now - first_seen > _KID_MISS_TTL:
            first_seen = now
            _kid_misses.pop(digest, None)
            _kid_misses[digest] = first_seen
        while len(_kid_misses) > _KID_MISS_MAX:
            # Evict the oldest first-miss.  Losing an entry only costs that
            # kid a fresh grace period — it can never turn into a wrong 401.
            _kid_misses.popitem(last=False)
        return first_seen


def _forget_kid_miss(kid: str) -> None:
    """Clear any miss history for a kid that has since resolved."""
    if not _kid_misses:  # keep the hot path free of hashing and locking
        return
    with _kid_lock:
        _kid_misses.pop(_kid_digest(kid), None)


def _signing_keys(client: PyJWKClient, *, refresh: bool) -> list[PyJWK]:
    """Signing keys from the JWKS, with issuer-side faults kept retryable.

    `PyJWKClientError` also covers "endpoint returned no JSON object" and
    "no signing keys in the set".  Those are broken responses from Entra, not
    statements about the caller's token, so they must not reach the code that
    decides whether a kid is foreign.
    """
    try:
        return client.get_signing_keys(refresh=refresh)
    except PyJWKClientConnectionError:
        raise  # already means "could not reach the issuer" → 503
    except PyJWKClientError as exc:
        raise SigningKeyUnavailable(f"JWKS unusable: {exc}") from exc


def _fresh_signing_keys(client: PyJWKClient) -> tuple[list[PyJWK], float | None]:
    """Return signing keys plus the time they were last fetched successfully
    over the network — `None` if that has never happened.

    Forces a fetch unless one was attempted within `_MIN_FORCED_FETCH_INTERVAL`;
    inside that window the cache still holds the last answer and re-requesting
    it would only hammer the endpoint.  Note the timestamp returned in that
    case is the last *successful* fetch, which may be older: an unreachable
    endpoint throttles attempts without ever refreshing what we know, and the
    caller must see that as unproven rather than fresh.
    """
    attempted = _last_fetch_attempt
    if attempted is None or time.monotonic() - attempted >= _MIN_FORCED_FETCH_INTERVAL:
        _mark_fetch_attempt()
        keys = _signing_keys(client, refresh=True)
        return keys, _mark_forced_fetch()
    return _signing_keys(client, refresh=False), _last_forced_fetch


def _resolve_after_kid_miss(client: PyJWKClient, kid: str) -> PyJWK:
    """Decide what a missing `kid` means, once the cache has already missed."""
    keys, fetched_at = _fresh_signing_keys(client)

    key = client.match_kid(keys, kid)
    if key is not None:
        # The cache was simply behind; nothing was ever wrong with the token.
        _forget_kid_miss(kid)
        return key

    now = time.monotonic()
    if fetched_at is None or now - fetched_at > _FRESH_FETCH_WINDOW:
        # We cannot show the key set we just checked is current, so we have no
        # standing to call the token foreign.
        raise SigningKeyUnavailable(
            f"no fresh key set to check kid {_kid_for_log(kid)} against"
        )

    first_seen = _record_kid_miss(kid, now)
    missing_for = now - first_seen
    if missing_for >= _KID_PROPAGATION_GRACE:
        logger.warning(
            "kid=%s absent from freshly fetched JWKS for %.0fs — treating token as foreign",
            _kid_for_log(kid), missing_for,
        )
        raise jwt.InvalidTokenError(f'Unable to find a signing key that matches: "{kid}"')

    logger.info(
        "kid=%s absent from a freshly fetched JWKS (%.0fs of %.0fs grace) — reporting unavailable",
        _kid_for_log(kid), missing_for, _KID_PROPAGATION_GRACE,
    )
    raise SigningKeyUnavailable(f"signing key {_kid_for_log(kid)} not visible yet")


def _resolve_signing_key(token: str) -> PyJWK:
    """Find the JWKS key that signed `token`.

    Deliberately does not use `PyJWKClient.get_signing_key_from_jwt`, which
    hides its own forced re-fetch inside the miss path: we need to know
    whether a fetch actually happened and when, and we need that fetch rate
    limited.  Raises `InvalidTokenError` (→ 401) or `SigningKeyUnavailable` /
    `PyJWKClientConnectionError` (→ 503).
    """
    kid = jwt.get_unverified_header(token).get("kid")
    if not kid or not isinstance(kid, str):
        # Nothing to look up, and no rotation can change that.  The isinstance
        # check matters: the header is unverified JSON, so `kid` can arrive as
        # a number or an object, and nothing downstream should have to cope.
        raise jwt.InvalidTokenError("Token header carries no usable 'kid'")

    client = _get_jwks_client()
    key = client.match_kid(_signing_keys(client, refresh=False), kid)
    if key is not None:
        _forget_kid_miss(kid)
        return key
    return _resolve_after_kid_miss(client, kid)


def validate_token(token: str) -> dict:
    """Validate an Entra ID Bearer JWT and return the decoded claims.

    Accepts both v1 tokens (iss = sts.windows.net/…) and v2 tokens
    (iss = login.microsoftonline.com/…/v2.0) by skipping issuer check —
    the JWKS signature check is the security boundary.
    """
    signing_key = _resolve_signing_key(token)
    allowed_audiences = [CLIENT_ID, f"api://{CLIENT_ID}"]

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=allowed_audiences,
        options={"verify_iss": False},
    )
    return claims


# ---------------------------------------------------------------------------
# RFC 8414 Authorization Server Metadata
# Returned at /.well-known/oauth-authorization-server so MCP clients
# (VS Code, Claude Desktop, ChatGPT) can discover the token endpoint and
# initiate the PKCE flow automatically on first connection.
# ---------------------------------------------------------------------------
def oauth_discovery_json() -> dict:
    base = f"https://login.microsoftonline.com/{TENANT_ID}"
    return {
        "issuer": f"{base}/v2.0",
        "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
        "token_endpoint": f"{base}/oauth2/v2.0/token",
        "jwks_uri": f"{base}/discovery/v2.0/keys",
        "scopes_supported": [
            f"api://{CLIENT_ID}/access",
            "openid",
            "profile",
            "offline_access",
        ],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "registration_endpoint": None,
    }


# ---------------------------------------------------------------------------
# Starlette middleware
# ---------------------------------------------------------------------------
class EntraAuthMiddleware(BaseHTTPMiddleware):
    """Validate Entra ID Bearer tokens on every non-public request.

    No-op when ENTRA_TENANT_ID or ENTRA_CLIENT_ID is not set so local
    stdio / docker-compose mode continues to work without any changes.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # No-op: local mode (env vars not injected)
        if not TENANT_ID or not CLIENT_ID:
            return await call_next(request)

        # Public endpoints pass through unconditionally
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # RFC 9728 §5.1: carry the Protected Resource Metadata URL so a
            # client can start OAuth discovery from this bare 401 (Alexa+
            # probes unauthenticated and follows exactly this pointer).
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("x-forwarded-host", request.url.netloc)
            prm_url = f"{proto}://{host}/.well-known/oauth-protected-resource"
            return JSONResponse(
                {"error": "unauthorized", "message": "Bearer token required"},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="jobContextMCP", resource_metadata="{prm_url}"'
                    )
                },
            )

        token = auth_header.removeprefix("Bearer ")

        try:
            claims = validate_token(token)
            request.state.user = claims
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                {"error": "unauthorized", "message": "Token expired"},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="jobContextMCP", error="invalid_token",'
                        ' error_description="Token has expired"'
                    )
                },
            )
        except jwt.InvalidTokenError as exc:
            return JSONResponse(
                {"error": "unauthorized", "message": str(exc)},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer realm="jobContextMCP", error="invalid_token"'
                    )
                },
            )
        except (PyJWKClientConnectionError, SigningKeyUnavailable) as exc:
            # Could not *check* the token. Retryable, and deliberately with no
            # WWW-Authenticate — that header is what makes a client discard a
            # credential that may well still be good.
            logger.warning("Token could not be verified (%s) — returning 503", exc)
            return JSONResponse(
                {
                    "error": "service_unavailable",
                    "message": "Unable to verify credentials right now; retry shortly.",
                },
                status_code=503,
                headers={"Retry-After": "5"},
            )
        except Exception:
            logger.exception("Unexpected error during token validation")
            return JSONResponse(
                {"error": "server_error", "message": "Token validation failed"},
                status_code=500,
            )

        return await call_next(request)
