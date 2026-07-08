"""JSON API for the React dashboard SPA.

GET /api/dashboard/home
    Returns the data the React Home screen renders: welcome name, Oura
    readiness (or null), pipeline summary, daily digest, in the exact shape
    src/screens/Home.jsx expects. All logic is reused from the legacy
    server-rendered home module so both stay in sync.
"""
from __future__ import annotations

import asyncio
import datetime
import html  # noqa: F401  (retained for potential HTML responses)
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lib import config
from lib.api_keys import create_key, list_keys, revoke_key
from lib.io import _load_json
from transport.http.auth import require_authenticated_user
from transport.http.security import User

from tools.digest import (
    _load_apps,
    _load_queue,
    _is_closed,
    _is_waiting,
    _days_since,
)
from .home import (
    _build_snapshot,
    _load_oura,
    _readiness_color_and_label,
    _today_move_text,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard-api"])


def _first_name(user: User) -> str:
    raw = (user.name or "").strip()
    if raw.lower() in ("api-key", ""):
        return "there"
    return raw.split()[0]


def _welcome(user: User) -> "tuple[str, bool]":
    """(greeting name, is_default) for the Home header.

    Desktop has no identity provider — its synthetic auth user is "Admin" —
    so greet with the contact name from config.json instead. That block is
    exactly what setup_workspace fills in, so the placeholder (and the
    onboarding CTA the frontend hangs off is_default) disappears once the
    user finishes setup.
    """
    from lib.app_dirs import is_desktop_mode

    if is_desktop_mode():
        try:
            from lib.config import get_contact_info

            contact = (get_contact_info().get("name") or "").strip()
        except Exception:  # noqa: BLE001 — greeting must never break Home
            contact = ""
        if contact:
            return contact.split()[0], False
        return "user", True
    name = _first_name(user)
    return name, name == "there"


def _oura_payload(oura: "dict | None") -> "dict | None":
    """Shape the Oura row into the frontend's oura object, or None."""
    if not oura:
        return None
    score = int(oura.get("readiness_score", 0))
    sleep_s = int(oura.get("sleep_score", 0))
    hrv = int(oura.get("hrv", 0))
    recovery = int(oura.get("recovery_index", 0))
    _color, label = _readiness_color_and_label(score)
    return {
        "score": score,
        "label": label,
        "bars": [
            {"label": "Sleep score", "val": sleep_s, "unit": "", "pct": min(sleep_s, 100), "tone": "accent"},
            {"label": "HRV", "val": hrv, "unit": "ms", "pct": min(hrv, 100), "tone": "accent"},
            {"label": "Recovery index", "val": recovery, "unit": "", "pct": min(recovery, 100), "tone": "green"},
        ],
    }


def _interview_today() -> "str | None":
    """Return the company of an interview scheduled for today, if any."""
    try:
        data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
        today = datetime.date.today().isoformat()
        for iv in data.get("interviews", []):
            if (iv.get("interview_date", "") or "")[:10] == today:
                return iv.get("company") or "Scheduled"
    except Exception:
        pass
    return None


def _digest_payload(snap: dict) -> dict:
    """Build the daily-digest items shown when no Oura ring is connected."""
    today = datetime.date.today()
    date_line = f"{today.strftime('%A, %B %-d')} \u00b7 Morning briefing"

    # Stale = active, not waiting on them, untouched 14+ days.
    try:
        apps = _load_apps()
        active = [a for a in apps if not _is_closed(a)]
        stale = sum(
            1 for a in active
            if not _is_waiting(a) and _days_since(a.get("last_updated", "")) >= 14
        )
    except Exception:
        stale = 0

    try:
        queue = _load_queue()
        assessments_ready = sum(1 for j in queue if j.get("status") == "evaluated")
    except Exception:
        assessments_ready = snap.get("undecided", 0)

    items = [
        {"label": "Follow-ups due", "value": str(snap.get("overdue", 0)), "color": "var(--warn)"},
    ]
    iv_today = _interview_today()
    if iv_today:
        items.append({"label": "Interview today", "value": iv_today, "color": "var(--cyan-300)"})
    items.append({"label": "Stale applications", "value": str(stale), "color": "var(--muted)"})
    items.append({"label": "New assessments ready", "value": str(assessments_ready), "color": "var(--green-300)"})

    return {"date": date_line, "items": items}


@router.get("/me", response_model=None)
async def dashboard_me(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    """Lightweight auth probe for the SPA.

    Returns 200 + the current user when the session cookie / bearer is valid,
    or 401 (via the dependency) when it is not. The React AuthContext calls
    this on mount to decide between rendering the app and redirecting to login,
    without paying for the full home payload.
    """
    return JSONResponse(
        {
            "authenticated": True,
            "id": user.id,
            "name": (user.name or "").strip(),
            "firstName": _first_name(user),
        }
    )


# ── Oura auto-sync (Home load) ──────────────────────────────────────────────
# Keep the dashboard current without a manual "Sync now": when a ring is
# connected, loading Home pulls fresh readiness from Oura. Readiness updates
# ~once/day, so the pull is throttled by last_sync_at and time-boxed, keeping
# routine navigations cheap and ensuring a slow/hung upstream can never stall
# the Home payload.
_OURA_AUTOSYNC_INTERVAL = datetime.timedelta(minutes=30)
_OURA_AUTOSYNC_TIMEOUT = 6.0


def _oura_sync_due(last_sync: str) -> bool:
    """True when the last Oura pull is missing or older than the throttle window."""
    if not last_sync:
        return True
    try:
        ts = datetime.datetime.fromisoformat(last_sync)
    except (TypeError, ValueError):
        return True  # unparseable timestamp — treat as stale and refresh
    if ts.tzinfo is not None:  # last_sync_at is naive UTC; normalize just in case
        ts = ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return (now - ts) >= _OURA_AUTOSYNC_INTERVAL


async def _auto_sync_oura(status: dict) -> None:
    """Best-effort refresh of Oura readiness on Home load.

    Connection status is token-based (no network). Only when a ring is
    connected AND the throttle window has elapsed do we make the blocking Oura
    API calls — off the event loop and under a hard timeout so the Home payload
    can never hang on a slow upstream. Any failure is swallowed; Home just
    serves the last-known readiness already in SQLite.
    """
    if not status.get("connected"):
        return
    if not _oura_sync_due(status.get("last_sync", "")):
        return
    try:
        from tools.oura import sync_oura

        await asyncio.wait_for(
            asyncio.to_thread(sync_oura), timeout=_OURA_AUTOSYNC_TIMEOUT
        )
    except Exception:  # noqa: BLE001 — auto-sync is best-effort; never fail Home
        pass


@router.get("/home", response_model=None)
async def dashboard_home_data(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    snap = _build_snapshot()
    # Refresh from Oura when connected + stale, then read the (now-current) row.
    # _auto_sync_oura is throttled + time-boxed, so this stays cheap on routine
    # navigations and safe when the Oura API is slow or down.
    status = _oura_status()
    await _auto_sync_oura(status)
    # Only surface readiness when a ring is genuinely connected. A stale or
    # zeroed oura_readiness row must never flip Home into the readiness view —
    # an unconnected user always sees the daily digest. Connection status is
    # token-based and makes no network call.
    oura = _load_oura() if (status.get("connected", False) or _oura_via_sync()) else None

    priorities = [
        {"n": str(i + 1), "text": p}
        for i, p in enumerate(snap.get("priorities", []))
    ]

    welcome_name, welcome_is_default = _welcome(user)
    payload = {
        "welcomeName": welcome_name,
        "welcomeIsDefault": welcome_is_default,
        "hasOura": oura is not None,
        "oura": _oura_payload(oura),
        "today": {
            "active": snap.get("active", 0),
            "inflight": snap.get("in_flight", 0),
            "overdue": snap.get("overdue", 0),
            "move": _today_move_text(oura, snap),
            "priorities": priorities,
        },
        "digest": _digest_payload(snap),
    }
    return JSONResponse(payload)


# ── API keys ─────────────────────────────────────────────────────────────────
# The React API Keys screen manages personal access tokens for MCP clients.
# Tokens are scoped to the caller's OID (user.id); the plaintext is shown once,
# at creation, and never stored or returned again.

class _CreateKeyBody(BaseModel):
    label: str = ""


def _key_dict(k) -> dict:
    return {
        "id": k.id,
        "label": k.label or "",
        "created_at": k.created_at or "",
        "last_used_at": k.last_used_at or "",
    }


@router.get("/api-keys", response_model=None)
async def api_keys_list(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    keys = [_key_dict(k) for k in list_keys(user.id)]
    return JSONResponse({"keys": keys})


@router.post("/api-keys", response_model=None)
async def api_keys_create(
    user: Annotated[User, Depends(require_authenticated_user)],
    body: _CreateKeyBody,
) -> JSONResponse:
    key_id, plaintext = create_key(user.id, body.label.strip())
    # plaintext is returned exactly once — the client must surface it now.
    return JSONResponse(
        {"id": key_id, "label": body.label.strip(), "token": plaintext},
        status_code=201,
    )


@router.post("/api-keys/{key_id}/revoke", response_model=None)
async def api_keys_revoke(
    key_id: int,
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    revoked = revoke_key(key_id, user.id)
    return JSONResponse({"revoked": bool(revoked)})


# ── Settings ─────────────────────────────────────────────────────────────────
# Read-only status summary for the React Settings screen. Mutations (saving an
# OpenAI key) remain on the classic /dashboard/settings page, which has the
# tenant-config write path; the React screen links to it.

def _is_owner() -> bool:
    try:
        from lib.config import OWNER_OID
        from lib.user_context import get_current_user_oid

        return bool(OWNER_OID) and get_current_user_oid() == OWNER_OID
    except Exception:
        return False


def _openai_key_set() -> bool:
    """Whether AI generation has a usable key for the active request/tenant.

    Mirrors the exact resolution used by lib.config.get_llm_client() so the
    Settings screen reports the same truth generation will actually see:
    the LLM_API_KEY env var (global override) or the active tenant's merged
    config.json openai_api_key. Works for single-tenant/local runs and the
    owner session, not just when a per-user data-folder override is active.
    """
    try:
        import os
        from lib.config import get_active_config

        api_key = os.environ.get("LLM_API_KEY") or get_active_config().get(
            "openai_api_key", ""
        )
        return bool(str(api_key or "").strip())
    except Exception:
        return False


def _oura_settings_payload(oura: "dict | None") -> "dict | None":
    """Shape the latest Oura row for the Settings screen, or None."""
    if not oura:
        return None
    return {
        "date": oura.get("date", "") or "",
        "readiness_score": int(oura.get("readiness_score", 0) or 0),
        "sleep_score": int(oura.get("sleep_score", 0) or 0),
        "hrv": int(oura.get("hrv", 0) or 0),
        "recovery_index": int(oura.get("recovery_index", 0) or 0),
    }


def _oura_via_sync() -> bool:
    """Desktop: readiness rows arriving via cloud sync count as connected.

    Oura deprecated personal access tokens, so a desktop app often has no
    local Oura credential at all — the ring is OAuth-connected on the hosted
    product and oura_readiness rows flow down through workspace sync. A
    recent row is as good as a connection for the Home hero.
    """
    from lib.app_dirs import is_desktop_mode

    if not is_desktop_mode():
        return False
    row = _load_oura()
    if not row or not row.get("date"):
        return False
    try:
        latest = datetime.date.fromisoformat(str(row["date"]))
    except ValueError:
        return False
    return (datetime.date.today() - latest).days <= 7


def _oura_status() -> dict:
    """Oura connection status (no network calls).

    Wrapped on this module so the Settings route stays import-light and tests
    can monkeypatch it, mirroring _is_owner / _openai_key_set.
    """
    try:
        from tools.oura import oura_connection_status

        return oura_connection_status()
    except Exception:
        return {"configured": False, "connected": False, "last_sync": "", "scope": ""}


@router.get("/settings", response_model=None)
async def settings_summary(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    status = _oura_status()
    return JSONResponse(
        {
            "isOwner": _is_owner(),
            "openaiKeySet": _openai_key_set(),
            "ouraConfigured": bool(status.get("configured")),
            "ouraConnected": bool(status.get("connected")) or _oura_via_sync(),
            "ouraViaSync": not status.get("connected") and _oura_via_sync(),
            "ouraLastSync": status.get("last_sync") or "",
            "oura": _oura_settings_payload(_load_oura()),
            "classicUrl": "/dashboard/settings",
        }
    )


# ── Oura Ring OAuth actions ────────────────────────────────────────────────────
# The browser connect/callback handshake lives in routes/dashboard/oura.py.
# These are the JSON actions the React Settings screen calls once a ring is
# connected: pull the latest reading on demand, or disconnect (drop tokens).
# There is no manual readiness entry from the web UI — data comes from the
# user's real Oura account via OAuth (the MCP tool remains for the iOS Shortcut).


@router.post("/oura/sync", response_model=None)
async def oura_sync(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> JSONResponse:
    """Pull the latest readiness from the connected Oura account into SQLite."""
    from tools.oura import sync_oura

    # sync_oura() does blocking httpx I/O — keep it off the event loop.
    result = await asyncio.to_thread(sync_oura)

    if result.get("error") in {"not_configured", "not_connected"}:
        status_code = 409  # actionable client state, not a server failure
    elif result.get("ok"):
        status_code = 200
    else:
        status_code = 502  # upstream Oura API / auth failure

    return JSONResponse(
        {
            "ok": bool(result.get("ok")),
            "connected": bool(result.get("connected")),
            "error": result.get("error", ""),
            "note": result.get("note", ""),
            "ouraConnected": _oura_status().get("connected", False),
            "oura": _oura_settings_payload(_load_oura()),
        },
        status_code=status_code,
    )


@router.post("/oura/disconnect", response_model=None)
async def oura_disconnect(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> JSONResponse:
    """Drop the current user's Oura OAuth tokens (disconnect the ring)."""
    from tools.oura import clear_oura_tokens

    removed = clear_oura_tokens()
    return JSONResponse({"ok": True, "removed": bool(removed), "ouraConnected": False})


# ── Workspace export ───────────────────────────────────────────────────────────
# One zip of the active user's entire data root (config.json, db/, workspace/,
# personas/). On the hosted product this is how a user pulls their cloud
# workspace down to move into the desktop app (Settings → Import); on desktop
# it doubles as a local backup.


def _active_user_root() -> "Path":
    """The directory that IS the current user's workspace, on any deployment.

    Entra sessions carry a per-user override (UserDataContextMiddleware);
    desktop is single-user with a fixed app-data dir. Anything else — e.g. an
    API-key admin session on the hosted product — has no single-user root,
    and falling back to the global DATA_FOLDER would export every tenant at
    once, so it's refused outright.
    """
    from lib.user_context import get_data_folder_override

    override = get_data_folder_override()
    if override is not None:
        return override
    from lib.app_dirs import desktop_data_dir, is_desktop_mode

    if is_desktop_mode():
        return desktop_data_dir()
    raise HTTPException(
        status_code=403,
        detail="Workspace export requires a user session (sign in via the dashboard).",
    )


@router.get("/export", response_model=None)
async def export_workspace(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
):
    """Download the whole workspace (config, SQLite DB, files) as a zip."""
    import tempfile
    import zipfile
    from pathlib import Path

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    root = _active_user_root()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="No workspace data to export yet.")

    def build() -> str:
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(root)
                # SQLite sidecar journals are point-in-time noise; the .db
                # itself is checkpointed on connection close.
                if rel.suffix in (".db-wal", ".db-shm") or rel.name.endswith(("-wal", "-shm")):
                    continue
                zf.write(path, str(rel))
        return tmp

    tmp = await asyncio.to_thread(build)
    stamp = datetime.date.today().isoformat()
    return FileResponse(
        tmp,
        media_type="application/zip",
        filename=f"jobcontext-export-{stamp}.zip",
        background=BackgroundTask(os.unlink, tmp),
    )


class OuraPatRequest(BaseModel):
    token: str


@router.post("/oura/pat", response_model=None)
async def oura_pat_connect(
    request: OuraPatRequest,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> JSONResponse:
    """Connect Oura with a Personal Access Token (desktop's auth path).

    The OAuth handshake needs server client credentials and a public HTTPS
    redirect URI registered with Oura — a local loopback app has neither, so
    the desktop pastes a PAT from cloud.ouraring.com instead. Validated
    against the Oura API before storing; a first sync runs immediately so
    the Home hero flips to readiness without waiting for the auto-sync.
    """
    from tools.oura import OuraError, save_oura_pat, sync_oura, validate_oura_pat

    token = request.token.strip()
    if not token:
        raise HTTPException(status_code=422, detail="Personal access token is empty.")
    try:
        valid = await asyncio.to_thread(validate_oura_pat, token)
    except OuraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=422,
            detail="Oura rejected that token — generate one at cloud.ouraring.com → Personal Access Tokens.",
        )
    save_oura_pat(token)
    result = await asyncio.to_thread(sync_oura)  # first pull is best-effort
    return JSONResponse(
        {
            "ok": True,
            "synced": bool(result.get("ok")),
            "ouraConnected": True,
            "oura": _oura_settings_payload(_load_oura()),
        }
    )

