"""Tests for the consolidated MCP tool surface (tools/consolidated.py).

The 11 domain facades must expose every capability of the legacy 85-tool
surface: each action maps to a real function, dispatch forwards exactly the
parameters the target accepts, and errors are actionable strings (never
tracebacks). The registered tool count is pinned so the surface can't
silently regrow.
"""
from __future__ import annotations

import inspect

import pytest

from tools import consolidated
from tools.consolidated import DOMAINS, FACADES, _actions_doc, _run


# ── surface shape ─────────────────────────────────────────────────────────────

def test_eleven_domain_tools():
    assert len(FACADES) == 11
    assert set(FACADES) == set(DOMAINS)


def test_every_action_targets_a_callable():
    for domain, actions in DOMAINS.items():
        for action, (fn, summary) in actions.items():
            assert callable(fn), f"{domain}.{action}"
            assert summary and isinstance(summary, str)


def test_action_count_covers_legacy_surface():
    # 84 actions ≙ the 85 legacy tools minus get_session_context's dual role
    # (session startup is folded into insights.session_context).
    total = sum(len(a) for a in DOMAINS.values())
    assert total == 85, f"action count changed: {total} — update this pin deliberately"


def test_facade_params_cover_every_target_param():
    """Every parameter of every target function must exist on its facade —
    otherwise a capability is silently unreachable."""
    for domain, actions in DOMAINS.items():
        facade_params = set(inspect.signature(FACADES[domain]).parameters)
        for action, (fn, _) in actions.items():
            for pname in inspect.signature(fn).parameters:
                assert pname in facade_params, (
                    f"{domain}.{action}: target param {pname!r} missing on facade"
                )


def test_registration_registers_eleven(monkeypatch):
    registered = []

    class FakeMCP:
        def tool(self, name=None):
            def deco(fn):
                registered.append(name or fn.__name__)
                return fn
            return deco

    consolidated.register(FakeMCP())
    assert sorted(registered) == sorted(FACADES)


def test_generated_docs_list_required_params():
    doc = _actions_doc("applications")
    assert "queue — " in doc
    assert "Requires: company, role, jd" in doc


def test_registered_docstrings_carry_action_docs():
    class FakeMCP:
        def tool(self, name=None):
            def deco(fn):
                return fn
            return deco

    consolidated.register(FakeMCP())
    for name, fn in FACADES.items():
        assert "Actions:" in fn.__doc__, name
        # Registering twice must not duplicate the generated section.
        consolidated.register(FakeMCP())
        assert fn.__doc__.count("Actions:") == 1, name


# ── dispatch behavior ─────────────────────────────────────────────────────────

def test_dispatch_forwards_only_provided_accepted_params(monkeypatch):
    seen = {}

    def fake_update(company, role, status="", next_steps="", contact="", notes=""):
        seen.update(company=company, role=role, status=status)
        return "ok"

    monkeypatch.setitem(DOMAINS["applications"], "update", (fake_update, "x"))
    out = FACADES["applications"](
        action="update", company="Acme", role="SWE", status="applied",
        # params for other actions must be ignored, not crash the target:
        decision="apply", fitment_score=9,
    )
    assert out == "ok"
    assert seen == {"company": "Acme", "role": "SWE", "status": "applied"}


def test_dispatch_unknown_action_lists_valid_ones():
    out = _run("applications", "frobnicate", {})
    assert "Unknown applications action" in out
    assert "queue" in out and "decide" in out


def test_dispatch_missing_required_params_is_actionable():
    out = FACADES["applications"](action="queue", company="Acme")
    assert "missing required parameter" in out
    assert "role" in out and "jd" in out


def test_dispatch_none_params_fall_back_to_target_defaults(monkeypatch):
    seen = {}

    def fake_search(query, location="", num_results=5, auto_queue=False):
        seen.update(num_results=num_results, auto_queue=auto_queue)
        return "ok"

    monkeypatch.setitem(DOMAINS["job_search"], "web", (fake_search, "x"))
    FACADES["job_search"](action="web", query="python")
    assert seen == {"num_results": 5, "auto_queue": False}


def test_end_to_end_workspace_check(tmp_path, monkeypatch):
    """One real (non-mocked) dispatch: workspace.check runs the actual tool."""
    import lib.config as cfg

    monkeypatch.setattr(cfg, "DATA_FOLDER", tmp_path, raising=False)
    out = FACADES["workspace"](action="check")
    assert isinstance(out, str) and out  # diagnostic text, no exception


# ── server registration modes ─────────────────────────────────────────────────

def test_chat_allowlist_matches_domain_names():
    from services.chat_service import CHAT_TOOL_ALLOWLIST

    assert set(CHAT_TOOL_ALLOWLIST) == set(FACADES)


@pytest.mark.parametrize("flag,expected", [("", 11), ("1", 85)])
def test_server_surface_size(flag, expected, tmp_path):
    """server.py registers 11 consolidated tools by default, 85 legacy ones
    behind JOBCONTEXT_LEGACY_TOOLS=1.

    Runs in a subprocess: re-importing server inside the test process would
    register the conftest autouse stubs (lambdas) as tools.
    """
    import os
    import subprocess
    import sys

    env = {**os.environ, "JOBCONTEXT_DATA_DIR": str(tmp_path)}
    env.pop("JOBCONTEXT_LEGACY_TOOLS", None)
    if flag:
        env["JOBCONTEXT_LEGACY_TOOLS"] = flag
    out = subprocess.run(
        [sys.executable, "-c",
         "import asyncio, server; print(len(asyncio.run(server.mcp.list_tools())))"],
        capture_output=True, text=True, env=env, timeout=180,
    )
    assert out.returncode == 0, out.stderr[-800:]
    assert int(out.stdout.strip().splitlines()[-1]) == expected
