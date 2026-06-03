"""Dashboard login routes for browser-based auth.

Provides a simple API-key form that sets an HTTP-only cookie (`jc_session`) so
mobile Safari / browser sessions can access protected dashboard routes without
manually sending Authorization headers.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from transport.http.security import get_auth_provider

router = APIRouter()

_DASHBOARD_ROOT = "/dashboard"
_LOGIN_PATH = "/dashboard/login"


def _safe_next(next_url: str | None) -> str:
    if next_url and next_url.startswith(_DASHBOARD_ROOT):
        return next_url
    return _DASHBOARD_ROOT


@router.get("/login")
async def dashboard_login_page(next: str = _DASHBOARD_ROOT) -> HTMLResponse:
  provider = get_auth_provider()
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
    <input type="text" name="username" value="frank" autocomplete="username" style="display:none" />
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
    secure_cookie = request.url.scheme == "https"
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
async def dashboard_logout() -> RedirectResponse:
    resp = RedirectResponse(url=_LOGIN_PATH, status_code=303)
    resp.delete_cookie("jc_session", path="/")
    return resp
