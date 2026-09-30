"""Tests for lib/discovery.py and scripts/discovery_report.py.

Pins every counting rule in the customer-discovery ledger so a traction number
quoted on an application can always be recomputed from records, and exercises
the SQLite layer (schema, constraints, signup import, CLI flows) on temp files.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import discovery as dr  # noqa: E402

_SCRIPT = _REPO_ROOT / "scripts" / "discovery_report.py"
_FINDINGS = _REPO_ROOT / "docs" / "discovery-findings.md"

_spec = importlib.util.spec_from_file_location("discovery_report", _SCRIPT)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cli
_spec.loader.exec_module(cli)


# --- dict-shaped fixtures (the rules are pure functions over this shape) -------------

def _consented(pid: int, **over) -> dict:
    p = {
        "id": pid, "name": f"P{pid}", "contact": f"p{pid}@x", "segment": "job_seeker",
        "channel": "linkedin_paid", "program": "interview", "status": "completed",
        "screener": {"segment_answer": "searching", "current_tools": [], "ai_assistant": "none"},
        "consent": {"version": "2026-09", "recorded_at": "2026-09-10T00:00:00",
                    "recording_ok": True, "quote_ok": True},
    }
    p.update(over)
    return p


def _interview(sid: int, pid: int, minutes: int = 30, **over) -> dict:
    s = {"id": sid, "participant_id": pid, "kind": "interview", "status": "completed",
         "duration_minutes": minutes, "themes": [], "quotes": []}
    s.update(over)
    return s


def _ledger(participants, sessions=(), incentives=()) -> dict:
    return {"program": {"interview_min_minutes": 20, "beta_sessions_to_complete": 3},
            "participants": list(participants), "sessions": list(sessions), "incentives": list(incentives)}


# --- counting rules -----------------------------------------------------------------

def test_interview_below_minimum_minutes_is_not_counted():
    rep = dr.build_report(_ledger([_consented(1)], [_interview(1, 1, minutes=15)]))
    assert rep.ok and rep.numbers["customer_interviews_completed"] == 0


def test_two_interviews_same_person_count_two_sessions_one_participant():
    rep = dr.build_report(_ledger([_consented(1)], [_interview(1, 1), _interview(2, 1)]))
    assert rep.numbers["customer_interviews_completed"] == 2
    assert rep.numbers["unique_participants_interviewed"] == 1
    assert rep.provenance["customer_interviews_completed"] == [1, 2]


def test_completed_interview_without_consent_is_a_hard_error():
    p = _consented(1); p["consent"] = {"version": "2026-09", "recorded_at": None}
    rep = dr.build_report(_ledger([p], [_interview(1, 1)]))
    assert not rep.ok and any("without consent" in e for e in rep.errors)
    assert rep.numbers["customer_interviews_completed"] == 0


def test_internal_participant_never_counts():
    rep = dr.build_report(_ledger([_consented(1, segment="internal")], [_interview(1, 1)]))
    assert not rep.ok and rep.numbers["customer_interviews_completed"] == 0


def test_scheduled_and_no_show_sessions_do_not_count():
    rep = dr.build_report(_ledger([_consented(1)], [
        _interview(1, 1, status="scheduled"), _interview(2, 1, status="no_show")]))
    assert rep.ok and rep.numbers["customer_interviews_completed"] == 0


def test_beta_completion_requires_three_sessions():
    p = _consented(1, program="beta", status="active")
    sessions = [{"id": i, "participant_id": 1, "kind": "beta_session", "status": "completed",
                 "duration_minutes": 40, "themes": [], "quotes": []} for i in (1, 2)]
    rep = dr.build_report(_ledger([p], sessions))
    assert rep.numbers["beta_testers_enrolled"] == 1 and rep.numbers["beta_testers_completed"] == 0
    sessions.append({"id": 3, "participant_id": 1, "kind": "beta_session", "status": "completed",
                     "duration_minutes": 40, "themes": [], "quotes": []})
    assert dr.build_report(_ledger([p], sessions)).numbers["beta_testers_completed"] == 1


def test_beta_dropped_status_is_not_enrolled():
    rep = dr.build_report(_ledger([_consented(1, program="beta", status="dropped")]))
    assert rep.numbers["beta_testers_enrolled"] == 0


def test_incentive_sent_without_reference_is_error():
    inc = {"id": 1, "participant_id": 1, "earned_by": "1", "type": "gift_card", "amount_usd": 25, "status": "sent"}
    rep = dr.build_report(_ledger([_consented(1)], [_interview(1, 1)], [inc]))
    assert any("no reference" in e for e in rep.errors)


def test_incentive_not_backed_by_earned_condition_is_error():
    inc = {"id": 1, "participant_id": 1, "earned_by": "9", "type": "gift_card", "amount_usd": 25,
           "status": "sent", "reference": "x"}
    rep = dr.build_report(_ledger([_consented(1)], [_interview(1, 1)], [inc]))
    assert any("has not earned" in e for e in rep.errors)


def test_paid_only_sums_sent_rows():
    incs = [{"id": 1, "participant_id": 1, "earned_by": "1", "type": "gift_card", "amount_usd": 25,
             "status": "sent", "reference": "r1"},
            {"id": 2, "participant_id": 2, "earned_by": "2", "type": "gift_card", "amount_usd": 25,
             "status": "pending"}]
    rep = dr.build_report(_ledger([_consented(1), _consented(2)], [_interview(1, 1), _interview(2, 2)], incs))
    assert rep.ok and rep.numbers["incentives_paid_usd"] == 25


def test_owed_incentive_warns_for_paid_channel_but_not_network():
    rep = dr.build_report(_ledger([_consented(1), _consented(2, channel="network_free")],
                                  [_interview(1, 1), _interview(2, 2)]))
    assert rep.ok
    assert any("participant 1: earned 1" in w for w in rep.warnings)
    assert not any("participant 2:" in w for w in rep.warnings)


def test_duplicate_and_unknown_ids_are_errors():
    rep = dr.build_report(_ledger([_consented(1), _consented(1)], [_interview(1, 1), _interview(1, 99)]))
    assert any("duplicate participant" in e for e in rep.errors)
    assert any("duplicate id" in e for e in rep.errors)
    assert any("unknown participant" in e for e in rep.errors)


def test_public_quote_suppressed_when_quote_consent_false():
    p = _consented(1); p["consent"]["quote_ok"] = False
    rep = dr.build_report(_ledger([p], [_interview(1, 1, quotes=[{"text": "never", "public": True}])]))
    assert rep.ok and rep.public_quotes == [] and any("suppressed" in w for w in rep.warnings)


def test_public_quote_is_segment_attributed_only():
    s = _interview(1, 1, quotes=[{"text": "I retype everything.", "public": True}])
    rep = dr.build_report(_ledger([_consented(1, name="Real Name")], [s]))
    assert rep.public_quotes == [{"segment": "job_seeker", "text": "I retype everything."}]
    block = dr.render_findings_block(rep, "2026-10-01")
    assert "Real Name" not in block and "job seeker" in block


# --- SQLite layer -----------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "discovery.db"
    con = dr.connect(path)
    yield path, con
    con.close()


def test_schema_init_is_idempotent_and_seeds_program(ledger):
    path, con = ledger
    assert con.execute("SELECT interview_min_minutes, beta_sessions_to_complete FROM program").fetchone()[:] == (20, 3)
    con.close()
    con2 = dr.connect(path)  # second open must not fail or duplicate the program row
    assert con2.execute("SELECT COUNT(*) FROM program").fetchone()[0] == 1
    con2.close()


def test_check_constraints_reject_bad_segment_and_unknown_participant(ledger):
    _, con = ledger
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO participants (name, contact, segment, channel, program, status, created_at)"
                    " VALUES ('x', 'x@x', 'martian', 'linkedin_paid', 'interview', 'screened', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO sessions (participant_id, kind, status, created_at) VALUES (999, 'interview', 'scheduled', 'now')")


def test_add_signup_maps_segment_and_dedupes_by_contact(ledger):
    _, con = ledger
    pid = dr.add_signup(con, "Ann", "Ann@Example.com", "I coach people who are", "Teal, Notion", "Claude")
    assert pid == 1
    assert dr.add_signup(con, "Ann again", "ann@example.com", "searching", "", "") is None
    row = dict(con.execute("SELECT segment, status, screener_json FROM participants WHERE id = 1").fetchone())
    assert row["segment"] == "coach" and row["status"] == "screened"
    assert json.loads(row["screener_json"])["current_tools"] == ["Teal", "Notion"]


def test_import_signups_from_forms_csv(ledger, tmp_path):
    path, con = ledger
    csv_path = tmp_path / "signups.csv"
    csv_path.write_text(
        "Timestamp,Name,Email address,Are you actively job searching?,What do you use today?,Which AI assistant?\n"
        "2026-09-20,Bo,bo@x.com,Actively job searching,Huntr,ChatGPT\n"
        "2026-09-20,Cy,cy@x.com,Career change,,none\n"
        "2026-09-21,Bo,bo@x.com,Actively job searching,Huntr,ChatGPT\n",
        encoding="utf-8")
    assert dr.import_signups(con, csv_path) == (2, 1)
    segs = [r[0] for r in con.execute("SELECT segment FROM participants ORDER BY id")]
    assert segs == ["job_seeker", "career_changer"]


def test_load_ledger_roundtrips_consent_themes_and_quotes(ledger):
    _, con = ledger
    pid = dr.add_signup(con, "Di", "di@x", "searching", "", "ChatGPT")
    con.execute("UPDATE participants SET consent_version='2026-09', consent_recorded_at='2026-09-10T10:00:00',"
                " consent_recording_ok=1, consent_quote_ok=1 WHERE id=?", (pid,))
    con.execute("INSERT INTO sessions (participant_id, kind, status, duration_minutes, themes, created_at)"
                " VALUES (?, 'interview', 'completed', 31, 're-explaining, trust', 'now')", (pid,))
    con.execute("INSERT INTO quotes (session_id, text, public) VALUES (1, 'I retype everything', 1)")
    con.commit()
    led = dr.load_ledger(con)
    assert led["participants"][0]["consent"]["quote_ok"] is True
    assert led["sessions"][0]["themes"] == ["re-explaining", "trust"]
    rep = dr.build_report(led)
    assert rep.ok and rep.numbers["customer_interviews_completed"] == 1
    assert rep.public_quotes[0]["text"] == "I retype everything"


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    path = tmp_path / "discovery.db"
    run = lambda *a: cli.main(["--ledger", str(path), *a])  # noqa: E731
    assert run("init") == 0
    con = dr.connect(path); pid = dr.add_signup(con, "Ed", "ed@x", "searching", "", ""); con.close()
    assert run("session", "add", str(pid), "--when", "2026-09-18T18:00") == 0
    # completed interview before consent → hard error
    assert run("session", "done", "1", "--minutes", "30", "--themes", "trust") == 0
    assert run("check") == 1
    assert "without consent" in capsys.readouterr().out
    assert run("consent", str(pid)) == 0
    assert run("check") == 0
    # incentive must reference an earned session, and sent needs a reference
    assert run("incentive", str(pid), "--earned-by", "1", "--amount", "25") == 0
    assert run("check") == 1  # sent with no reference
    con = dr.connect(path); con.execute("UPDATE incentives SET reference='amz-1'"); con.commit(); con.close()
    assert run("check") == 0
    assert run("--as-of", "2026-10-01", "snapshot") == 0
    snap = json.loads(next(tmp_path.glob("discovery_snapshot_2026-10-01_*.json")).read_text(encoding="utf-8"))
    assert snap["numbers"]["customer_interviews_completed"] == 1
    assert snap["provenance"]["customer_interviews_completed"] == [1]
    assert snap["ledger_sha256"] == dr.ledger_sha256(path)
    page = tmp_path / "f.md"
    monkeypatch.setattr(dr, "FINDINGS_PATH", page)
    page.write_text(f"intro\n{dr.FINDINGS_BEGIN}\nold\n{dr.FINDINGS_END}\noutro\n", encoding="utf-8")
    assert run("--as-of", "2026-10-01", "findings", str(page)) == 0
    text = page.read_text(encoding="utf-8")
    assert "old" not in text and "| Customer interviews completed | 1 |" in text and "outro" in text


def test_findings_page_has_managed_block():
    text = _FINDINGS.read_text(encoding="utf-8")
    assert dr.FINDINGS_BEGIN in text and dr.FINDINGS_END in text


def test_findings_writer_fails_without_block(tmp_path, monkeypatch):
    rep = dr.build_report(_ledger([_consented(1)], [_interview(1, 1)]))
    bare = tmp_path / "bare.md"; bare.write_text("no block", encoding="utf-8")
    monkeypatch.setattr(dr, "FINDINGS_PATH", bare)
    with pytest.raises(SystemExit):
        dr.write_findings(bare, rep, "2026-10-01")
