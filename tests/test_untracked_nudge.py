"""The untracked-application nudge in generation results.

MCP clients receive the logging contract in the server instructions; WebMCP
agents see only the tool surface, so the contract also rides in the one
channel every client acts on — the tool result. Generating for a company
with no tracked application appends a nudge naming the exact follow-up call
(2026-08-30: ChatGPT generated a Travelers resume and never logged the
application, orphaning the file in Materials' untracked bucket).
"""
from __future__ import annotations

import json

from lib import config
from tools.generate import _untracked_note


def _track(*companies: str) -> None:
    config.STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATUS_FILE.write_text(json.dumps(
        {"applications": [{"company": c, "role": "SWE"} for c in companies]}
    ), encoding="utf-8")


class TestUntrackedNote:
    def test_untracked_company_gets_auto_logged(self, isolated_server):
        # 2026-08-31: the nudge became an auto-log — a document generated FOR
        # a company is a pipeline event; the user shouldn't do homework to
        # make their own artifact tracked. (The nudge survives as the
        # degraded path when the auto-log itself fails.)
        _track("Acme")
        note = _untracked_note("Travelers", "AI Engineer")
        assert "auto-logged" in note and "materials drafted" in note
        apps = json.loads(config.STATUS_FILE.read_text(encoding="utf-8"))["applications"]
        added = [a for a in apps if a["company"] == "Travelers"]
        assert added and added[0]["status"] == "materials drafted"

    def test_tracked_company_is_silent(self, isolated_server):
        _track("Travelers")
        assert _untracked_note("Travelers", "AI Engineer") == ""

    def test_match_is_case_insensitive_and_substring_both_ways(self, isolated_server):
        _track("Travelers Insurance")
        assert _untracked_note("travelers", "x") == ""
        _track("Travelers")
        assert _untracked_note("Travelers Insurance", "x") == ""

    def test_no_status_file_still_auto_logs(self, isolated_server):
        if config.STATUS_FILE.exists():
            config.STATUS_FILE.unlink()
        assert "auto-logged" in _untracked_note("Acme", "SWE")
        assert config.STATUS_FILE.exists()  # the log created the tracker

    def test_malformed_status_file_fails_soft(self, isolated_server):
        config.STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.STATUS_FILE.write_text("{not json", encoding="utf-8")
        # A nudge is never worth failing a generation — broken lookup stays quiet.
        assert _untracked_note("Acme", "SWE") == ""

    def test_empty_company_is_silent(self, isolated_server):
        _track("Acme")
        assert _untracked_note("", "SWE") == ""

    def test_generator_return_blocks_carry_the_note(self):
        """Both generators append the note to their success block — pin the
        call sites so a return-block rewrite can't silently drop the nudge."""
        import inspect

        from tools import generate

        src = inspect.getsource(generate)
        # filename rides along so EVAL artifacts can be excluded from the
        # auto-log — eval runs must never seed phantom pipeline entries.
        assert src.count("]) + _untracked_note(company, role, filename)") == 2
