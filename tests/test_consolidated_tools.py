"""Tests for the consolidated MCP tool surface (tools/consolidated.py).

The 11 domain facades must expose every capability of the legacy 87-tool
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
    # 86 actions ≙ the 87 legacy tools minus get_session_context's dual role
    # (session startup is folded into insights.session_context). Bumped from
    # 85/84 when stories gained update/delete (a wrong fact could only be
    # superseded by a second entry before, never corrected in place).
    total = sum(len(a) for a in DOMAINS.values())
    assert total == 87, f"action count changed: {total} — update this pin deliberately"


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


@pytest.mark.parametrize("flag,expected", [("", 11), ("1", 87)])
def test_server_surface_size(flag, expected, tmp_path):
    """server.py registers 11 consolidated tools by default, 87 legacy ones
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


# ── facade type coercion (str-schema -> real int/list/dict params) ────────────
#
# Facades intentionally expose plain strings for params whose real target
# takes an int/list/dict (see module docstring) — not every MCP client
# renders nested array/object schemas well. _coerce_param() bridges that gap.
# These regression-test the bugs that existed before it did: a str/int
# mismatch matched nothing with no error (post_metrics post_id), and a
# comma-separated string handed straight to a list param got shredded into
# single characters by downstream ', '.join() calls (people tags).

from tools.consolidated import _coerce_param  # noqa: E402


class TestCoerceParam:
    def test_int_param_accepts_plain_numeric_string(self):
        assert _coerce_param("post_id", "39", int | None) == 39

    def test_int_param_strips_leading_hash(self):
        """get_linkedin_posts() prints ids as '#39' — that exact string must
        also work, not just the bare number."""
        assert _coerce_param("post_id", "#39", int | None) == 39

    def test_int_param_rejects_non_numeric_with_clean_error(self):
        with pytest.raises(ValueError, match="post_id must be a number"):
            _coerce_param("post_id", "not-a-number", int | None)

    def test_list_param_splits_comma_separated_string(self):
        assert _coerce_param("tags", "java, spring, sql", list[str] | None) == [
            "java", "spring", "sql",
        ]

    def test_list_param_passthrough_when_already_a_list(self):
        assert _coerce_param("tags", ["java", "spring"], list[str] | None) == [
            "java", "spring",
        ]

    def test_dict_param_parses_json_string(self):
        out = _coerce_param("audience_highlights", '{"top_job_title": "SWE"}', dict | None)
        assert out == {"top_job_title": "SWE"}

    def test_dict_param_rejects_non_json_with_clean_error(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            _coerce_param("audience_highlights", "not json", dict | None)

    def test_dict_param_rejects_json_array_with_clean_error(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            _coerce_param("audience_highlights", "[1, 2]", dict | None)

    def test_none_passes_through_untouched(self):
        assert _coerce_param("post_id", None, int | None) is None


def test_run_returns_actionable_error_instead_of_raising():
    """A bad facade value must come back as a '✗ domain.action: ...' string,
    never propagate as a raw exception through the MCP tool boundary."""
    out = _run("brand", "post_metrics", {"post_id": "not-a-number"})
    assert out.startswith("✗ brand.post_metrics:")
    assert "post_id must be a number" in out


class TestPostLogIdentityRegression:
    """End-to-end regression for the bug where every log_linkedin_post() call
    sharing the same `source` (e.g. 'linkedin') silently overwrote whichever
    post happened to share it, and post_id (typed str on the facade but int
    on the real function) never matched anything."""

    def test_post_id_as_string_updates_the_right_post(self, isolated_server):
        FACADES["brand"](action="post_log", text="First.", source="linkedin", auto_log_tone=False)
        FACADES["brand"](action="post_log", text="Second.", source="linkedin", auto_log_tone=False)
        FACADES["brand"](
            action="post_log", text="Second, corrected.", source="linkedin",
            post_id="2", auto_log_tone=False,
        )
        import server as srv
        import json

        posts = json.loads(srv.LINKEDIN_POSTS_FILE.read_text())["posts"]
        assert [p["text"] for p in posts] == ["First.", "Second, corrected."]

    def test_post_metrics_by_hash_prefixed_id(self, isolated_server):
        FACADES["brand"](action="post_log", text="Hi.", source="linkedin", auto_log_tone=False)
        out = FACADES["brand"](action="post_metrics", post_id="#1", reactions=10)
        assert "✓" in out and "reactions=10" in out


class TestPeopleTagsRegression:
    """Regression for tags being shredded into individual characters when a
    comma-separated string reached log_person()'s list[str] parameter."""

    def test_comma_separated_tags_stored_as_a_real_list(self, isolated_server):
        FACADES["people"](
            action="log", name="Puja Priyadarshini", relationship="recruiter",
            company="Acme", context="Met at a conference.",
            tags="java, spring, sql, python",
        )
        import server as srv
        import json

        people = json.loads(srv.PEOPLE_FILE.read_text())["people"]
        assert people[0]["tags"] == ["java", "spring", "sql", "python"]


class TestStoriesUpdateDelete:
    """Bug #6: a story with a wrong fact could previously only be
    'superseded' by a second entry, leaving the wrong one retrievable."""

    def test_update_corrects_story_in_place(self, isolated_server):
        FACADES["stories"](action="log", story="Original wrong fact.", tags="testing")
        FACADES["stories"](action="update", story_id="1", story="Corrected fact.")
        import server as srv
        import json

        stories = json.loads(srv.PERSONAL_CONTEXT_FILE.read_text())["stories"]
        assert len(stories) == 1
        assert stories[0]["story"] == "Corrected fact."

    def test_delete_removes_story(self, isolated_server):
        FACADES["stories"](action="log", story="Duplicate entry.", tags="testing")
        FACADES["stories"](action="delete", story_id="1")
        import server as srv
        import json

        stories = json.loads(srv.PERSONAL_CONTEXT_FILE.read_text())["stories"]
        assert stories == []

    def test_update_unknown_id_returns_clean_error(self, isolated_server):
        out = FACADES["stories"](action="update", story_id="999", story="X.")
        assert "999" in out and "✗" in out


def test_outreach_status_enum_choices_surfaced_in_generated_docs():
    """Bug #7: an enum-typed param's allowed values must be discoverable
    from the tool description, not only from the error after a bad guess."""
    doc = _actions_doc("people")
    assert "outreach_status (one of: none, drafted, sent, responded)" in doc

