"""Submit-and-poll generation (tools/generate_async.py).

In-browser agents cap a WebMCP tool call at ~25s; generation takes 60–120s.
These pin the async surface: submit enqueues the same control-plane kind the
synchronous path records, and generation_status returns the same response
text — attestation and audit line included — once the row succeeds.
"""
from __future__ import annotations

from lib import work
from tools import generate_async, generate_work


class TestSubmit:
    def test_submit_resume_enqueues_the_resume_kind(self, isolated_server):
        out = generate_async.submit_resume("Acme", "Staff Eng", "jd text")
        assert "queued as work item #" in out
        assert "generation_status" in out

        rows = [r for r in work.list_items() if r["kind"] == generate_work.KIND_RESUME]
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "queued"
        assert row["origin"] == "chat_async"
        assert row["inputs"]["company"] == "Acme"
        assert row["inputs"]["role"] == "Staff Eng"
        assert row["inputs"]["job_description"] == "jd text"
        # Defaults recorded explicitly so the row is replayable as fn(**inputs).
        assert row["inputs"]["style"] == "navy"

    def test_submit_cover_letter_enqueues_the_cover_kind(self, isolated_server):
        out = generate_async.submit_cover_letter("Acme", "Staff Eng", "jd text")
        assert "queued as work item #" in out
        row = [r for r in work.list_items()
               if r["kind"] == generate_work.KIND_COVER_LETTER][0]
        assert row["status"] == "queued"
        assert row["inputs"]["export_pipeline"] == "html"

    def test_submit_resume_rejects_unknown_style_without_enqueueing(self, isolated_server):
        # A bad style must fail at submit time with the valid options — not
        # minutes later inside the queued 60–120s run.
        out = generate_async.submit_resume("Acme", "Staff Eng", "jd", style="ai-platform")
        assert out.startswith("Error: unknown style 'ai-platform'")
        assert "navy" in out
        assert not [r for r in work.list_items() if r["kind"] == generate_work.KIND_RESUME]

    def test_submit_cover_letter_rejects_unknown_template_without_enqueueing(self, isolated_server):
        out = generate_async.submit_cover_letter("Acme", "Staff Eng", "jd", cl_template="fancy")
        assert out.startswith("Error: unknown CL template 'fancy'")
        assert not [r for r in work.list_items() if r["kind"] == generate_work.KIND_COVER_LETTER]

    def test_submitted_inputs_execute_against_the_real_signature(self, isolated_server):
        """The dispatcher runs fn(**inputs) — a submit that records a key the
        generator doesn't accept fails at execution time, not enqueue time.
        Bind them against the real signatures so drift breaks here instead."""
        import inspect
        from tests.test_generate_work import _REAL_RESUME, _REAL_COVER

        generate_async.submit_resume("Acme", "Staff Eng", "jd")
        generate_async.submit_cover_letter("Acme", "Staff Eng", "jd")
        for kind, fn in ((generate_work.KIND_RESUME, _REAL_RESUME),
                         (generate_work.KIND_COVER_LETTER, _REAL_COVER)):
            row = [r for r in work.list_items() if r["kind"] == kind][0]
            inspect.signature(fn).bind(**row["inputs"])  # raises on drift


class TestGenerationStatus:
    def test_unknown_id_says_so(self, isolated_server):
        assert "No work item #424242" in generate_async.generation_status(424242)

    def test_queued_row_reports_state_and_poll_hint(self, isolated_server):
        generate_async.submit_resume("Acme", "Staff Eng", "jd")
        row = [r for r in work.list_items()
               if r["kind"] == generate_work.KIND_RESUME][0]
        out = generate_async.generation_status(row["id"])
        assert "queued" in out
        assert "Poll again" in out

    def test_succeeded_row_returns_document_with_audit_line(self, isolated_server):
        work.register_kind("generate.test_async", lambda inputs: {"result": "DOC TEXT"})
        row = work.run_now("generate.test_async", {})
        out = generate_async.generation_status(row["id"])
        assert out.startswith("DOC TEXT")
        assert f"control plane: work item #{row['id']}" in out
        assert "durable audit row" in out

    def test_handled_failure_result_passes_through_unstamped(self, isolated_server):
        """Same rule as the synchronous wrapper: a ✗-prefixed result is a
        reported failure — stamping it would dress an error up as an attested
        success."""
        work.register_kind("generate.test_soft_fail",
                           lambda inputs: {"result": "✗ OpenAI API error: boom"})
        row = work.run_now("generate.test_soft_fail", {})
        out = generate_async.generation_status(row["id"])
        assert out == "✗ OpenAI API error: boom"

    def test_failed_row_reports_the_error(self, isolated_server):
        work.register_kind(
            "generate.test_boom",
            lambda inputs: (_ for _ in ()).throw(RuntimeError("model exploded")))
        row = work.run_now("generate.test_boom", {})
        out = generate_async.generation_status(row["id"])
        assert out.startswith("✗ Generation failed")
        assert "model exploded" in out

    def test_non_generation_kind_is_refused(self, isolated_server):
        work.register_kind("t.other", lambda inputs: {"result": "secretish"})
        row = work.run_now("t.other", {})
        out = generate_async.generation_status(row["id"])
        assert "not a document generation" in out
        assert "secretish" not in out

    def test_string_work_id_is_coerced(self, isolated_server):
        work.register_kind("generate.test_str_id", lambda inputs: {"result": "ok"})
        row = work.run_now("generate.test_str_id", {})
        assert generate_async.generation_status(str(row["id"])).startswith("ok")


class TestFacadeWiring:
    def test_documents_actions_registered(self):
        import tools.consolidated as c

        assert c.DOMAINS["documents"]["submit_resume"][0] is generate_async.submit_resume
        assert c.DOMAINS["documents"]["submit_cover_letter"][0] is generate_async.submit_cover_letter
        assert c.DOMAINS["documents"]["generation_status"][0] is generate_async.generation_status
        # The sync generators must steer short-timeout clients to the async path.
        for action in ("generate_resume", "generate_cover_letter"):
            assert "submit" in c.DOMAINS["documents"][action][1]

    def test_dispatch_submit_then_poll_round_trip(self, isolated_server):
        import tools.consolidated as c

        out = c._run("documents", "submit_resume",
                     {"company": "Acme", "role": "SWE", "job_description": "jd"})
        assert "queued as work item #" in out
        row = [r for r in work.list_items()
               if r["kind"] == generate_work.KIND_RESUME][0]
        polled = c._run("documents", "generation_status", {"work_id": row["id"]})
        assert "queued" in polled
