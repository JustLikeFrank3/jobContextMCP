"""Tests for the deterministic provenance gate (lib/provenance.py) and its
integration into the LangGraph resume pipeline (tools/langgraph_pipeline.py).

No LLM calls anywhere here — the gate is deterministic by design, and the
routing/persistence tests drive the node and router functions directly with
crafted state.
"""
from __future__ import annotations

import json

import pytest

from lib.provenance import check_claims, extract_claims, record_run


# ===========================================================================
# extract_claims — what counts as a numeric claim
# ===========================================================================

class TestExtractClaims:
    def test_percentages(self):
        assert extract_claims("cut latency 34% and errors by 12 percent") == ["34%", "12 percent"]

    def test_currency_and_magnitude(self):
        claims = extract_claims("saved $1.2M yearly on a $500k budget serving 15k users")
        assert "$1.2M" in claims
        assert "$500k" in claims
        assert "15k" in claims

    def test_multipliers_and_grouped_numbers(self):
        claims = extract_claims("3x throughput across 10,000 devices")
        assert "3x" in claims
        assert "10,000" in claims

    def test_years_are_claims(self):
        assert "2019" in extract_claims("Led the team from 2019 to 2022")

    def test_duplicates_collapse_by_normalized_form(self):
        assert extract_claims("34% then again 34% and 34 %") == ["34%"]

    def test_plain_prose_has_no_claims(self):
        assert extract_claims("Led a team and shipped the platform reliably") == []

    def test_empty_and_none_safe(self):
        assert extract_claims("") == []
        assert extract_claims(None) == []


# ===========================================================================
# check_claims — membership against source material
# ===========================================================================

class TestCheckClaims:
    SOURCES = [
        "Reduced p99 latency 34% at Initech (2019-2022).",
        "Cost program saved $1.2M annually.",
    ]

    def test_sourced_claims_pass(self):
        draft = "Cut latency 34% and saved $1.2M between 2019 and 2022."
        assert check_claims(draft, self.SOURCES) == []

    def test_fabricated_claim_caught(self):
        draft = "Cut latency 34% and improved uptime 99.99% serving 40k users."
        violations = check_claims(draft, self.SOURCES)
        assert "99.99%" in violations
        assert "40k" in violations
        assert "34%" not in violations

    def test_formatting_differences_dont_false_positive(self):
        # source has "$1.2M"; draft says "$1.2m" / source "34%" vs "34 percent"
        draft = "Delivered $1.2m in savings, a 34 percent latency win."
        assert check_claims(draft, self.SOURCES) == []

    def test_comma_grouping_normalized(self):
        assert check_claims("served 10,000 users", ["scaled to 10000 users"]) == []

    def test_empty_sources_flag_everything(self):
        assert check_claims("grew revenue 25%", []) == ["25%"]


# ===========================================================================
# record_run — persistence (isolated sqlite via explicit path)
# ===========================================================================

class TestRecordRun:
    def test_row_written_with_verdict_and_json_fields(self, tmp_path):
        db = tmp_path / "prov.db"
        record_run(
            kind="resume",
            company="Initech",
            role="SWE",
            job_description="build things",
            chunk_texts=["chunk one", "chunk two"],
            claims=["34%"],
            violations=[],
            verdict="passed",
            revisions=1,
            db_path=db,
        )
        import sqlite3

        rows = sqlite3.connect(db).execute(
            "SELECT kind, company, verdict, revisions, claims, violations, chunk_hashes "
            "FROM generation_provenance"
        ).fetchall()
        assert len(rows) == 1
        kind, company, verdict, revisions, claims, violations, chunk_hashes = rows[0]
        assert (kind, company, verdict, revisions) == ("resume", "Initech", "passed", 1)
        assert json.loads(claims) == ["34%"]
        assert json.loads(violations) == []
        assert len(json.loads(chunk_hashes)) == 2

    def test_never_raises_on_broken_db(self, tmp_path):
        # a directory where a db file should be — connection will fail
        record_run(
            kind="resume", company="", role="", job_description="",
            chunk_texts=[], claims=[], violations=[], verdict="failed",
            revisions=0, db_path=tmp_path,
        )  # must not raise


# ===========================================================================
# Pipeline integration — gate node + routing (no LLM)
# ===========================================================================

