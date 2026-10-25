"""Dashboard login routes for browser-based auth.

Two modes depending on the active AuthProvider:

  ApiKeyAuthProvider — shows an API key form; sets jc_session cookie on
    successful submit.

  EntraAuthProvider  — GET /login redirects straight to Entra PKCE;
    GET /callback exchanges the auth code for a token and sets jc_session.
"""
from __future__ import annotations

import html
import hashlib
import os
import re
import secrets
from typing import Annotated
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from transport.http.security import EntraAuthProvider, get_auth_provider

_SERVER_BASE = os.environ.get(
    "SERVER_BASE_URL", "https://app.jobcontext.ai"
)

router = APIRouter()


def _is_secure(request: Request) -> bool:
    """Return True when the connection is HTTPS.

    Checks X-Forwarded-Proto first so the flag is correct when running behind
    a TLS-terminating ingress (AKS nginx, Azure App Gateway, etc.) where
    request.url.scheme is always 'http' at the pod level.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.lower() == "https"
    return request.url.scheme == "https"

_DASHBOARD_ROOT = "/dashboard"
_LOGIN_PATH = "/dashboard/login"
_LOGIN_CSRF_COOKIE = "jc_login_csrf"
_LOGIN_CSRF_SECONDS = 600


def _csrf_cookie_name(request: Request) -> str:
    # __Host- requires Secure, Path=/ and no Domain: a sibling subdomain
    # cannot inject the pre-login challenge into a TLS browser session.
    return f"__Host-{_LOGIN_CSRF_COOKIE}" if _is_secure(request) else _LOGIN_CSRF_COOKIE


def _validate_login_csrf(request: Request, token: str) -> None:
    """Require the browser's pre-login challenge AND a same-origin submit.

    The cookie is HttpOnly and never sufficient on its own. The hidden form
    field proves that the submitter read the login page. Origin/Fetch Metadata
    checks additionally prevent cookie-injection attacks, including HTTP local
    mode where the browser cannot use a Secure __Host- cookie.
    """
    cookie = request.cookies.get(_csrf_cookie_name(request), "")
    valid_token = re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    if not valid_token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie) or not secrets.compare_digest(cookie, token):
        raise HTTPException(403, "Login form expired or invalid; reload the sign-in page")

    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site and fetch_site != "same-origin":
        raise HTTPException(403, "Submit the sign-in form from this site")
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        try:
            origin = urlsplit(source)
            same_origin = (
                origin.scheme == ("https" if _is_secure(request) else "http")
                and origin.netloc.lower() == request.headers.get("host", "").lower()
                and origin.username is None and origin.password is None
            )
        except ValueError:
            same_origin = False
        if not same_origin:
            raise HTTPException(403, "Submit the sign-in form from this site")
    elif fetch_site != "same-origin":
        # This is a browser-only form, not an API-key authentication endpoint.
        # Old clients can use Referer; clients with no provenance fail closed.
        raise HTTPException(403, "Submit the sign-in form from this site")


def _login_message(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    """Render trusted/escaped login messages without inline CSS."""
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title>'
        '<link rel="stylesheet" href="/static/dashboard-login.css">'
        f'</head><body><main class="card"><h2>{title}</h2>{body}</main></body></html>',
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )

# Internal destinations a post-login redirect may land on. The React SPA lives
# under /app, the legacy server-rendered dashboard under /dashboard, and
# /oauth/authorize is the ChatGPT key-bridge consent page, which sends
# unauthenticated browsers through here and needs to get back with its
# query string intact. Anything else (external URLs, protocol-relative
# //host) falls back to the SPA.
_ALLOWED_NEXT_PREFIXES = (_DASHBOARD_ROOT, "/app", "/oauth/authorize")

# Default post-login destination: the React SPA. Auth flows that arrive without
# an explicit (and safe) next target land here, not on the legacy /dashboard
# pages. The classic pages stay reachable via their /dashboard links.
_DEFAULT_NEXT = "/app"


def _safe_next(next_url: str | None) -> str:
    if (
        next_url
        and next_url.startswith("/")
        and not next_url.startswith("//")
        and any(next_url.startswith(p) for p in _ALLOWED_NEXT_PREFIXES)
    ):
        return next_url
    return _DEFAULT_NEXT


@router.get("/login", response_model=None)
async def dashboard_login_page(request: Request, next: str = _DEFAULT_NEXT) -> HTMLResponse | RedirectResponse:
  provider = get_auth_provider()

  # Entra mode: skip the form, go straight to PKCE
  if isinstance(provider, EntraAuthProvider):
    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    verifier = secrets.token_urlsafe(64)
    import base64
    challenge_b64 = base64.urlsafe_b64encode(
      hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    params = urlencode({
      "client_id": client_id,
      "response_type": "code",
      "redirect_uri": f"{_SERVER_BASE}/dashboard/callback",
      "scope": f"api://{client_id}/access openid profile",
      "response_mode": "query",
      "code_challenge": challenge_b64,
      "code_challenge_method": "S256",
      "state": next,
    })
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{params}"
    resp = RedirectResponse(url=auth_url, status_code=302)
    # Store verifier in a short-lived cookie for the callback
    resp.set_cookie("pkce_verifier", verifier, httponly=True, samesite="lax",
                    secure=_is_secure(request), max_age=600, path="/")
    return resp

  if not provider.auth_enabled:
    return _login_message(
      "Authentication disabled",
      '<p>API_KEY is not set. Login is not required.</p>'
      f'<p><a href="{_DEFAULT_NEXT}">Open dashboard</a></p>',
    )

  next_url = _safe_next(next)
  safe_next_url = html.escape(next_url, quote=True)
  csrf_token = secrets.token_urlsafe(32)
  page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContextMCP — Dashboard Login</title>
  <link rel="stylesheet" href="/static/dashboard-login.css" />
</head>
<body>
  <form class="card" method="post" action="{_LOGIN_PATH}">
    <h1>Dashboard Login</h1>
    <p>Enter your API key to create a browser session on this device.</p>
    <input type="hidden" name="next" value="{safe_next_url}" />
    <input type="hidden" name="csrf_token" value="{csrf_token}" />
    <label for="api_key">API key</label>
    <input id="api_key" name="api_key" type="password" autocomplete="current-password" required />
    <button type="submit">Sign in</button>
    <div class="hint">Cookie is HTTP-only and stored for 30 days on this browser.</div>
  </form>
</body>
</html>"""
  response = HTMLResponse(page_html, headers={"Cache-Control": "no-store"})
  response.set_cookie(
      _csrf_cookie_name(request), csrf_token, httponly=True, samesite="strict",
      secure=_is_secure(request), max_age=_LOGIN_CSRF_SECONDS, path="/",
  )
  return response


