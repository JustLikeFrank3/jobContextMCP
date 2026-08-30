"""The trust report: gates and control-plane provenance surfaced through chat.

An agent generating a document over WebMCP should be able to SHOW its user
that the safeguards ran: the generation response names its correction passes
and control-plane work item, and documents(action="provenance") returns the
durable truth-gate record for the run.
"""
from __future__ import annotations

from lib.provenance import record_run
from tools.generate import get_provenance_report


def _record(verdict: str = "passed", violations=None, company="Acme", role="Staff Eng"):
    record_run(
        kind="resume",
        company=company,
        role=role,
        job_description="jd",
        chunk_texts=[],
        claims=["9 years", "$1.8M/year", "40k claims/month"],
        violations=violations or [],
        verdict=verdict,
        revisions=1 if violations else 0,
    )


class TestGetProvenanceReport:
    def test_pass_verdict_reads_as_attestation(self, isolated_server):
        _record()
        out = get_provenance_report()
        assert "TRUST REPORT" in out
        assert "✓ PASS" in out
        assert "3 claims checked" in out
        assert "0 unsourced" in out
        assert "generation_provenance #" in out
        assert "Entailment critic:" in out

    def test_failed_verdict_lists_violations(self, isolated_server):
        _record(verdict="failed", violations=["47%"])
        out = get_provenance_report()
        assert "⚠ FAILED" in out
        assert "1 unsourced" in out
        assert "- 47%" in out
        assert "Correction passes: 1" in out

    def test_company_filter_pins_the_record(self, isolated_server):
        _record(company="Acme", role="Staff Eng")
        _record(company="Globex", role="Principal", verdict="failed", violations=["12x"])
        out = get_provenance_report(company="Acme")
        assert "Acme" in out
        assert "✓ PASS" in out

    def test_no_record_says_so_plainly(self, isolated_server):
        out = get_provenance_report(company="NeverGenerated")
        assert "No gate record found" in out


class TestFacadeExposesProvenance:
    def test_documents_provenance_action_registered_read_only(self):
        import tools.consolidated as c

        fn, desc = c.DOMAINS["documents"]["provenance"]
        assert fn is get_provenance_report
        assert "read-only" in desc.lower()

    def test_dispatch_reaches_the_report(self, isolated_server):
        import tools.consolidated as c

        _record()
        out = c._run("documents", "provenance", {"company": "Acme"})
        assert "TRUST REPORT" in out


class TestControlPlaneLineOnSuccess:
    def test_tracked_success_appends_work_item_line(self, isolated_server):
        from tools import generate_work

        def _dummy(company: str) -> str:
            return f"✓ generated for {company}"

        wrapped = generate_work.tracked(
            "test_trust_report_kind",
            system_prompt=lambda: "sys",
            origin="test",
        )(_dummy)
        out = wrapped(company="Acme")
        assert out.startswith("✓ generated for Acme")
        assert "control plane: work item #" in out
        assert "durable audit row" in out
