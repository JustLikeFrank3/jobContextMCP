"""Dashboard login routes for browser-based auth.

Two modes depending on the active AuthProvider:

  ApiKeyAuthProvider — shows an API key form; sets jc_session cookie on
    successful submit.

  EntraAuthProvider  — GET /login redirects straight to Entra PKCE;
    GET /callback exchanges the auth code for a token and sets jc_session.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from transport.http.security import EntraAuthProvider, get_auth_provider

_SERVER_BASE = os.environ.get(
    "SERVER_BASE_URL", "https://jobcontextmcp.eastus.cloudapp.azure.com"
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


def _safe_next(next_url: str | None) -> str:
    if next_url and next_url.startswith(_DASHBOARD_ROOT):
        return next_url
    return _DASHBOARD_ROOT


@router.get("/login", response_model=None)
async def dashboard_login_page(request: Request, next: str = _DASHBOARD_ROOT) -> HTMLResponse | RedirectResponse:
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
    return HTMLResponse(
      '<!doctype html><meta charset="utf-8"><title>Dashboard Login</title>'
      '<body style="font-family:Inter,Arial,sans-serif;background:#0b1220;color:#e6edf7;padding:24px">'
      '<h2>Authentication disabled</h2>'
      '<p>API_KEY is not set. Login is not required.</p>'
      f'<p><a href="{_DASHBOARD_ROOT}" style="color:#3FA8A8">Open dashboard</a></p>'
      '</body>',
      status_code=200,
    )

  next_url = _safe_next(next)
  html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContextMCP — Dashboard Login</title>
  <style>
    :root {{
      --bg: #0b1220; --panel: #111a2b; --line: #23324d;
      --text: #e6edf7; --muted: #9aa8bf; --accent: #3FA8A8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: linear-gradient(180deg, #0b1220 0%, #0a1020 100%);
      color: var(--text);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      padding: 16px;
    }}
    .card {{
      width: 100%; max-width: 420px; background: var(--panel);
      border: 1px solid var(--line); border-radius: 14px; padding: 20px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 1.1rem; }}
    p {{ margin: 0 0 14px; color: var(--muted); font-size: .88rem; line-height: 1.45; }}
    label {{ display: block; margin: 0 0 8px; font-size: .82rem; color: var(--muted); }}
    input {{
      width: 100%; background: #0e1628; color: var(--text);
      border: 1px solid var(--line); border-radius: 10px;
      padding: 10px 12px; font-size: .92rem; margin: 0 0 12px;
    }}
    button {{
      width: 100%; border: 0; border-radius: 10px; padding: 10px 12px;
      background: var(--accent); color: #0b1220; font-weight: 700; cursor: pointer;
    }}
    .hint {{ margin-top: 12px; color: var(--muted); font-size: .78rem; }}
  </style>
</head>
<body>
  <form class="card" method="post" action="{_LOGIN_PATH}">
    <h1>Dashboard Login</h1>
    <p>Enter your API key to create a browser session on this device.</p>
    <input type="hidden" name="next" value="{next_url}" />
    <label for="api_key">API key</label>
    <input id="api_key" name="api_key" type="password" autocomplete="current-password" required />
    <button type="submit">Sign in</button>
    <div class="hint">Cookie is HTTP-only and stored for 30 days on this browser.</div>
  </form>
</body>
</html>"""
  return HTMLResponse(html)


@router.post("/login")
async def dashboard_login_submit(
    request: Request,
  api_key: Annotated[str, Form()],
  next: Annotated[str, Form()] = _DASHBOARD_ROOT,
) -> RedirectResponse:
    provider = get_auth_provider()
    next_url = _safe_next(next)

    if not provider.auth_enabled:
        return RedirectResponse(url=next_url, status_code=303)

    login_result = provider.authenticate_login(api_key)
    if not login_result:
        return RedirectResponse(url=f"{_LOGIN_PATH}?next={next_url}", status_code=303)

    _, session_token = login_result

    resp = RedirectResponse(url=next_url, status_code=303)
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
    state: str = _DASHBOARD_ROOT,
    error: str = "",
) -> RedirectResponse | HTMLResponse:
    """Handle Entra PKCE callback, exchange code for token, set jc_session cookie."""
    if error:
        return HTMLResponse(
            f'<html><body style="font-family:sans-serif;background:#0b1220;color:#e6edf7;padding:24px">'
            f'<h2>Login failed</h2><p>{error}</p>'
            f'<p><a href="{_LOGIN_PATH}" style="color:#3FA8A8">Try again</a></p></body></html>',
            status_code=400,
        )

    verifier = request.cookies.get("pkce_verifier", "")
    if not code or not verifier:
        return RedirectResponse(url=_LOGIN_PATH, status_code=302)

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    if not client_secret:
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0b1220;color:#e6edf7;padding:24px">'
            '<h2>Server auth not configured</h2>'
            '<p>ENTRA_CLIENT_SECRET is missing in runtime configuration.</p>'
            f'<p><a href="{_LOGIN_PATH}" style="color:#3FA8A8">Try again</a></p></body></html>',
            status_code=500,
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
        return HTMLResponse(
            '<html><body style="font-family:sans-serif;background:#0b1220;color:#e6edf7;padding:24px">'
            '<h2>Token exchange failed</h2>'
            f'<pre>{resp.text[:400]}</pre>'
            f'<p><a href="{_LOGIN_PATH}" style="color:#3FA8A8">Try again</a></p></body></html>',
            status_code=400,
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