class TestPipelineIntegration:
    def _state(self, **overrides) -> dict:
        state = {
            "company": "Initech",
            "role": "SWE",
            "job_description": "We need 5 years of Python.",
            "retrieved_context": "",
            "retrieved_hits": [{"text": "Reduced latency 34% in 2021."}],
            "tone_profile": "",
            "star_stories": "Saved $1.2M in the cloud migration.",
            "draft": "",
            "review_notes": "",
            "revision_count": 0,
            "approved": False,
            "provenance_violations": [],
        }
        state.update(overrides)
        return state

    def test_gate_passes_sourced_draft(self, monkeypatch, tmp_path):
        from tools import langgraph_pipeline as lp

        master = tmp_path / "master.txt"
        master.write_text("Python engineer since 2018.", encoding="utf-8")
        monkeypatch.setattr(
            lp.config, "get_active_master_resume_path", lambda: master, raising=False
        )
        state = self._state(
            draft="Cut latency 34% in 2021; saved $1.2M. Python since 2018."
        )
        assert lp.validate_provenance_node(state) == {"provenance_violations": []}

    def test_gate_catches_fabrication(self, monkeypatch, tmp_path):
        from tools import langgraph_pipeline as lp

        master = tmp_path / "master.txt"
        master.write_text("Python engineer since 2018.", encoding="utf-8")
        monkeypatch.setattr(
            lp.config, "get_active_master_resume_path", lambda: master, raising=False
        )
        state = self._state(draft="Improved conversion 47% for 2M users.")
        result = lp.validate_provenance_node(state)
        assert "47%" in result["provenance_violations"]
        assert "2M" in result["provenance_violations"]

    def test_router_blocks_approved_draft_with_violations(self):
        """The core of the gate: reviewer approval alone is not enough."""
        from tools.langgraph_pipeline import route_after_review

        state = self._state(approved=True, provenance_violations=["47%"])
        assert route_after_review(state) == "revise"

    def test_router_finalizes_when_both_gates_clean(self):
        from tools.langgraph_pipeline import route_after_review

        state = self._state(approved=True, provenance_violations=[])
        assert route_after_review(state) == "finalize"

    def test_router_respects_revision_budget(self):
        from tools.langgraph_pipeline import route_after_review

        state = self._state(approved=False, provenance_violations=["47%"], revision_count=2)
        assert route_after_review(state) == "finalize"

    def test_violations_rendered_into_revise_feedback(self):
        from tools.langgraph_pipeline import _provenance_feedback

        text = _provenance_feedback(self._state(provenance_violations=["47%", "2M"]))
        assert "47%" in text and "2M" in text
        assert "PROVENANCE VIOLATIONS" in text
        assert _provenance_feedback(self._state()) == ""

    def test_graph_wiring_includes_gate(self):
        """Every path to review passes through validate_provenance."""
        from tools.langgraph_pipeline import _build_graph

        compiled = _build_graph()
        graph = compiled.get_graph()
        edges = {(e.source, e.target) for e in graph.edges}
        assert ("draft", "validate_provenance") in edges
        assert ("validate_provenance", "review") in edges
        assert ("revise", "validate_provenance") in edges
        # the old unguarded paths must be gone
        assert ("draft", "review") not in edges
        assert ("revise", "review") not in edges


class TestBoundaryAwareContainment:
    """Substring lookalikes must not count as sources (the '2M in $1.2M' bug,
    caught during development by test_gate_catches_fabrication)."""

    def test_claim_inside_larger_number_is_violation(self):
        assert check_claims("served 2M users", ["saved $1.2M"]) == ["2M"]
        assert check_claims("improved 34%", ["improved 134%"]) == ["34%"]

    def test_currency_prefix_still_backs_bare_number(self):
        assert check_claims("delivered 500k in savings", ["a $500k program"]) == []


class TestRetrieveDegradation:
    def test_retrieve_node_degrades_without_embeddings(self, monkeypatch):
        """Anthropic-only deployments have no OpenAI embeddings key — the
        pipeline must draft without emphasis hints, not die (field incident:
        Pi, Jul 2026)."""
        import lib.rag as rag
        from tools import langgraph_pipeline as lp

        def boom(*a, **k):
            raise ValueError("openai_api_key not set in config.json.")

        monkeypatch.setattr(rag, "search", boom)
        out = lp.retrieve_node({"job_description": "any JD"})
        assert out == {"retrieved_context": "", "retrieved_hits": []}


# ===========================================================================
# Single-shot paths (tools/generate.py) + second graph (workflows/langgraph)
# ===========================================================================

class TestSingleShotGate:
    def test_note_passes_and_records(self, monkeypatch):
        from tools import generate as gen

        recorded = {}
        monkeypatch.setattr(
            "lib.provenance.record_run", lambda **kw: recorded.update(kw)
        )
        note = gen._provenance_note(
            "resume", "Initech", "SWE", "jd text",
            content="Cut latency 34%.", source_text="latency fell 34% in prod",
        )
        assert note.startswith("✓ Provenance")
        assert recorded["verdict"] == "passed"
        assert recorded["kind"] == "resume"

    def test_note_flags_fabrication_and_records_failure(self, monkeypatch):
        from tools import generate as gen

        recorded = {}
        monkeypatch.setattr(
            "lib.provenance.record_run", lambda **kw: recorded.update(kw)
        )
        note = gen._provenance_note(
            "cover_letter", "Initech", "SWE", "jd",
            content="Grew revenue 47% to $9M.", source_text="no numbers here",
        )
        assert note.startswith("⚠ Provenance: unsourced claims")
        assert "47%" in note and "$9M" in note
        assert recorded["verdict"] == "failed"
        assert recorded["violations"] == ["47%", "$9M"]

    def test_note_never_raises(self, monkeypatch):
        from tools import generate as gen

        def boom(**kw):
            raise RuntimeError("db on fire")

        monkeypatch.setattr("lib.provenance.record_run", boom)
        # record_run itself swallows, but simulate an unexpected error path
        monkeypatch.setattr("lib.provenance.check_claims", boom)
        note = gen._provenance_note("resume", "", "", "", "x", "y")
        assert note.startswith("⚠ Provenance check skipped")


