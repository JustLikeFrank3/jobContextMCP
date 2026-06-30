"""JSON API for the React dashboard SPA.

GET /api/dashboard/home
    Returns the data the React Home screen renders: welcome name, Oura
    readiness (or null), pipeline summary, daily digest, in the exact shape
    src/screens/Home.jsx expects. All logic is reused from the legacy
    server-rendered home module so both stay in sync.
"""
from __future__ import annotations

import datetime
import html
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lib import config
from lib.api_keys import create_key, list_keys, revoke_key
from lib.io import _load_json
from transport.http.auth import require_api_key, require_authenticated_user
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

router = APIRouter(prefix="/api/dashboard", tags=["dashboard-api"], dependencies=[Depends(require_api_key)])


def _first_name(user: User) -> str:
    raw = (user.name or "").strip()
    if raw.lower() in ("api-key", ""):
        return "there"
    return raw.split()[0]


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
            "name": html.escape((user.name or "").strip()),
            "firstName": html.escape(_first_name(user)),
        }
    )


@router.get("/home", response_model=None)
async def dashboard_home_data(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    snap = _build_snapshot()
    oura = _load_oura()

    priorities = [
        {"n": str(i + 1), "text": p}
        for i, p in enumerate(snap.get("priorities", []))
    ]

    payload = {
        "welcomeName": html.escape(_first_name(user)),
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
    try:
        from lib.user_context import get_data_folder_override

        override = get_data_folder_override()
        if not override:
            return False
        cfg_path = override / "config.json"
        if not cfg_path.exists():
            return False
        import json

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return bool((cfg.get("openai_api_key") or "").strip())
    except Exception:
        return False


@router.get("/settings", response_model=None)
async def settings_summary(
    user: Annotated[User, Depends(require_authenticated_user)],
) -> JSONResponse:
    return JSONResponse(
        {
            "isOwner": _is_owner(),
            "openaiKeySet": _openai_key_set(),
            "ouraConnected": _load_oura() is not None,
            "classicUrl": "/dashboard/settings",
        }
    )

