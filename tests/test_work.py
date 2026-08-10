"""Control plane P0 (lib/work.py): durable work items + dispatcher.

The invariants that matter:
  - executors run inside the work row's OWN partition (never ambient context)
  - outcomes are durable rows: success stores artifacts, failure stores the
    traceback — nothing vanishes into an executor
  - restart recovery: orphaned queued rows are re-dispatched, exhausted ones
    are marked failed
  - the HTTP surface exposes rows to the owning caller
"""
from __future__ import annotations

import time

import pytest

import lib.config as cfg
from lib import work
from lib.user_context import get_data_folder_override, reset_data_folder, set_data_folder


@pytest.fixture()
def work_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_FOLDER", str(tmp_path), raising=False)
    saved = dict(work._KINDS)
    yield tmp_path
    work._KINDS.clear()
    work._KINDS.update(saved)


def test_enqueue_requires_registered_kind(work_env):
    with pytest.raises(ValueError):
        work.enqueue("no_such_kind", {})


def test_execute_runs_in_the_rows_partition(work_env):
    """The whole point: the executor sees the row's home partition, not the
    dispatcher's ambient context."""
    seen = {}
    work.register_kind("probe", lambda inputs: seen.update(
        override=str(get_data_folder_override()), **inputs) or {"ok": True})

    partition = work_env / "users" / "user-abc"
    (partition / "db").mkdir(parents=True)
    token = set_data_folder(partition)
    try:
        item_id = work.enqueue("probe", {"x": 1})
    finally:
        reset_data_folder(token)

    work._execute(str(partition), item_id)

    assert seen["override"] == str(partition)
    assert seen["x"] == 1
    token = set_data_folder(partition)
    try:
        item = work.get_item(item_id)
    finally:
        reset_data_folder(token)
    assert item["status"] == "succeeded"
    assert item["artifacts"] == {"ok": True}
    assert item["attempt"] == 1 and item["started_at"] and item["finished_at"]


def test_failure_is_recorded_not_swallowed(work_env):
    def boom(inputs):
        raise RuntimeError("scraper exploded")

    work.register_kind("boom", boom)
    item_id = work.enqueue("boom", {"url": "https://x"})
    work._execute(None, item_id)
    item = work.get_item(item_id)
    assert item["status"] == "failed"
    assert "scraper exploded" in item["error"]
    assert "Traceback" in item["error"]


def test_unregistered_kind_at_execution_fails_row(work_env):
    work.register_kind("temp", lambda i: {})
    item_id = work.enqueue("temp", {})
    del work._KINDS["temp"]
    work._execute(None, item_id)
    assert "no executor registered" in work.get_item(item_id)["error"]


def test_sweep_recovers_orphans_and_fails_exhausted(work_env):
    work.register_kind("probe", lambda i: {})
    fresh = work.enqueue("probe", {})          # queued, attempt 0 → re-dispatch
    stuck = work.enqueue("probe", {})          # simulate died mid-run, attempts spent
    from lib.db import get_connection
    with get_connection() as con:
        con.execute(
            "UPDATE work_items SET status='running', attempt=1 WHERE id=?", (stuck,))
        con.commit()

    found = work._sweep_partitions()

    assert (None, fresh) in found
    assert all(item_id != stuck for _, item_id in found)
    item = work.get_item(stuck)
    assert item["status"] == "failed" and "abandoned" in item["error"]


def test_sweep_scans_user_partitions(work_env):
    work.register_kind("probe", lambda i: {})
    partition = work_env / "users" / "user-xyz"
    (partition / "db").mkdir(parents=True)
    token = set_data_folder(partition)
    try:
        item_id = work.enqueue("probe", {})
    finally:
        reset_data_folder(token)
    assert (str(partition), item_id) in work._sweep_partitions()


# ── end to end through the live app (dispatcher running in lifespan) ─────────

@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    import lib.config as cfg_mod
    from lib.user_provisioning import provision_user_data

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cfg_mod, "DATA_FOLDER", str(root), raising=False)
    provision_user_data(root)
    monkeypatch.delenv("API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    reset_settings_cache()
    saved = dict(work._KINDS)
    with TestClient(create_app()) as client:
        yield client
    reset_settings_cache()
    work._KINDS.clear()
    work._KINDS.update(saved)


def _wait_status(client, work_id: int, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = client.get(f"/api/work/{work_id}").json()
        if item.get("status") in ("succeeded", "failed"):
            return item
        time.sleep(0.05)
    raise AssertionError(f"work {work_id} never finished: {item}")


def test_capture_flows_through_control_plane(app_client, monkeypatch):
    monkeypatch.setitem(
        work._KINDS, "capture_url",
        lambda inputs: {"imported": True, "company": "Acme", "url": inputs["url"]},
    )
    resp = app_client.post("/api/capture", json={"url": "https://jobs.example.com/1"})
    assert resp.status_code == 200
    work_id = resp.json()["work_id"]

    item = _wait_status(app_client, work_id)
    assert item["status"] == "succeeded"
    assert item["artifacts"]["company"] == "Acme"
    assert item["kind"] == "capture_url" and item["origin"] == "mobile-share"

    listing = app_client.get("/api/work?status=succeeded").json()["items"]
    assert any(i["id"] == work_id for i in listing)


def test_capture_failure_visible_via_api(app_client, monkeypatch):
    def die(inputs):
        raise RuntimeError("blocked by LinkedIn")

    monkeypatch.setitem(work._KINDS, "capture_url", die)
    resp = app_client.post("/api/capture", json={"url": "https://jobs.example.com/2"})
    item = _wait_status(app_client, resp.json()["work_id"])
    assert item["status"] == "failed"
    assert "blocked by LinkedIn" in item["error"]


def test_work_get_404(app_client):
    assert app_client.get("/api/work/99999").status_code == 404


# ── P2: token accounting on the row ──────────────────────────────────────────
#
# Motivated by a real misread: `llm_tokens_total` is cumulative across every
# run since process start, and reading it as one night's spend overstated the
# nightly eval cost by 3x. Per-row totals cannot be misread that way — the row
# is the unit of work, and the tokens on it are the tokens that unit burned.

def _fake_llm(prompt: int, completion: int, model: str = "m-test"):
    """A client whose one call reports the given usage."""
    import types
    response = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="text"))],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion,
            total_tokens=prompt + completion),
    )
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **_k: response)
        )
    ), model


