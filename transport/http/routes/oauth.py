"""OAuth 2.0 / MCP discovery endpoints.

Implements three endpoints that allow MCP clients (Claude.ai, mcp-remote,
VS Code) to auto-discover the Entra ID authorization server and complete
the PKCE flow without any manual configuration:

  GET  /.well-known/oauth-protected-resource   RFC 9728 — resource metadata
  GET  /.well-known/oauth-authorization-server RFC 8414 — auth server metadata
  POST /oauth/register                         RFC 7591 — dynamic client reg

Flow that works once these are in place:
  1. Client hits /.well-known/oauth-protected-resource → gets Entra base URL
  2. Client fetches /.well-known/oauth-authorization-server → gets token/auth
     endpoints, scopes, and our /oauth/register endpoint
  3. Client POSTs to /oauth/register → receives ENTRA_CLIENT_ID as client_id
  4. Client opens browser → user logs in to Entra (PKCE, no secret needed)
  5. Client sends resulting Bearer JWT to /mcp
  6. UserDataContextMiddleware validates JWT, extracts oid, routes to tenant

Entra app registration requirements (one-time, done in Azure Portal):
  - "Allow public client flows" = Yes (Entra app → Authentication tab)
  - Add redirect URI: http://localhost  (covers mcp-remote's local callback)
  - Add redirect URI: https://claude.ai/oauth/callback  (Claude.ai native MCP)
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(tags=["oauth-discovery"])


def _base_url(request: Request) -> str:
    """Return the canonical server URL, respecting reverse-proxy headers."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{proto}://{host}"


@router.get(
    "/.well-known/oauth-protected-resource",
    include_in_schema=False,
)
@router.get(
    "/.well-known/oauth-protected-resource/{path:path}",
    include_in_schema=False,
)
async def oauth_protected_resource(request: Request, path: str = "") -> JSONResponse:
    """RFC 9728 Protected Resource Metadata.

    Tells MCP clients where to find the authorization server (Entra ID).
    The path suffix variant handles clients that append the resource path
    (e.g. /.well-known/oauth-protected-resource/mcp).
    """
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    base = _base_url(request)
    # Point to OUR server as the authorization server so that mcp-remote
    # fetches /.well-known/oauth-authorization-server from US (which has a
    # registration_endpoint).  If we pointed to Entra here, mcp-remote would
    # fetch Entra's own openid-configuration, find no registration_endpoint,
    # and throw "Incompatible auth server: does not support dynamic client
    # registration".
    #
    # resource MUST be the server HTTPS origin so that mcp-remote 0.1.37's
    # selectResourceURL check passes (it validates resource == serverUrl or
    # server origin).  mcp-remote then sends resource=<this value> to
    # Entra's authorize endpoint.  Entra v2.0 throws AADSTS9010010 when
    # `resource` and `scope` reference different app identifiers — we fix
    # that via the /oauth/authorize proxy route which strips `resource`
    # before forwarding to Entra.
    return JSONResponse({
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [
            f"api://{client_id}/access",
            "openid",
            "profile",
            "offline_access",
        ],
    })


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_authorization_server(request: Request) -> JSONResponse:
    """RFC 8414 Authorization Server Metadata.

    Served locally so clients get a single document with all Entra endpoints,
    supported scopes, and our dynamic registration endpoint — no second
    round-trip to login.microsoftonline.com required.
    """
    from lib.auth import oauth_discovery_json

    base = _base_url(request)
    data = oauth_discovery_json()
    # RFC 8414 §3.3: issuer MUST equal the URL this document was served from.
    data["issuer"] = base
    data["registration_endpoint"] = f"{base}/oauth/register"
    # Point authorization_endpoint at our proxy route.  mcp-remote will send
    # the browser there; we strip the `resource` param (which causes Entra's
    # AADSTS9010010 when it doesn't match the api:// scope identifier) and
    # 302-redirect to Entra.  token_endpoint stays pointed at Entra directly
    # because the token exchange does not include `resource`.
    data["authorization_endpoint"] = f"{base}/oauth/authorize"
    return JSONResponse(data)


@router.post("/oauth/register", include_in_schema=False)
async def oauth_dynamic_register(request: Request) -> JSONResponse:
    """RFC 7591 Dynamic Client Registration (static proxy).

    MCP clients POST here to "register" and receive a client_id before
    starting the PKCE flow.  Entra requires pre-registered clients, so we
    return the pre-configured ENTRA_CLIENT_ID rather than creating a new
    registration — all MCP clients share the one registered Entra app.

    The client's requested redirect_uris are echoed back; Entra itself
    validates them against the app registration (real security boundary).
    """
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    if not client_id:
        return JSONResponse({"error": "server_not_configured"}, status_code=503)

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    redirect_uris: list[str] = body.get("redirect_uris", [])

    return JSONResponse(
        {
            "client_id": client_id,
            "client_id_issued_at": 0,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # public client / PKCE
            "scope": f"api://{client_id}/access openid profile offline_access",
        },
        status_code=201,
    )


@router.get("/oauth/authorize", include_in_schema=False)
async def oauth_authorize_proxy(request: Request) -> RedirectResponse:
    """Strip the 'resource' param and proxy to Entra's authorize endpoint.

    mcp-remote takes the PRM 'resource' value and adds it as a query param
    when building the authorization URL.  Entra v2.0 throws AADSTS9010010
    when both 'resource' and 'scope' are present and they reference different
    application identifiers (resource=https://... vs scope=api://...).

    We point auth_server_metadata.authorization_endpoint here so that
    mcp-remote sends the browser to US first.  We strip 'resource' from the
    query string, then 302-redirect to Entra's real authorize endpoint.
    All PKCE params (code_challenge, state, redirect_uri, etc.) are
    preserved — this is completely transparent to both the browser and
    mcp-remote's local callback server.
    """
    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    entra_authorize = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    )

    # Forward every param the client sent EXCEPT 'resource'
    params = {k: v for k, v in request.query_params.items() if k != "resource"}
    target_url = f"{entra_authorize}?{urlencode(params)}"
    return RedirectResponse(url=target_url, status_code=302)