class TestResumeGraphReactsToVerdict:
    def _review(self, draft, revisions=0):
        from workflows.langgraph.resume_graph import _node_review

        return _node_review({
            "draft": draft, "revisions": revisions, "max_revisions": 1,
        })

    def test_provenance_warning_triggers_revision(self):
        out = self._review(
            "✓ Resume generated for X @ Y\n  ⚠ Provenance: unsourced claims — verify before sending: 47%"
        )
        assert out["needs_revision"] is True
        assert any("Provenance gate" in f for f in out["review_feedback"])

    def test_clean_verdict_passes_review(self):
        out = self._review(
            "✓ Resume generated for X @ Y\n  ✓ Provenance: all numeric claims trace to source material"
        )
        assert out["needs_revision"] is False
        assert out["review_feedback"] == []


class TestDurableMetrics:
    def test_gauges_from_db(self, tmp_path):
        from lib.provenance import render_durable_metrics

        db = tmp_path / "prov.db"
        for verdict, violations in [("passed", []), ("passed", []), ("failed", ["47%", "2M"])]:
            record_run(
                kind="resume", company="X", role="Y", job_description="jd",
                chunk_texts=[], claims=["1%"], violations=violations,
                verdict=verdict, revisions=0, db_path=db,
            )
        out = render_durable_metrics(db_path=db)
        assert 'provenance_runs_total{verdict="passed",kind="resume"} 2' in out
        assert 'provenance_runs_total{verdict="failed",kind="resume"} 1' in out
        assert 'provenance_violations_recorded_total{kind="resume"} 2' in out

    def test_empty_db_renders_nothing(self, tmp_path):
        from lib.provenance import render_durable_metrics
        from lib.db import get_connection

        db = tmp_path / "empty.db"
        with get_connection(path=db):
            pass  # create schema only
        assert render_durable_metrics(db_path=db) == ""

    def test_never_raises(self, tmp_path):
        from lib.provenance import render_durable_metrics

        assert render_durable_metrics(db_path=tmp_path) == ""  # dir, not a db


class TestMasterEditAudit:
    def test_edit_recorded(self, tmp_path):
        from lib.provenance import record_master_edit
        import sqlite3

        db = tmp_path / "audit.db"
        record_master_edit("931 passing tests", "1484 passing tests", db_path=db)
        rows = sqlite3.connect(db).execute(
            "SELECT oid, old_text, new_text FROM master_resume_edits"
        ).fetchall()
        assert rows == [("", "931 passing tests", "1484 passing tests")]

    def test_never_raises(self, tmp_path):
        from lib.provenance import record_master_edit

        record_master_edit("a", "b", db_path=tmp_path)  # dir, not a db

    def test_update_master_resume_writes_audit_row(self, monkeypatch, tmp_path):
        import sqlite3
        from tools import resume as resume_mod
        import lib.provenance as prov

        master = tmp_path / "master.txt"
        master.write_text("I maintain 931 passing tests today.", encoding="utf-8")
        monkeypatch.setattr(
            resume_mod.config, "get_active_master_resume_path", lambda: master,
            raising=False,
        )
        db = tmp_path / "audit.db"
        real = prov.record_master_edit
        monkeypatch.setattr(
            prov, "record_master_edit",
            lambda old, new, db_path=None: real(old, new, db_path=db),
        )
        out = resume_mod.update_master_resume("931 passing tests", "1484 passing tests")
        assert out.startswith("✓")
        assert "1484 passing tests" in master.read_text(encoding="utf-8")
        n = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM master_resume_edits"
        ).fetchone()[0]
        assert n == 1

    def test_edit_gauge_rendered(self, tmp_path):
        from lib.provenance import record_master_edit, record_run, render_durable_metrics

        db = tmp_path / "m.db"
        record_run(kind="resume", company="X", role="Y", job_description="j",
                   chunk_texts=[], claims=[], violations=[], verdict="passed",
                   revisions=0, db_path=db)
        record_master_edit("a", "b", db_path=db)
        out = render_durable_metrics(db_path=db)
        assert "master_resume_edits_total 1" in out