@pytest.fixture()
def no_rate_gate(monkeypatch):
    """The 12s inter-call spacing is a production concern, not a test one."""
    from lib import openai_calls as oc
    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc, "_LAST_CHAT_CALL", 0.0)


def _call_llm(prompt: int, completion: int, model: str = "m-test") -> None:
    from lib.openai_calls import create_chat_completion
    client, name = _fake_llm(prompt, completion, model)
    create_chat_completion(client, label="unit", model=name, max_tokens=100)


def test_tokens_are_attributed_to_the_row_that_burned_them(work_env, no_rate_gate):
    def two_calls(inputs):
        _call_llm(100, 20)
        _call_llm(30, 5, model="m-other")
        return {"ok": True}

    work.register_kind("spendy", two_calls)
    item_id = work.enqueue("spendy", {})
    work._execute(None, item_id)

    item = work.get_item(item_id)
    assert item["llm_calls"] == 2
    assert item["tokens_prompt"] == 130
    assert item["tokens_completion"] == 25
    assert item["models"] == ["m-other", "m-test"]


def test_failed_run_still_records_what_it_spent(work_env, no_rate_gate):
    """Spend that produced nothing is the spend most worth seeing — a failure
    path that dropped its usage would hide exactly the expensive mistakes."""
    def burn_then_die(inputs):
        _call_llm(500, 40)
        raise RuntimeError("died after the expensive part")

    work.register_kind("burn", burn_then_die)
    item_id = work.enqueue("burn", {})
    work._execute(None, item_id)

    item = work.get_item(item_id)
    assert item["status"] == "failed"
    assert item["llm_calls"] == 1 and item["tokens_prompt"] == 500


def test_work_without_llm_calls_records_zero_not_null(work_env):
    work.register_kind("quiet", lambda i: {"ok": True})
    item_id = work.enqueue("quiet", {})
    work._execute(None, item_id)
    item = work.get_item(item_id)
    assert item["llm_calls"] == 0 and item["tokens_prompt"] == 0
    assert item["models"] == []


def test_usage_outside_a_work_item_is_not_collected(work_env, no_rate_gate):
    """The sink is opt-in per unit of work; an ordinary call must not append to
    whatever list happens to be current."""
    from lib import openai_calls as oc
    _call_llm(10, 10)
    assert oc._USAGE_SINK.get() is None


def test_columns_are_added_to_a_pre_p2_table(work_env):
    """Existing partitions have a work_items created before these columns
    existed. The PRAGMA-guarded ALTER must add them on next touch — and must be
    a no-op on the second pass."""
    from lib.db import get_connection

    with get_connection() as con:
        con.execute("DROP TABLE IF EXISTS work_items")
        con.execute(
            "CREATE TABLE work_items (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "kind TEXT NOT NULL, inputs_json TEXT NOT NULL DEFAULT '{}', "
            "status TEXT NOT NULL DEFAULT 'queued', attempt INTEGER NOT NULL DEFAULT 0, "
            "max_attempts INTEGER NOT NULL DEFAULT 1, origin TEXT NOT NULL DEFAULT '', "
            "error TEXT, artifacts_json TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "started_at TEXT, finished_at TEXT)"
        )
        con.execute("INSERT INTO work_items (kind) VALUES ('legacy')")
        con.commit()

    work._ensure_schema()
    work._ensure_schema()  # idempotent: a second ALTER would raise

    with get_connection() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(work_items)")}
    assert {"llm_calls", "tokens_prompt", "tokens_completion", "models_json"} <= cols
    # The pre-existing row reads back with the defaults, not NULLs.
    legacy = work.list_items()[0]
    assert legacy["kind"] == "legacy" and legacy["llm_calls"] == 0


def test_stats_reports_tokens_by_kind(app_client, monkeypatch):
    from lib import openai_calls as oc
    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc, "_LAST_CHAT_CALL", 0.0)

    def capture(inputs):
        _call_llm(200, 60)
        return {"ok": True}

    monkeypatch.setitem(work._KINDS, "capture_url", capture)
    resp = app_client.post("/api/capture", json={"url": "https://jobs.example.com/3"})
    _wait_status(app_client, resp.json()["work_id"])

    stats = app_client.get("/api/work/stats").json()
    row = [r for r in stats["tokens_by_kind"] if r["kind"] == "capture_url"][0]
    assert row["llm_calls"] == 1
    assert row["tokens_prompt"] == 200 and row["tokens_completion"] == 60
    # Tokens, never a dollar figure: prices change and a stored cost goes stale
    # silently (Sonnet 5's introductory rate ends 2026-08-31).
    assert not any("cost" in k or "usd" in k for k in row)
