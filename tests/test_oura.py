"""Tests for tools/oura.py + the v4 oura_readiness migration retrofit.

Covers:
  - migration creates oura_readiness on a fresh DB
  - migration tolerance: a missing job_queue table (fragile ALTER) does NOT
    block the oura_readiness CREATE from landing on partial DBs
  - log_oura_readiness insert + upsert (same date overwrites, no duplicate)
  - _latest_oura_row returns the most recent row by date
  - per-oid isolation (one user can't read another's readiness)
  - get_oura_readiness formatting + empty-state message
  - _load_oura() in the dashboard reads SQLite first, JSON file as fallback
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import lib.config as cfg
import lib.db as db
from lib.user_context import set_user_oid, reset_user_oid


@pytest.fixture()
def tmp_data(tmp_path: Path, monkeypatch):
    """Point lib.config.DATA_FOLDER at an isolated tmp dir for each test."""
    monkeypatch.setattr(cfg, "DATA_FOLDER", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture()
def oura_mod():
    import tools.oura as oura
    return importlib.reload(oura)


# ── migration ────────────────────────────────────────────────────────────────

def test_migration_creates_oura_table(tmp_data):
    with db.get_connection() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(oura_readiness)").fetchall()]
    assert {"oid", "date", "readiness_score", "sleep_score", "hrv", "recovery_index"} <= set(cols)


def test_migration_tolerates_missing_job_queue(tmp_data):
    """The fragile v2/v3 ALTER TABLE job_queue statements must not abort the
    chain when job_queue is absent — oura_readiness (v4) must still be created."""
    # A fresh DB here has NO job_queue table, so the ALTERs would historically
    # raise "no such table" and block v4. With tolerance, v4 still lands.
    with db.get_connection() as con:
        names = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "oura_readiness" in names
    assert "job_queue" not in names  # confirms the ALTERs were genuinely skipped


# ── log / upsert ─────────────────────────────────────────────────────────────

def test_log_oura_readiness_inserts(tmp_data, oura_mod):
    msg = oura_mod.log_oura_readiness(
        readiness_score=82, sleep_score=64, hrv=64, recovery_index=88, date="2026-06-29"
    )
    assert "2026-06-29" in msg and "82" in msg
    row = oura_mod._latest_oura_row()
    assert row["readiness_score"] == 82
    assert row["recovery_index"] == 88


def test_log_oura_readiness_upsert_overwrites(tmp_data, oura_mod):
    oura_mod.log_oura_readiness(
        readiness_score=82, sleep_score=64, hrv=64, recovery_index=88, date="2026-06-29"
    )
    oura_mod.log_oura_readiness(
        readiness_score=90, sleep_score=70, hrv=70, recovery_index=95, date="2026-06-29"
    )
    with db.get_connection() as con:
        n = con.execute(
            "SELECT COUNT(*) FROM oura_readiness WHERE date='2026-06-29'"
        ).fetchone()[0]
    assert n == 1
    assert oura_mod._latest_oura_row()["readiness_score"] == 90


def test_latest_row_picks_most_recent_date(tmp_data, oura_mod):
    oura_mod.log_oura_readiness(readiness_score=70, sleep_score=60, hrv=55, recovery_index=72, date="2026-06-27")
    oura_mod.log_oura_readiness(readiness_score=88, sleep_score=80, hrv=72, recovery_index=90, date="2026-06-29")
    oura_mod.log_oura_readiness(readiness_score=75, sleep_score=65, hrv=60, recovery_index=78, date="2026-06-28")
    assert oura_mod._latest_oura_row()["date"] == "2026-06-29"


# ── per-oid isolation ────────────────────────────────────────────────────────

def test_oid_isolation(tmp_data, oura_mod):
    tok_a = set_user_oid("user-aaa")
    try:
        oura_mod.log_oura_readiness(readiness_score=80, sleep_score=60, hrv=60, recovery_index=80, date="2026-06-29")
    finally:
        reset_user_oid(tok_a)

    tok_b = set_user_oid("user-bbb")
    try:
        # user B has no rows of their own
        assert oura_mod._latest_oura_row() is None
        oura_mod.log_oura_readiness(readiness_score=50, sleep_score=40, hrv=40, recovery_index=55, date="2026-06-29")
        assert oura_mod._latest_oura_row()["readiness_score"] == 50
    finally:
        reset_user_oid(tok_b)

    tok_a2 = set_user_oid("user-aaa")
    try:
        assert oura_mod._latest_oura_row()["readiness_score"] == 80  # unchanged by B
    finally:
        reset_user_oid(tok_a2)


def test_oidless_session_cannot_read_real_oid_rows(tmp_data, oura_mod):
    """Leak guard: a row written under a real OID must NOT be visible to an
    OID-less (empty-string) session sharing the same database file."""
    tok = set_user_oid("real-user-123")
    try:
        oura_mod.log_oura_readiness(
            readiness_score=84, sleep_score=70, hrv=65, recovery_index=82, date="2026-06-29"
        )
    finally:
        reset_user_oid(tok)

    # No OID set now (default ''). Must not see real-user-123's row.
    assert oura_mod._latest_oura_row() is None
    assert "No Oura data" in oura_mod.get_oura_readiness(days=7)



# ── get_oura_readiness formatting ────────────────────────────────────────────

def test_get_oura_readiness_empty(tmp_data, oura_mod):
    out = oura_mod.get_oura_readiness(days=7)
    assert "No Oura data" in out


def test_get_oura_readiness_lists_rows(tmp_data, oura_mod):
    import datetime
    # Relative date: a hardcoded one rots out of the 7-day window over time.
    day = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    oura_mod.log_oura_readiness(readiness_score=88, sleep_score=80, hrv=72, recovery_index=90, date=day)
    out = oura_mod.get_oura_readiness(days=7)
    assert day in out
    assert "88" in out
    assert "High" in out  # >= 85


# ── dashboard _load_oura integration ─────────────────────────────────────────

def test_load_oura_prefers_sqlite(tmp_data, oura_mod):
    from transport.http.routes.dashboard import home
    oura_mod.log_oura_readiness(readiness_score=91, sleep_score=81, hrv=73, recovery_index=92, date="2026-06-29")
    loaded = home._load_oura()
    assert loaded is not None
    assert loaded["readiness_score"] == 91


def test_load_oura_falls_back_to_json(tmp_data, monkeypatch):
    """With no SQLite rows, _load_oura reads workspace/oura.json."""
    from transport.http.routes.dashboard import home
    ws = tmp_data / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "oura.json").write_text(
        '{"date":"2026-06-29","readiness_score":77,"sleep_score":66,"hrv":61,"recovery_index":81}'
    )
    monkeypatch.setattr(
        "lib.config.get_active_workspace_folder", lambda: ws, raising=False
    )
    loaded = home._load_oura()
    assert loaded is not None
    assert loaded["readiness_score"] == 77


# ── OAuth token storage: encryption at rest ──────────────────────────────────

_RAW_TOKENS = {
    "access_token": "oura_access_plain_xyz",
    "refresh_token": "oura_refresh_plain_xyz",
    "expires_in": 86400,
    "scope": "daily",
}


def test_tokens_round_trip_without_key(tmp_data, oura_mod, monkeypatch):
    """With no APP_ENCRYPTION_KEY, tokens persist as plaintext (prior behaviour)."""
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")

    oura_mod.save_oura_tokens(dict(_RAW_TOKENS))
    got = oura_mod.get_oura_tokens()
    assert got["access_token"] == "oura_access_plain_xyz"
    assert got["refresh_token"] == "oura_refresh_plain_xyz"

    # Stored value is the raw plaintext (no encryption prefix).
    with db.get_connection() as con:
        row = con.execute("SELECT access_token, refresh_token FROM oura_tokens").fetchone()
    assert row["access_token"] == "oura_access_plain_xyz"
    assert not row["access_token"].startswith("enc:")


def test_tokens_encrypted_at_rest_with_key(tmp_data, oura_mod, monkeypatch):
    """With a key set, the DB holds ciphertext but get_oura_tokens returns plaintext."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)

    oura_mod.save_oura_tokens(dict(_RAW_TOKENS))

    # On disk: encrypted, prefixed, and not the plaintext.
    with db.get_connection() as con:
        row = con.execute("SELECT access_token, refresh_token FROM oura_tokens").fetchone()
    assert row["access_token"].startswith("enc:v1:")
    assert "oura_access_plain_xyz" not in row["access_token"]
    assert row["refresh_token"].startswith("enc:v1:")

    # Through the accessor: transparently decrypted.
    got = oura_mod.get_oura_tokens()
    assert got["access_token"] == "oura_access_plain_xyz"
    assert got["refresh_token"] == "oura_refresh_plain_xyz"


