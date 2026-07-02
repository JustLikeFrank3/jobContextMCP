"""Oura Ring OAuth connect flow (browser).

  GET /dashboard/oura/connect   — start the OAuth handshake: set a state cookie
                                  and redirect the browser to Oura's consent
                                  screen.
  GET /dashboard/oura/callback  — Oura redirects here with ?code&state. We
                                  verify state, exchange the code for tokens,
                                  store them per-OID, do a first sync, then
                                  bounce back to the React Settings screen.

The matching JSON actions the SPA calls itself (sync / disconnect) live in
transport/http/routes/dashboard/api.py under /api/dashboard/oura/*.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from transport.http.auth import require_authenticated_user
from transport.http.security import User

import tools.oura as oura

router = APIRouter(dependencies=[Depends(require_authenticated_user)])

_SERVER_BASE = os.environ.get("SERVER_BASE_URL", "https://app.jobcontext.ai")
_CALLBACK_PATH = "/dashboard/oura/callback"
_SETTINGS = "/app/settings"
_STATE_COOKIE = "oura_state"


def _is_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        return forwarded.lower() == "https"
    return request.url.scheme == "https"


def _settings_redirect(status: str) -> RedirectResponse:
    """Redirect back to the SPA Settings screen with an outcome flag."""
    resp = RedirectResponse(url=f"{_SETTINGS}?oura={status}", status_code=303)
    resp.delete_cookie(_STATE_COOKIE, path="/")
    return resp


@router.get("/oura/connect", response_model=None)
async def oura_connect(
    request: Request,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> RedirectResponse:
    """Begin the Oura OAuth handshake."""
    if not oura.oura_configured():
        return _settings_redirect("unavailable")

    state = secrets.token_urlsafe(32)
    redirect_uri = f"{_SERVER_BASE}{_CALLBACK_PATH}"
    auth_url = oura.oura_authorize_url(state, redirect_uri)

    resp = RedirectResponse(url=auth_url, status_code=302)
    resp.set_cookie(
        _STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        max_age=600,
        path="/",
    )
    return resp


@router.get("/oura/callback", response_model=None)
async def oura_callback(
    request: Request,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Handle Oura's redirect: verify state, exchange code, store tokens, sync."""
    if error or not code:
        return _settings_redirect("error")

    expected = request.cookies.get(_STATE_COOKIE, "")
    if not expected or not secrets.compare_digest(expected, state):
        return _settings_redirect("error")

    redirect_uri = f"{_SERVER_BASE}{_CALLBACK_PATH}"
    try:
        tokens = await asyncio.to_thread(oura.exchange_code_for_tokens, code, redirect_uri)
        await asyncio.to_thread(oura.save_oura_tokens, tokens)
    except oura.OuraError:
        return _settings_redirect("error")

    # First sync is best-effort: a connected ring with no data yet still counts
    # as connected; the user can Sync now later from Settings.
    try:
        await asyncio.to_thread(oura.sync_oura)
    except Exception:  # noqa: BLE001 — never fail the connect on a sync hiccup
        pass

    return _settings_redirect("connected")
