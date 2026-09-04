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

import base64
import hashlib
import hmac
import html as _html
import os
import secrets
import time
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

router = APIRouter(tags=["oauth-discovery"])


# ── ChatGPT key bridge ────────────────────────────────────────────────────────
# ChatGPT's MCP connector speaks only OAuth (authorization-code + PKCE) or
# no-auth — it has nowhere to paste a static API key, and it cannot complete
# the Entra proxy flow unless its callback URI is registered on the Entra app.
# This bridge fronts the EXISTING per-user API-key system (lib.api_keys) with
# a minimal code flow instead: consent is the jc_session cookie, and the
# access_token the client walks away with IS a freshly minted jcmcp_ key —
# which /mcp already accepts and partition-scopes via lookup_key().  Entra is
# never involved; requests whose redirect_uri is not on the bridge allowlist
# take the Entra proxy path below, byte-for-byte unchanged.
#
# The issued key never expires (no refresh_token is returned) — the same
# deliberate trade the mobile app made on 2026-07-17 — and shows up on the
# dashboard's API Keys tab labeled "ChatGPT connector", revocable there.

_BRIDGE_CODE_PREFIX = "jcac_"
_BRIDGE_CODE_TTL_SECONDS = 120
_BRIDGE_KEY_LABEL = "ChatGPT connector"
_BRIDGE_DEFAULT_REDIRECTS = (
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://chat.openai.com/connector_platform_oauth_redirect",
)

# Pending one-time codes: code → {oid, redirect_uri, code_challenge, expires}.
# In-process is sufficient: deploys are single-pod (Recreate strategy) and a
# code only lives for the seconds between consent redirect and token exchange;
# a deploy in that window just means clicking Connect again.
_bridge_codes: dict[str, dict] = {}


def _bridge_enabled() -> bool:
    """The bridge only makes sense where the jc_session cookie carries a
    per-user identity — i.e. Entra mode.  In API-key/desktop mode there is
    no per-user consent to give."""
    return bool(os.environ.get("ENTRA_CLIENT_ID"))


def _bridge_redirect_uris() -> frozenset[str]:
    """Exact-match allowlist of callback URIs the bridge will release codes
    to.  Overridable via KEYBRIDGE_REDIRECT_URIS (comma-separated) in case
    ChatGPT's callback changes."""
    raw = os.environ.get("KEYBRIDGE_REDIRECT_URIS", "")
    if raw.strip():
        return frozenset(u.strip() for u in raw.split(",") if u.strip())
    return frozenset(_BRIDGE_DEFAULT_REDIRECTS)


def _mint_bridge_code(oid: str, redirect_uri: str, code_challenge: str) -> str:
    now = time.time()
    # Opportunistic purge so abandoned consents don't accumulate.
    for stale in [c for c, rec in _bridge_codes.items() if rec["expires"] < now]:
        _bridge_codes.pop(stale, None)
    code = _BRIDGE_CODE_PREFIX + secrets.token_urlsafe(24)
    _bridge_codes[code] = {
        "oid": oid,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "expires": now + _BRIDGE_CODE_TTL_SECONDS,
    }
    return code


def _consume_bridge_code(code: str) -> dict | None:
    """Single-use: the code is removed whether or not it is still valid."""
    rec = _bridge_codes.pop(code, None)
    if rec is None or rec["expires"] < time.time():
        return None
    return rec


def _pkce_matches(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii", "ignore")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, code_challenge)


def _granted_scope(client_id: str) -> str:
    """The scope this deployment issues tokens for.

    Single source of truth: /oauth/register advertises it, and a refresh that
    arrives without a scope is re-issued against it (see `_scope_for_refresh`).
    If those two ever disagree, Entra rejects the refresh as a scope the user
    never consented to.
    """
    return f"api://{client_id}/access openid profile offline_access"


def _scope_for_refresh() -> str:
    """Scope to attach to a refresh_token grant that arrived without one.

    RFC 6749 §6 makes `scope` OPTIONAL on a refresh — omit it and you get the
    originally granted scope — so clients legitimately leave it out, and
    Claude's connector does.  Entra v2.0 does not implement that default: with
    no scope it cannot resolve a resource, falls back to the calling app
    itself, and answers

        400 AADSTS90009: Application '<client_id>' (api://<client_id>) is
        requesting a token for itself.

    which is fatal in a way nothing upstream can retry around.  The access
    token simply expires, the refresh fails, and the connector is dead until
    someone reconnects it by hand — observed on every token lifetime between
    2026-08-05 and 2026-08-10 (docs/connector-resilience.md, "Defect 3").

    The authorization_code exchange is unaffected and deliberately left alone:
    the code already carries the scope consented to at /oauth/authorize.

    Returns "" when ENTRA_CLIENT_ID is unset, so local/API-key deployments
    forward the body untouched.
    """
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    return _granted_scope(client_id) if client_id else ""


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
            "scope": _granted_scope(client_id),
        },
        status_code=201,
    )