@router.post("/login")
async def dashboard_login_submit(
    request: Request,
  api_key: Annotated[str, Form()],
  next: Annotated[str, Form()] = _DEFAULT_NEXT,
  csrf_token: Annotated[str, Form()] = "",
) -> RedirectResponse:
    provider = get_auth_provider()
    next_url = _safe_next(next)

    if not provider.auth_enabled:
        return RedirectResponse(url=next_url, status_code=303)

    # Entra uses its own PKCE GET/callback flow and never renders this form.
    if not isinstance(provider, EntraAuthProvider):
        _validate_login_csrf(request, csrf_token)

    login_result = provider.authenticate_login(api_key)
    if not login_result:
        return RedirectResponse(url=f"{_LOGIN_PATH}?next={next_url}", status_code=303)

    _, session_token = login_result

    resp = RedirectResponse(url=next_url, status_code=303)
    resp.delete_cookie(
        _csrf_cookie_name(request), path="/", httponly=True, samesite="strict",
        secure=_is_secure(request),
    )
    resp.headers["Cache-Control"] = "no-store"
    secure_cookie = _is_secure(request)
    resp.set_cookie(
        key="jc_session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return resp


@router.post("/logout")
async def dashboard_logout(request: Request) -> RedirectResponse:
    provider = get_auth_provider()

    if isinstance(provider, EntraAuthProvider):
        # Redirect to Entra's end-session endpoint so the SSO session is
        # cleared server-side.  Without this, hitting /login again bounces
        # straight back through PKCE and the user is re-authed silently.
        # post_logout_redirect_uri must be registered as an allowed logout
        # redirect URI in the Entra app registration.
        tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
        post_logout_uri = f"{_SERVER_BASE}/"
        params = urlencode({"post_logout_redirect_uri": post_logout_uri})
        redirect_url = (
            f"https://login.microsoftonline.com/{tenant_id}"
            f"/oauth2/v2.0/logout?{params}"
        )
    else:
        redirect_url = _LOGIN_PATH

    resp = RedirectResponse(url=redirect_url, status_code=303)
    resp.delete_cookie(
        "jc_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
    )
    return resp


@router.get("/callback", response_model=None)
async def dashboard_entra_callback(
    request: Request,
    code: str = "",
    state: str = _DEFAULT_NEXT,
    error: str = "",
) -> RedirectResponse | HTMLResponse:
    """Handle Entra PKCE callback, exchange code for token, set jc_session cookie."""
    if error:
        safe_error = html.escape(error)
        return _login_message(
            "Login failed", f'<p>{safe_error}</p>'
            f'<p><a href="{_LOGIN_PATH}">Try again</a></p>', status_code=400,
        )

    verifier = request.cookies.get("pkce_verifier", "")
    if not code or not verifier:
        return RedirectResponse(url=_LOGIN_PATH, status_code=302)

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    if not client_secret:
        return _login_message(
            "Server auth not configured",
            '<p>ENTRA_CLIENT_SECRET is missing in runtime configuration.</p>'
            f'<p><a href="{_LOGIN_PATH}">Try again</a></p>', status_code=500,
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data={
            "grant_type": "authorization_code",
            "client_id": client_id,
          "client_secret": client_secret,
            "code": code,
            "redirect_uri": f"{_SERVER_BASE}/dashboard/callback",
            "code_verifier": verifier,
            "scope": f"api://{client_id}/access openid profile",
        })

    if resp.status_code != 200:
        safe_response_text = html.escape(resp.text[:400])
        return _login_message(
            "Token exchange failed", f'<pre>{safe_response_text}</pre>'
            f'<p><a href="{_LOGIN_PATH}">Try again</a></p>', status_code=400,
        )

    tokens = resp.json()
    access_token = tokens.get("access_token", "")

    next_url = _safe_next(state)
    redirect = RedirectResponse(url=next_url, status_code=303)
    secure = _is_secure(request)
    redirect.set_cookie(
        key="jc_session",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=60 * 60,  # 1h — matches Entra token lifetime
        path="/",
    )
    redirect.delete_cookie("pkce_verifier", path="/")
    return redirect
