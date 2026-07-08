"""LLM tool calls pass strings where schemas say list[str] — never explode
them into characters (the Cox follow_up_commitments corruption)."""
from __future__ import annotations

import pytest

import lib.config as cfg


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    from lib.user_provisioning import provision_user_data

    monkeypatch.setattr(cfg, "DATA_FOLDER", str(tmp_path), raising=False)
    # Static module-level file paths were computed at import from the real
    # DATA_FOLDER — repoint them or the test writes into the repo's live
    # data/ files (which is exactly how a leaked entry broke the migration
    # roundtrip test).
    monkeypatch.setattr(cfg, "INTERVIEWS_FILE", tmp_path / "interviews.json", raising=False)
    provision_user_data(tmp_path)
    return tmp_path


def test_string_list_fields_coerce_not_explode(workspace):
    from tools.interviews import get_interviews, log_interview

    result = log_interview(
        company="Cox Automotive",
        role="Senior Platform Engineer",
        interview_date="2026-07-08",
        interview_type="recruiter_screen",
        follow_up_commitments="Proceed as agreed; send Azure architecture examples.",
        surfaced_priorities="System design panel is the heavy round",
        tags="recruiter,comp-discussed",
        verbatim_quotes="Budget tops out at 135K base",
    )
    assert result.startswith("✓")
    out = get_interviews(company="Cox Automotive", include_full=True)
    assert "Proceed as agreed; send Azure architecture examples." in out
    # No character explosion: single letters never appear as standalone items.
    assert "'P', 'r', 'o'" not in out and '"P", "r"' not in out


def test_string_merge_on_update_stays_intact(workspace):
    from tools.interviews import get_interviews, log_interview

    log_interview(
        company="Cox Automotive", role="SWE", interview_date="2026-07-08",
        interview_type="recruiter_screen",
        follow_up_commitments=["Send portfolio link"],
    )
    log_interview(
        company="Cox Automotive", role="SWE", interview_date="2026-07-08",
        interview_type="recruiter_screen",
        follow_up_commitments="Follow up on comp band by Friday",
    )
    out = get_interviews(company="Cox Automotive", include_full=True)
    assert "Send portfolio link" in out
    assert "Follow up on comp band by Friday" in out