def _bridge_consent_response(request: Request) -> Response:
    """Consent step of the key bridge (see module comment above).

    Identity comes ONLY from the middleware-established user context (the
    validated jc_session cookie) — never from anything in the query string.
    Unauthenticated browsers bounce through /dashboard/login and land back
    here with the full authorize query intact.
    """
    from lib.user_context import get_current_user_oid

    qp = request.query_params
    redirect_uri = qp.get("redirect_uri", "")
    state = qp.get("state", "")
    code_challenge = qp.get("code_challenge", "")
    method = qp.get("code_challenge_method", "")

    if not code_challenge or method != "S256":
        return JSONResponse(
            {"error": "invalid_request", "error_description": "PKCE with S256 is required"},
            status_code=400,
        )

    oid = get_current_user_oid()
    if not oid:
        next_url = quote(f"{request.url.path}?{request.url.query}", safe="")
        return RedirectResponse(url=f"/dashboard/login?next={next_url}", status_code=303)

    esc = _html.escape
    cancel_qs = urlencode({"error": "access_denied", "state": state} if state else {"error": "access_denied"})
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect ChatGPT — jobContextMCP</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; max-width: 480px;
           margin: 80px auto; padding: 0 24px; color: #1a1a1a; }}
    h1 {{ font-size: 1.3rem; margin-bottom: 8px; }}
    p  {{ color: #555; line-height: 1.6; }}
    .actions {{ display: flex; gap: 12px; margin-top: 28px; }}
    .approve {{ background: #1a1a1a; color: #fff; border: none;
               border-radius: 8px; padding: 10px 22px; font-size: .95rem;
               cursor: pointer; }}
    .approve:hover {{ background: #333; }}
    .cancel {{ display: inline-block; color: #555; text-decoration: none;
              border: 1px solid #ccc; border-radius: 8px; padding: 10px 22px;
              font-size: .95rem; }}
  </style>
</head>
<body>
  <h1>Connect ChatGPT to your jobContext workspace?</h1>
  <p>ChatGPT is asking for access to the workspace you are signed in to.
     Approving creates an API key labeled &ldquo;{esc(_BRIDGE_KEY_LABEL)}&rdquo;
     that you can revoke any time from the dashboard&rsquo;s API Keys tab.</p>
  <form method="post" action="/oauth/authorize/approve">
    <input type="hidden" name="redirect_uri" value="{esc(redirect_uri)}">
    <input type="hidden" name="state" value="{esc(state)}">
    <input type="hidden" name="code_challenge" value="{esc(code_challenge)}">
    <div class="actions">
      <button class="approve" type="submit">Approve</button>
      <a class="cancel" href="{esc(redirect_uri)}?{esc(cancel_qs)}">Cancel</a>
    </div>
  </form>
</body>
</html>"""
    return HTMLResponse(page)


@router.post("/oauth/authorize/approve", include_in_schema=False)
async def oauth_bridge_approve(request: Request) -> Response:
    """Mint a one-time code after the user approves the bridge consent page.

    The oid is read from the authenticated request context; the form only
    carries the OAuth round-trip parameters, and the redirect_uri is
    re-validated against the allowlist so a tampered form can't aim the
    code anywhere else.
    """
    from lib.user_context import get_current_user_oid

    if not _bridge_enabled():
        return JSONResponse({"error": "invalid_request"}, status_code=404)

    # The only legitimate sender is our own consent page. A cross-site form
    # POST carries Sec-Fetch-Site: cross-site (same stance as the /mcp guard:
    # no header at all means a non-browser client, which can't be CSRF'd).
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site and fetch_site not in ("same-origin", "none"):
        return JSONResponse({"error": "invalid_request"}, status_code=403)

    oid = get_current_user_oid()
    if not oid:
        return JSONResponse({"error": "access_denied"}, status_code=401)

    form = await request.form()
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))
    code_challenge = str(form.get("code_challenge", ""))

    if redirect_uri not in _bridge_redirect_uris() or not code_challenge:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    code = _mint_bridge_code(oid, redirect_uri, code_challenge)
    params = {"code": code, "state": state} if state else {"code": code}
    return RedirectResponse(url=f"{redirect_uri}?{urlencode(params)}", status_code=303)


def _bridge_token_response(payload: dict) -> JSONResponse:
    """Exchange a bridge code for a freshly minted jcmcp_ API key."""
    from lib.api_keys import create_key

    if payload.get("grant_type") != "authorization_code":
        # The bridge issues no refresh tokens; a jcmcp_ key doesn't expire.
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    rec = _consume_bridge_code(str(payload.get("code", "")))
    if rec is None:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    if str(payload.get("redirect_uri", "")) != rec["redirect_uri"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    if not _pkce_matches(str(payload.get("code_verifier", "")), rec["code_challenge"]):
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    _key_id, plaintext = create_key(rec["oid"], label=_BRIDGE_KEY_LABEL)
    return JSONResponse(
        {"access_token": plaintext, "token_type": "bearer"},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.get("/oauth/authorize", include_in_schema=False)
async def oauth_authorize_proxy(request: Request) -> Response:
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
    # ChatGPT's callback URIs divert to the key bridge; everything else
    # (Claude.ai, Cursor, VS Code, mcp-remote) proceeds to Entra unchanged.
    if _bridge_enabled() and request.query_params.get("redirect_uri", "") in _bridge_redirect_uris():
        return _bridge_consent_response(request)

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
    """Reshape the token exchange POST for Entra v2.0 and forward it.

    Two fixups, both for the same reason: the MCP client speaks RFC 6749 and
    Entra v2.0 does not accept it verbatim.

    1. Strip 'resource'.  mcp-remote sends resource=<server-origin> in the
       body; Entra throws AADSTS9010010 when 'resource' and 'scope' reference
       different application identifiers.

    2. Supply 'scope' on a refresh.  See `_scope_for_refresh`.
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

    # Bridge codes are exchanged locally — Entra never sees them.
    if str(payload.get("code", "")).startswith(_BRIDGE_CODE_PREFIX):
        return _bridge_token_response(payload)

    if payload.get("grant_type") == "refresh_token" and not payload.get("scope"):
        scope = _scope_for_refresh()
        if scope:
            payload["scope"] = scope
            _log.info("oauth/token: supplied scope for a refresh that omitted it")

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
    Visit https://app.jobcontext.ai/logout in a browser.
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
            "https://app.jobcontext.ai",
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
