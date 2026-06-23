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
  - Under "Mobile and desktop applications" platform:
      cursor://anysphere.cursor-mcp/oauth/callback  (Cursor IDE)
      http://localhost                               (mcp-remote local callback)
  - Under "Single-page application" or "Web" platform:
      https://claude.ai/oauth/callback              (Claude.ai native MCP)

  NOTE: Custom URI schemes (cursor://, vscode://, etc.) MUST be registered
  under "Mobile and desktop applications" — the "Web" platform rejects them.
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

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
    # Point BOTH authorize and token endpoints at our proxy routes.
    # mcp-remote sends resource=<server-origin> in both the authorize redirect
    # and the token exchange POST.  Entra v2.0 throws AADSTS9010010 when
    # resource and scope reference different application identifiers.
    # Our proxies strip 'resource' before forwarding to Entra.
    data["authorization_endpoint"] = f"{base}/oauth/authorize"
    data["token_endpoint"] = f"{base}/oauth/token"
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


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token_proxy(request: Request):
    """Strip 'resource' from the token exchange POST and forward to Entra.

    mcp-remote sends resource=<server-origin> in the token exchange body.
    Entra v2.0 throws AADSTS9010010 when 'resource' and 'scope' reference
    different application identifiers.  We strip it here before forwarding.
    """
    import httpx

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    entra_token = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    )

    import logging
    _log = logging.getLogger(__name__)

    # Parse the form body and strip 'resource'
    form = await request.form()
    payload = {k: v for k, v in form.multi_items() if k != "resource"}

    # Debug: log what the client sent (mask secrets)
    safe = {k: (str(v)[:8] + "…" if k in ("code", "client_secret", "refresh_token") and len(str(v)) > 8 else str(v))
            for k, v in payload.items()}
    _log.info("oauth/token proxy payload: %s", safe)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            entra_token,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

    if resp.status_code >= 400:
        _log.warning("oauth/token Entra error %s: %s", resp.status_code, resp.text[:500])

    from fastapi.responses import Response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
    )


@router.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    """User-facing logout page.

    Clears the Entra browser session via the end_session_endpoint, then
    shows instructions for clearing the local mcp-remote token cache.
    Visit https://jobcontext.ai/logout in a browser.
    """
    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    base = _base_url(request)
    entra_logout = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={base}/logged-out"
    )
    return RedirectResponse(url=entra_logout, status_code=302)


@router.post("/logout", include_in_schema=False)
async def logout_post(request: Request) -> RedirectResponse:
    """POST handler for sign-out form buttons across the dashboard.

    Clears the jc_session cookie first.  In Entra mode, hands off to the
    Entra end-session endpoint so the SSO session is also cleared
    server-side, then Entra redirects the browser back to the root landing
    page (/).  In API-key (non-Entra) mode, skips Entra and goes straight
    to / so the user can click Sign In again.
    """
    from transport.http.routes.dashboard.login import _is_secure
    from transport.http.security import EntraAuthProvider, get_auth_provider

    provider = get_auth_provider()

    if isinstance(provider, EntraAuthProvider):
        tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
        # Use SERVER_BASE_URL (same env var login.py uses) so the redirect URI
        # always matches what is registered in Entra AD.  _base_url(request)
        # derives the URL from X-Forwarded-Host which may differ from the
        # registered URI when running behind an ingress or load balancer.
        server_base = os.environ.get(
            "SERVER_BASE_URL",
            "https://jobcontext.ai",
        )
        target = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={server_base}/"
        )
    else:
        target = "/"

    resp = RedirectResponse(url=target, status_code=303)
    resp.delete_cookie("jc_session", path="/", httponly=True,
                       samesite="lax", secure=_is_secure(request))
    return resp


@router.get("/logged-out", include_in_schema=False)
async def logged_out(request: Request) -> HTMLResponse:
    """Post-logout landing page with local cache clear instructions."""
    mcp_auth_path = "~/.mcp-auth/mcp-remote-0.1.37"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Logged out — jobContextMCP</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; max-width: 560px;
           margin: 80px auto; padding: 0 24px; color: #1a1a1a; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 8px; }}
    p  {{ color: #555; line-height: 1.6; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px;
            font-size: .9rem; }}
    pre  {{ background: #f4f4f4; padding: 14px; border-radius: 6px;
            overflow-x: auto; font-size: .85rem; }}
    .step {{ margin-top: 20px; }}
    .home-btn {{
      display: inline-block; margin-top: 28px;
      background: #1a1a1a; color: #fff; text-decoration: none;
      border-radius: 8px; padding: 10px 20px; font-size: .9rem;
    }}
    .home-btn:hover {{ background: #333; }}
  </style>
</head>
<body>
  <h1>✓ Signed out of jobContextMCP</h1>
  <p>Your Microsoft account session has been cleared.</p>
  <p>To fully log out and allow a different account to connect, also clear
     the local token cache that Claude Desktop stores on this machine:</p>
  <div class="step">
    <strong>1. Open a terminal and run:</strong>
    <pre>rm -rf "{mcp_auth_path}"</pre>
  </div>
  <div class="step">
    <strong>2. Quit and reopen Claude Desktop.</strong><br>
    <p style="margin-top:6px">Claude Desktop will re-authenticate on next start
    and open a new browser login prompt.</p>
  </div>
  <a class="home-btn" href="/dashboard/login">Sign in again</a>
</body>
</html>"""
    return HTMLResponse(content=html)