def test_tokens_unreadable_after_key_rotation(tmp_data, oura_mod, monkeypatch):
    """A rotated/missing key makes get_oura_tokens report not-connected (None),
    so the user is prompted to reconnect rather than the request erroring."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    oura_mod.save_oura_tokens(dict(_RAW_TOKENS))

    # Rotate to a different key.
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    assert oura_mod.get_oura_tokens() is None


def test_oura_connection_status_with_encryption(tmp_data, oura_mod, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert oura_mod.oura_connection_status()["connected"] is False
    oura_mod.save_oura_tokens(dict(_RAW_TOKENS))
    assert oura_mod.oura_connection_status()["connected"] is True


# ── httpx mock plumbing ──────────────────────────────────────────────────────

class _FakeResp:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


@pytest.fixture()
def creds(monkeypatch):
    """Configure Oura client credentials via env for the duration of a test."""
    monkeypatch.setenv("OURA_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "test-client-secret")


# ── credentials / configuration ──────────────────────────────────────────────

def test_oura_configured_true_with_env(oura_mod, creds):
    assert oura_mod.oura_configured() is True


def test_oura_configured_false_without_creds(oura_mod, monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    monkeypatch.setitem(cfg._cfg, "oura_client_id", "")
    monkeypatch.setitem(cfg._cfg, "oura_client_secret", "")
    assert oura_mod.oura_configured() is False


def test_client_creds_fall_back_to_config(oura_mod, monkeypatch):
    """When env vars are absent, credentials come from lib.config._cfg."""
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    monkeypatch.setitem(cfg._cfg, "oura_client_id", "cfg-cid")
    monkeypatch.setitem(cfg._cfg, "oura_client_secret", "cfg-secret")
    cid, secret = oura_mod._client_creds()
    assert cid == "cfg-cid"
    assert secret == "cfg-secret"


def test_oura_authorize_url_contains_params(oura_mod, creds):
    url = oura_mod.oura_authorize_url(state="xyz-state", redirect_uri="https://app/cb")
    assert url.startswith(oura_mod.OURA_AUTHORIZE_URL)
    assert "client_id=test-client-id" in url
    assert "state=xyz-state" in url
    assert "redirect_uri=https" in url


# ── token save error path ────────────────────────────────────────────────────

def test_save_oura_tokens_missing_fields_raises(tmp_data, oura_mod):
    with pytest.raises(oura_mod.OuraError):
        oura_mod.save_oura_tokens({"access_token": "only-access"})  # no refresh


def test_clear_oura_tokens_returns_true_then_false(tmp_data, oura_mod):
    oura_mod.save_oura_tokens(dict(_RAW_TOKENS))
    assert oura_mod.clear_oura_tokens() is True
    assert oura_mod.clear_oura_tokens() is False
    assert oura_mod.get_oura_tokens() is None


# ── exchange_code_for_tokens ─────────────────────────────────────────────────

def test_exchange_code_success(oura_mod, creds, monkeypatch):
    import httpx
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return _FakeResp(200, {"access_token": "a", "refresh_token": "r", "expires_in": 100})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = oura_mod.exchange_code_for_tokens("the-code", "https://app/cb")
    assert out["access_token"] == "a"
    assert captured["url"] == oura_mod.OURA_TOKEN_URL
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "the-code"


def test_exchange_code_missing_creds_raises(oura_mod, monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    monkeypatch.setitem(cfg._cfg, "oura_client_id", "")
    monkeypatch.setitem(cfg._cfg, "oura_client_secret", "")
    with pytest.raises(oura_mod.OuraError):
        oura_mod.exchange_code_for_tokens("code", "https://app/cb")


def test_exchange_code_non_200_raises(oura_mod, creds, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(400, text="bad request"))
    with pytest.raises(oura_mod.OuraError):
        oura_mod.exchange_code_for_tokens("code", "https://app/cb")


def test_exchange_code_http_error_raises(oura_mod, creds, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.HTTPError("connection reset")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(oura_mod.OuraError):
        oura_mod.exchange_code_for_tokens("code", "https://app/cb")


# ── refresh + valid-access-token ─────────────────────────────────────────────

def test_refresh_tokens_persists_and_keeps_refresh(tmp_data, oura_mod, creds, monkeypatch):
    import httpx
    # Response omits refresh_token — the existing one must be retained.
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _FakeResp(200, {"access_token": "new-access", "expires_in": 3600}),
    )
    out = oura_mod._refresh_tokens("old-refresh")
    assert out["access_token"] == "new-access"
    assert out["refresh_token"] == "old-refresh"  # setdefault kept it
    # And it was saved.
    stored = oura_mod.get_oura_tokens()
    assert stored["access_token"] == "new-access"


def test_refresh_tokens_non_200_raises(oura_mod, creds, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(401, text="nope"))
    with pytest.raises(oura_mod.OuraError):
        oura_mod._refresh_tokens("old-refresh")


def test_valid_access_token_none_when_no_row(tmp_data, oura_mod):
    assert oura_mod._valid_access_token() is None


def test_valid_access_token_returns_unexpired(tmp_data, oura_mod, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    oura_mod.save_oura_tokens({
        "access_token": "still-good", "refresh_token": "r", "expires_in": 86400,
    })
    assert oura_mod._valid_access_token() == "still-good"


def test_valid_access_token_refreshes_when_expired(tmp_data, oura_mod, creds, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    # Persist an already-expired token.
    oura_mod.save_oura_tokens({
        "access_token": "stale", "refresh_token": "old-refresh", "expires_in": -10,
    })
    import httpx
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _FakeResp(200, {"access_token": "fresh", "expires_in": 3600}),
    )
    assert oura_mod._valid_access_token() == "fresh"


# ── _api_get ─────────────────────────────────────────────────────────────────

def test_api_get_returns_data_list(oura_mod, monkeypatch):
    import httpx
    monkeypatch.setattr(
        httpx, "get",
        lambda *a, **k: _FakeResp(200, {"data": [{"day": "2026-06-29", "score": 80}]}),
    )
    out = oura_mod._api_get("tok", "daily_readiness", {"start_date": "x", "end_date": "y"})
    assert out == [{"day": "2026-06-29", "score": 80}]


def test_api_get_401_raises(oura_mod, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(401, text="unauth"))
    with pytest.raises(oura_mod.OuraError):
        oura_mod._api_get("tok", "daily_readiness", {})


def test_api_get_500_raises(oura_mod, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(500, text="boom"))
    with pytest.raises(oura_mod.OuraError):
        oura_mod._api_get("tok", "daily_readiness", {})


def test_api_get_http_error_raises(oura_mod, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.HTTPError("timeout")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(oura_mod.OuraError):
        oura_mod._api_get("tok", "daily_readiness", {})


# ── _latest_by_day ───────────────────────────────────────────────────────────

def test_latest_by_day_picks_max(oura_mod):
    items = [{"day": "2026-06-27"}, {"day": "2026-06-29"}, {"day": "2026-06-28"}]
    assert oura_mod._latest_by_day(items)["day"] == "2026-06-29"


def test_latest_by_day_empty_is_none(oura_mod):
    assert oura_mod._latest_by_day([]) is None
    assert oura_mod._latest_by_day([{"score": 1}]) is None  # no 'day' keys


# ── fetch_latest_from_oura ───────────────────────────────────────────────────

def _fake_api_map(mapping):
    """Return a fake _api_get that dispatches by endpoint path."""
    def _fake(access_token, path, params):
        return mapping.get(path, [])
    return _fake


def test_fetch_latest_combines_endpoints(oura_mod, monkeypatch):
    day = "2026-06-29"
    monkeypatch.setattr(oura_mod, "_api_get", _fake_api_map({
        "daily_readiness": [{"day": day, "score": 88, "contributors": {"recovery_index": 91}}],
        "daily_sleep": [{"day": day, "score": 80}],
        "sleep": [{"day": day, "average_hrv": 64.6}],
    }))
    out = oura_mod.fetch_latest_from_oura("tok")
    assert out["date"] == day
    assert out["readiness_score"] == 88
    assert out["sleep_score"] == 80
    assert out["hrv"] == 65  # rounded
    assert out["recovery_index"] == 91
    assert "daily_readiness" in out["raw_json"]


def test_fetch_latest_no_readiness_returns_none(oura_mod, monkeypatch):
    monkeypatch.setattr(oura_mod, "_api_get", _fake_api_map({"daily_readiness": []}))
    assert oura_mod.fetch_latest_from_oura("tok") is None


def test_fetch_latest_hrv_best_effort(oura_mod, monkeypatch):
    """An HRV endpoint failure must not sink the whole fetch; hrv falls back to 0."""
    day = "2026-06-29"

    def _fake(access_token, path, params):
        if path == "sleep":
            raise oura_mod.OuraError("hrv endpoint down")
        return {
            "daily_readiness": [{"day": day, "score": 70, "contributors": {}}],
            "daily_sleep": [{"day": day, "score": 60}],
        }.get(path, [])

    monkeypatch.setattr(oura_mod, "_api_get", _fake)
    out = oura_mod.fetch_latest_from_oura("tok")
    assert out["hrv"] == 0
    assert out["readiness_score"] == 70


# ── sync_oura ────────────────────────────────────────────────────────────────

def test_sync_oura_not_configured(tmp_data, oura_mod, monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    monkeypatch.setitem(cfg._cfg, "oura_client_id", "")
    monkeypatch.setitem(cfg._cfg, "oura_client_secret", "")
    res = oura_mod.sync_oura()
    assert res == {"ok": False, "connected": False, "error": "not_configured"}


def test_sync_oura_not_connected(tmp_data, oura_mod, creds):
    res = oura_mod.sync_oura()
    assert res["ok"] is False
    assert res["error"] == "not_connected"


def test_sync_oura_no_data_marks_synced(tmp_data, oura_mod, creds, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    oura_mod.save_oura_tokens({"access_token": "a", "refresh_token": "r", "expires_in": 86400})
    monkeypatch.setattr(oura_mod, "fetch_latest_from_oura", lambda tok: None)
    res = oura_mod.sync_oura()
    assert res["ok"] is True
    assert res["reading"] is None
    assert res["note"] == "no_data"


def test_sync_oura_success_logs_reading(tmp_data, oura_mod, creds, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    oura_mod.save_oura_tokens({"access_token": "a", "refresh_token": "r", "expires_in": 86400})
    reading = {
        "date": "2026-06-29", "readiness_score": 84, "sleep_score": 70,
        "hrv": 61, "recovery_index": 82, "raw_json": "{}",
    }
    monkeypatch.setattr(oura_mod, "fetch_latest_from_oura", lambda tok: reading)
    res = oura_mod.sync_oura()
    assert res["ok"] is True
    assert res["reading"]["readiness_score"] == 84
    # Persisted to the readiness table.
    assert oura_mod._latest_oura_row()["readiness_score"] == 84


def test_sync_oura_fetch_error_reports_connected(tmp_data, oura_mod, creds, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    oura_mod.save_oura_tokens({"access_token": "a", "refresh_token": "r", "expires_in": 86400})

    def boom(tok):
        raise oura_mod.OuraError("api down")

    monkeypatch.setattr(oura_mod, "fetch_latest_from_oura", boom)
    res = oura_mod.sync_oura()
    assert res["ok"] is False
    assert res["connected"] is True
    assert "api down" in res["error"]


# ── sync_oura_readiness (string wrapper for MCP) ─────────────────────────────

def test_sync_oura_readiness_not_configured_message(tmp_data, oura_mod, monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    monkeypatch.setitem(cfg._cfg, "oura_client_id", "")
    monkeypatch.setitem(cfg._cfg, "oura_client_secret", "")
    assert "not configured" in oura_mod.sync_oura_readiness().lower()


def test_sync_oura_readiness_success_message(tmp_data, oura_mod, monkeypatch):
    monkeypatch.setattr(oura_mod, "sync_oura", lambda: {
        "ok": True,
        "reading": {"date": "2026-06-29", "readiness_score": 88,
                    "sleep_score": 80, "hrv": 65, "recovery_index": 90},
    })
    out = oura_mod.sync_oura_readiness()
    assert "2026-06-29" in out
    assert "88" in out
    assert "High" in out


def test_sync_oura_readiness_no_data_message(tmp_data, oura_mod, monkeypatch):
    monkeypatch.setattr(oura_mod, "sync_oura", lambda: {"ok": True, "reading": None})
    assert "no new readiness" in oura_mod.sync_oura_readiness().lower()


def test_sync_oura_readiness_not_connected_message(tmp_data, oura_mod, monkeypatch):
    monkeypatch.setattr(oura_mod, "sync_oura", lambda: {"ok": False, "error": "not_connected"})
    assert "connect" in oura_mod.sync_oura_readiness().lower()


# ── Personal Access Token path (desktop) ─────────────────────────────────────

def test_save_oura_pat_stores_and_returns_token(tmp_data, oura_mod):
    oura_mod.save_oura_pat("pat-abc-123")
    row = oura_mod.get_oura_tokens()
    assert row is not None
    assert row["access_token"] == "pat-abc-123"
    assert row["refresh_token"] == ""  # empty refresh marks a PAT
    # A PAT never goes through the refresh dance, even with no client creds.
    assert oura_mod._valid_access_token() == "pat-abc-123"


def test_save_oura_pat_rejects_empty(tmp_data, oura_mod):
    with pytest.raises(oura_mod.OuraError):
        oura_mod.save_oura_pat("   ")


def test_connection_status_connected_via_pat(tmp_data, oura_mod):
    assert oura_mod.oura_connection_status()["connected"] is False
    oura_mod.save_oura_pat("pat-abc-123")
    status = oura_mod.oura_connection_status()
    assert status["connected"] is True
    assert status["scope"] == "pat"


def test_sync_uses_pat_without_client_creds(tmp_data, oura_mod, monkeypatch):
    """sync_oura() must work from a stored PAT alone — no OURA_CLIENT_ID/SECRET."""
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    oura_mod.save_oura_pat("pat-abc-123")

    seen = {}

    def fake_fetch(access_token):
        seen["token"] = access_token
        return {
            "date": "2026-07-07", "readiness_score": 88, "sleep_score": 90,
            "hrv": 55, "recovery_index": 80, "raw_json": "{}",
        }

    monkeypatch.setattr(oura_mod, "fetch_latest_from_oura", fake_fetch)
    result = oura_mod.sync_oura()
    assert result["ok"] is True
    assert seen["token"] == "pat-abc-123"


def test_sync_without_any_credentials_reports_not_configured(tmp_data, oura_mod, monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    result = oura_mod.sync_oura()
    assert result["ok"] is False
    assert result["error"] == "not_configured"
