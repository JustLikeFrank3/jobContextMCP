"""tools/oura.py — Oura Ring readiness data integration.

Two paths feed the same per-user ``oura_readiness`` table that the dashboard
home page reads to drive the Readiness + Pipeline hero card:

  1. OAuth integration (preferred) — the user connects their Oura account via
     the browser flow (transport/http/routes/dashboard/oura.py). Tokens are
     stored per-OID in ``oura_tokens`` and ``sync_oura()`` pulls real daily
     readiness / sleep / HRV from the Oura Cloud API v2.
  2. Manual / MCP push — ``log_oura_readiness()`` upserts a snapshot directly
     (used by the MCP tool and the iOS Shortcut fallback).

Tools exposed to MCP
--------------------
  sync_oura_readiness()
      Pull the latest readiness from the connected Oura account into SQLite.

  log_oura_readiness(date?, readiness_score, sleep_score, hrv, recovery_index, raw_json?)
      Upserts today's (or a named date's) readiness data manually.

  get_oura_readiness(days?)
      Returns the last N days of readiness records as a formatted string.
"""
from __future__ import annotations

import datetime
import json
import os
from urllib.parse import urlencode

from lib.db import get_connection
from lib.user_context import get_current_user_oid


# ── Oura Cloud API v2 endpoints ────────────────────────────────────────────────
OURA_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"

# Scopes: personal (profile) + daily (readiness, sleep, activity, HRV via sleep).
OURA_SCOPES = "personal daily"

# Refresh slightly before true expiry so an in-flight request never races a
# token going stale.
_TOKEN_REFRESH_SKEW_SECONDS = 120


class OuraError(RuntimeError):
    """Raised when an Oura API call or OAuth exchange fails."""


# ── configuration ──────────────────────────────────────────────────────────────
def _client_creds() -> "tuple[str, str]":
    """Return (client_id, client_secret) from env, falling back to config.json."""
    cid = os.environ.get("OURA_CLIENT_ID", "")
    secret = os.environ.get("OURA_CLIENT_SECRET", "")
    if not cid or not secret:
        try:
            from lib import config
            cid = cid or getattr(config, "_cfg", {}).get("oura_client_id", "")
            secret = secret or getattr(config, "_cfg", {}).get("oura_client_secret", "")
        except Exception:
            pass
    return cid, secret


def oura_configured() -> bool:
    """True when the server has Oura OAuth client credentials available."""
    cid, secret = _client_creds()
    return bool(cid and secret)


def oura_authorize_url(state: str, redirect_uri: str) -> str:
    """Build the Oura authorize URL the browser is redirected to on Connect."""
    cid, _ = _client_creds()
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "scope": OURA_SCOPES,
        "state": state,
    }
    return f"{OURA_AUTHORIZE_URL}?{urlencode(params)}"


# ── helpers ────────────────────────────────────────────────────────────────────
def _readiness_label(score: int) -> str:
    """Map a readiness score to its High / Good / Low band label."""
    if score >= 85:
        return "High"
    if score >= 70:
        return "Good"
    return "Low"

