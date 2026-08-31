"""Finite request timeouts on every remote LLM client.

The SDK default is 600s per request with internal retries on top — a stalled
provider connection held a dispatcher slot (there are two, shared by every
tenant) while the work row honestly read 'running' (2026-08-31: two
chat-submitted generations wedged the control plane this way). These pin
that every remote provider branch constructs its client with the finite
timeout, and that a far-past-window running row says so instead of chirping
"poll again in 15 seconds".
"""
from __future__ import annotations

import sqlite3

import pytest

from lib import config as cfg

# Captured at import, before conftest's autouse fixture stubs
# lib.config.get_llm_client to (None, None) for every non-live test — same
# pattern as test_generate_work._REAL_RESUME.
_REAL_GET_LLM_CLIENT = cfg.get_llm_client

_EXPECTED_TIMEOUT = 120.0


def _client_for(monkeypatch, provider: str, **cfg_overrides):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    overrides = {"llm_provider": provider, **cfg_overrides}
    monkeypatch.setattr(cfg, "get_active_config", lambda: overrides)
    client, _model = _REAL_GET_LLM_CLIENT()
    return client


class TestRemoteClientTimeouts:
    def test_openai_client_carries_finite_timeout(self, monkeypatch):
        client = _client_for(monkeypatch, "openai", openai_api_key="sk-test")
        assert client is not None
        assert float(client.timeout) == _EXPECTED_TIMEOUT
        assert client.max_retries == 2

    def test_anthropic_compat_client_carries_finite_timeout(self, monkeypatch):
        client = _client_for(monkeypatch, "anthropic", anthropic_api_key="sk-ant-test")
        assert client is not None
        assert float(client.timeout) == _EXPECTED_TIMEOUT

    def test_foundry_client_carries_finite_timeout(self, monkeypatch):
        client = _client_for(
            monkeypatch, "foundry",
            azure_foundry_endpoint="https://example.openai.azure.com",
            azure_foundry_api_key="key",
        )
        assert client is not None
        assert float(client.timeout) == _EXPECTED_TIMEOUT

    def test_ollama_keeps_the_sdk_default(self, monkeypatch):
        """Local inference is legitimately slow and a localhost socket cannot
        black-hole the cloud dispatcher — the budget stays unbounded there."""
        client = _client_for(monkeypatch, "ollama")
        assert client is not None
        # SDK default is an httpx.Timeout object, not our finite float.
        assert client.timeout != _EXPECTED_TIMEOUT

    def test_timeout_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "45")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setattr(
            cfg, "get_active_config",
            lambda: {"llm_provider": "openai", "openai_api_key": "sk-test"},
        )
        client, _ = _REAL_GET_LLM_CLIENT()
        assert float(client.timeout) == 45.0


class TestStaleRunningHonesty:
    def _age_row(self, row_id: int, minutes: int) -> None:
        from lib.db import get_connection

        with get_connection() as con:
            con.execute(
                "UPDATE work_items SET status='running', "
                "started_at=datetime('now', ?) WHERE id = ?",
                (f"-{minutes} minutes", row_id),
            )
            con.commit()

    def test_far_past_window_running_row_says_so(self, isolated_server):
        from lib import work
        from tools import generate_async, generate_work

        generate_async.submit_resume("Acme", "Staff Eng", "jd")
        row = [r for r in work.list_items()
               if r["kind"] == generate_work.KIND_RESUME][0]
        self._age_row(row["id"], 12)

        out = generate_async.generation_status(row["id"])
        assert "running" in out
        assert "well past" in out
        assert "~12 minutes" in out

    def test_fresh_running_row_keeps_the_short_poll_hint(self, isolated_server):
        from lib import work
        from tools import generate_async, generate_work

        generate_async.submit_resume("Acme", "Staff Eng", "jd")
        row = [r for r in work.list_items()
               if r["kind"] == generate_work.KIND_RESUME][0]
        self._age_row(row["id"], 1)

        out = generate_async.generation_status(row["id"])
        assert "Poll again in ~15 seconds" in out
        assert "well past" not in out

    def test_unparseable_stamp_fails_soft(self, isolated_server):
        from tools.generate_async import _running_minutes

        assert _running_minutes({"started_at": "not-a-date"}) is None
        assert _running_minutes({}) is None
