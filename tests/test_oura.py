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
    oura_mod.log_oura_readiness(readiness_score=88, sleep_score=80, hrv=72, recovery_index=90, date="2026-06-29")
    out = oura_mod.get_oura_readiness(days=7)
    assert "2026-06-29" in out
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