def _latest_oura_row() -> "dict | None":
    """Return the most recent oura_readiness row for the current user, or None.

    Always scoped to the current OID. In local/dev or API-key sessions the OID
    is the empty string, and rows are written with that same empty OID, so a
    WHERE oid = '' match still returns the local user's own data. On a shared
    database this guarantees an OID-less session can never read another user's
    rows (their rows carry a real OID, not '').
    """
    oid = get_current_user_oid()
    try:
        with get_connection() as con:
            row = con.execute(
                "SELECT date, readiness_score, sleep_score, hrv, recovery_index "
                "FROM oura_readiness WHERE oid = ? "
                "ORDER BY date DESC LIMIT 1",
                (oid,),
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    return None


# ── MCP tools ─────────────────────────────────────────────────────────────────

def log_oura_readiness(
    readiness_score: int,
    sleep_score: int,
    hrv: int,
    recovery_index: int,
    date: str = "",
    raw_json: str = "",
) -> str:
    """Log or update a daily Oura Ring readiness snapshot to SQLite.

    Call once per day (or whenever the Oura app syncs) with today's scores.
    Re-logging the same date overwrites the previous entry.

    Parameters
    ----------
    readiness_score : Oura readiness score 0-100.
    sleep_score     : Oura sleep score 0-100.
    hrv             : Heart rate variability in ms (rMSSD).
    recovery_index  : Oura recovery index 0-100.
    date            : ISO date string (YYYY-MM-DD). Defaults to today.
    raw_json        : Optional full Oura API response payload as a JSON string.
    """
    log_date = date or datetime.date.today().isoformat()
    oid = get_current_user_oid()

    with get_connection() as con:
        con.execute(
            """INSERT INTO oura_readiness
                   (oid, date, readiness_score, sleep_score, hrv, recovery_index, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(oid, date) DO UPDATE SET
                   readiness_score = excluded.readiness_score,
                   sleep_score     = excluded.sleep_score,
                   hrv             = excluded.hrv,
                   recovery_index  = excluded.recovery_index,
                   raw_json        = excluded.raw_json""",
            (oid, log_date, readiness_score, sleep_score, hrv, recovery_index, raw_json or None),
        )

    _label = _readiness_label(readiness_score)
    return (
        f"Oura readiness logged for {log_date}.\n"
        f"  Readiness: {readiness_score} ({_label})\n"
        f"  Sleep:     {sleep_score}\n"
        f"  HRV:       {hrv} ms\n"
        f"  Recovery:  {recovery_index}"
    )


def get_oura_readiness(days: int = 7) -> str:
    """Return recent Oura readiness records for the current user.

    Parameters
    ----------
    days : Number of days of history to return (default 7, max 90).
    """
    days = min(max(1, days), 90)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    oid = get_current_user_oid()

    try:
        with get_connection() as con:
            rows = con.execute(
                "SELECT date, readiness_score, sleep_score, hrv, recovery_index "
                "FROM oura_readiness WHERE oid = ? AND date >= ? "
                "ORDER BY date DESC",
                (oid, cutoff),
            ).fetchall()
    except Exception as exc:
        return f"Error reading oura_readiness: {exc}"

    if not rows:
        return f"No Oura data logged in the past {days} days. Use log_oura_readiness() to add entries."

    lines = [f"═══ OURA READINESS (last {days} days) ═══", ""]
    for r in rows:
        score = r["readiness_score"] or 0
        label = _readiness_label(score)
        lines.append(
            f"{r['date']}  Readiness {score:3d} ({label:<4})  "
            f"Sleep {r['sleep_score'] or '--':>3}  "
            f"HRV {r['hrv'] or '--':>3} ms  "
            f"Recovery {r['recovery_index'] or '--':>3}"
        )
    return "\n".join(lines)


# ── OAuth token storage (per-OID) ──────────────────────────────────────────────
def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def save_oura_tokens(tokens: dict) -> None:
    """Persist (or refresh) the current user's Oura OAuth tokens.

    Expects the raw token-endpoint response: access_token, refresh_token,
    expires_in (seconds), scope. Upserts a single row keyed by OID.
    """
    oid = get_current_user_oid()
    access = tokens.get("access_token", "")
    refresh = tokens.get("refresh_token", "")
    if not access or not refresh:
        raise OuraError("token response missing access_token/refresh_token")
    expires_in = int(tokens.get("expires_in", 86400) or 86400)
    expires_at = (_now_utc() + datetime.timedelta(seconds=expires_in)).isoformat()
    scope = tokens.get("scope", "") or OURA_SCOPES
    now = _now_utc().isoformat()

    with get_connection() as con:
        con.execute(
            """INSERT INTO oura_tokens
                   (oid, access_token, refresh_token, expires_at, scope, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(oid) DO UPDATE SET
                   access_token  = excluded.access_token,
                   refresh_token = excluded.refresh_token,
                   expires_at    = excluded.expires_at,
                   scope         = excluded.scope,
                   updated_at    = excluded.updated_at""",
            (oid, access, refresh, expires_at, scope, now, now),
        )


def get_oura_tokens() -> "dict | None":
    """Return the current user's stored Oura token row, or None."""
    oid = get_current_user_oid()
    try:
        with get_connection() as con:
            row = con.execute(
                "SELECT access_token, refresh_token, expires_at, scope, last_sync_at "
                "FROM oura_tokens WHERE oid = ?",
                (oid,),
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def clear_oura_tokens() -> bool:
    """Delete the current user's Oura tokens (disconnect). Returns True if a row was removed."""
    oid = get_current_user_oid()
    with get_connection() as con:
        cur = con.execute("DELETE FROM oura_tokens WHERE oid = ?", (oid,))
        return cur.rowcount > 0


def _mark_synced() -> None:
    oid = get_current_user_oid()
    with get_connection() as con:
        con.execute(
            "UPDATE oura_tokens SET last_sync_at = ?, updated_at = ? WHERE oid = ?",
            (_now_utc().isoformat(), _now_utc().isoformat(), oid),
        )


# ── OAuth code/refresh exchange ────────────────────────────────────────────────
def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    import httpx

    cid, secret = _client_creds()
    if not cid or not secret:
        raise OuraError("Oura client credentials are not configured")
    try:
        resp = httpx.post(
            OURA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise OuraError(f"token request failed: {exc}") from exc
    if resp.status_code != 200:
        raise OuraError(f"token exchange returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _refresh_tokens(refresh_token: str) -> dict:
    """Use a refresh token to obtain a fresh access token; persists the result."""
    import httpx

    cid, secret = _client_creds()
    try:
        resp = httpx.post(
            OURA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise OuraError(f"token refresh failed: {exc}") from exc
    if resp.status_code != 200:
        raise OuraError(f"token refresh returned {resp.status_code}: {resp.text[:200]}")
    tokens = resp.json()
    # Oura may not echo a new refresh_token; keep the existing one if so.
    tokens.setdefault("refresh_token", refresh_token)
    save_oura_tokens(tokens)
    return tokens


def _valid_access_token() -> "str | None":
    """Return a non-expired access token for the current user, refreshing if needed."""
    row = get_oura_tokens()
    if not row:
        return None
    try:
        expires_at = datetime.datetime.fromisoformat(row["expires_at"])
    except (ValueError, TypeError):
        expires_at = _now_utc()
    if _now_utc() + datetime.timedelta(seconds=_TOKEN_REFRESH_SKEW_SECONDS) >= expires_at:
        refreshed = _refresh_tokens(row["refresh_token"])
        return refreshed.get("access_token")
    return row["access_token"]


# ── Oura API data fetch ────────────────────────────────────────────────────────
def _api_get(access_token: str, path: str, params: dict) -> list:
    """GET an Oura usercollection endpoint and return its data list."""
    import httpx

    try:
        resp = httpx.get(
            f"{OURA_API_BASE}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise OuraError(f"Oura API {path} request failed: {exc}") from exc
    if resp.status_code == 401:
        raise OuraError("Oura API rejected the access token (401)")
    if resp.status_code != 200:
        raise OuraError(f"Oura API {path} returned {resp.status_code}: {resp.text[:160]}")
    return resp.json().get("data", []) or []


def _latest_by_day(items: list) -> "dict | None":
    """Return the item with the most recent 'day', or None."""
    dated = [i for i in items if i.get("day")]
    if not dated:
        return None
    return max(dated, key=lambda i: i["day"])


def fetch_latest_from_oura(access_token: str) -> "dict | None":
    """Pull the most recent readiness/sleep/HRV snapshot from the Oura API.

    Returns a dict matching the oura_readiness columns, or None when the
    account has no readiness data in the lookback window.
    """
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=4)).isoformat()
    end = today.isoformat()
    window = {"start_date": start, "end_date": end}

    readiness_items = _api_get(access_token, "daily_readiness", window)
    latest = _latest_by_day(readiness_items)
    if not latest:
        return None

    day = latest["day"]
    contributors = latest.get("contributors") or {}
    readiness_score = int(latest.get("score") or 0)
    recovery_index = int(contributors.get("recovery_index") or 0)

    # Sleep score: match the readiness day, else fall back to the latest sleep day.
    sleep_items = _api_get(access_token, "daily_sleep", window)
    sleep_by_day = {i["day"]: i for i in sleep_items if i.get("day")}
    sleep_row = sleep_by_day.get(day) or _latest_by_day(sleep_items) or {}
    sleep_score = int(sleep_row.get("score") or 0)

    # HRV (ms): from the detailed sleep endpoint's average_hrv.
    hrv = 0
    try:
        hrv_items = _api_get(access_token, "sleep", window)
        hrv_by_day = {i["day"]: i for i in hrv_items if i.get("day")}
        hrv_row = hrv_by_day.get(day) or _latest_by_day(hrv_items) or {}
        hrv = int(round(hrv_row.get("average_hrv") or 0))
    except OuraError:
        pass  # HRV is best-effort; readiness/sleep are the primary signals.

    return {
        "date": day,
        "readiness_score": readiness_score,
        "sleep_score": sleep_score,
        "hrv": hrv,
        "recovery_index": recovery_index,
        "raw_json": json.dumps({"daily_readiness": latest, "daily_sleep": sleep_row}),
    }


def sync_oura() -> dict:
    """Pull the latest reading from the connected Oura account into SQLite.

    Returns a structured result the API/MCP layers can surface:
      {ok, connected, reading|None, error?}
    """
    if not oura_configured():
        return {"ok": False, "connected": False, "error": "not_configured"}
    try:
        access = _valid_access_token()
    except OuraError as exc:
        return {"ok": False, "connected": False, "error": f"auth: {exc}"}
    if not access:
        return {"ok": False, "connected": False, "error": "not_connected"}

    try:
        reading = fetch_latest_from_oura(access)
    except OuraError as exc:
        return {"ok": False, "connected": True, "error": str(exc)}

    if not reading:
        _mark_synced()
        return {"ok": True, "connected": True, "reading": None, "note": "no_data"}

    log_oura_readiness(
        readiness_score=reading["readiness_score"],
        sleep_score=reading["sleep_score"],
        hrv=reading["hrv"],
        recovery_index=reading["recovery_index"],
        date=reading["date"],
        raw_json=reading.get("raw_json", ""),
    )
    _mark_synced()
    return {"ok": True, "connected": True, "reading": reading}


def oura_connection_status() -> dict:
    """Lightweight status for the Settings screen (no network calls)."""
    row = get_oura_tokens()
    return {
        "configured": oura_configured(),
        "connected": row is not None,
        "last_sync": (row or {}).get("last_sync_at") or "",
        "scope": (row or {}).get("scope") or "",
    }


def sync_oura_readiness() -> str:
    """Pull the latest readiness from your connected Oura account into the dashboard.

    Requires that you have connected Oura via the dashboard Settings page first.
    """
    result = sync_oura()
    if result.get("ok"):
        r = result.get("reading")
        if not r:
            return "Oura is connected, but no new readiness data was available to sync."
        return (
            f"Synced Oura readiness for {r['date']}.\n"
            f"  Readiness: {r['readiness_score']} ({_readiness_label(r['readiness_score'])})\n"
            f"  Sleep:     {r['sleep_score']}\n"
            f"  HRV:       {r['hrv']} ms\n"
            f"  Recovery:  {r['recovery_index']}"
        )
    err = result.get("error", "unknown error")
    if err == "not_configured":
        return "Oura integration is not configured on this server (missing OURA_CLIENT_ID/SECRET)."
    if err == "not_connected":
        return "No Oura account is connected. Open dashboard Settings and click Connect Oura Ring."
    return f"Could not sync Oura readiness: {err}"


# ── registration ───────────────────────────────────────────────────────────────

def register(mcp) -> None:
    mcp.tool()(sync_oura_readiness)
    mcp.tool()(log_oura_readiness)
    mcp.tool()(get_oura_readiness)
