"""Generated documents auto-track their application (2026-08-31 report).

A resume generated for an untracked company used to land in Materials'
untracked bucket with only a nudge to go log the application by hand. A
document generated FOR a company is a pipeline event: `_untracked_note` now
auto-logs the application at "materials drafted", which makes the file
tracked the moment it lands. EVAL artifacts are excluded (they're deleted
after scoring and must never seed phantom pipeline entries), and any
auto-log failure degrades to the old nudge — never a failed generation.
"""
from __future__ import annotations

import json

import pytest

import lib.config as cfg
from lib import user_context
from tools.generate import _untracked_note


@pytest.fixture()
def partition(tmp_path, monkeypatch):
    root = tmp_path / "user"
    root.mkdir()
    status = tmp_path / "status.json"
    monkeypatch.setattr(cfg, "STATUS_FILE", status, raising=False)
    token = user_context.set_data_folder(root)
    try:
        yield status
    finally:
        user_context.reset_data_folder(token)


def _apps(status_file):
    if not status_file.exists():
        return []
    return json.loads(status_file.read_text(encoding="utf-8")).get("applications", [])


class TestAutoTrack:
    def test_untracked_company_gets_auto_logged(self, partition):
        note = _untracked_note("Northwind Systems", "Staff Engineer", "Northwind Resume")
        assert "auto-logged" in note
        assert "materials drafted" in note
        apps = _apps(partition)
        assert len(apps) == 1
        assert apps[0]["company"] == "Northwind Systems"
        assert apps[0]["role"] == "Staff Engineer"
        assert apps[0]["status"] == "materials drafted"
        assert "Auto-logged" in apps[0]["notes"]

    def test_eval_artifacts_never_seed_pipeline_entries(self, partition):
        # The golden set names REAL employers — an eval run must not create
        # applications in the partition it runs in.
        note = _untracked_note("Northwind Systems", "Staff Engineer",
                               "EVAL GD-T01 Northwind Systems Staff Engineer")
        assert note == ""
        assert _apps(partition) == []

    def test_tracked_company_is_a_noop(self, partition):
        partition.write_text(json.dumps({"applications": [
            {"company": "Northwind Systems", "role": "SWE", "status": "applied"},
        ]}), encoding="utf-8")
        note = _untracked_note("Northwind Systems", "Staff Engineer", "f")
        assert note == ""
        assert len(_apps(partition)) == 1  # nothing added
        assert _apps(partition)[0]["status"] == "applied"  # nothing demoted

    def test_substring_tracked_company_is_a_noop(self, partition):
        partition.write_text(json.dumps({"applications": [
            {"company": "GM", "role": "SWE", "status": "applied"},
        ]}), encoding="utf-8")
        assert _untracked_note("General Motors GM", "SWE", "f") == ""

    def test_empty_company_is_a_noop(self, partition):
        assert _untracked_note("", "Role", "f") == ""
        assert _apps(partition) == []

    def test_auto_log_failure_degrades_to_the_nudge(self, partition, monkeypatch):
        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr("tools.job_hunt.update_application", boom)
        note = _untracked_note("Northwind Systems", "Staff Engineer", "f")
        assert "not a tracked application" in note  # old nudge, not a crash
        assert 'applications(action="update"' in note
