"""Control-plane P1: document generation as durable work rows.

The generators are wrapped rather than called through at each site, so these
pin the two properties that matter: the wrapper is invisible to callers (same
return value, signature, docstring — the MCP facade reads all three), and it
can never be the reason a document fails to generate.
"""
from __future__ import annotations

import inspect

import pytest

from lib import work
from tools import fitment as _fitment
from tools import generate, generate_work

# Captured at import, before conftest's autouse fixture replaces both generators
# with stubs for every non-live_llm test — same pattern as
# test_generate_coverage._REAL_GENERATE_RESUME. Asserting on the module
# attribute instead would inspect the lambda, not the wrapper.
_REAL_RESUME = generate.generate_resume
_REAL_COVER = generate.generate_cover_letter
_REAL_ASSESSMENT = _fitment.run_job_assessment


class TestPromptVersion:
    def test_stable_for_identical_text(self):
        assert generate_work.prompt_version("abc") == "ba7816bf8f01"

    def test_changes_when_the_prompt_changes(self):
        assert generate_work.prompt_version("abc") != generate_work.prompt_version("abd")

    def test_empty_and_none_safe(self):
        assert generate_work.prompt_version("")
        assert generate_work.prompt_version(None)


class TestWrapperIsInvisible:
    """The facade reads name, signature, and docstring off these functions —
    a wrapper that obscured any of them would break the tool schema."""

    def test_signature_preserved(self):
        params = list(inspect.signature(_REAL_RESUME).parameters)
        assert params[:3] == ["company", "role", "job_description"]
        assert list(inspect.signature(_REAL_COVER).parameters)[:3] == [
            "company", "role", "job_description"]

    def test_docstring_preserved(self):
        assert "Generate a tailored resume" in _REAL_RESUME.__doc__
        assert "Generate a tailored cover letter" in _REAL_COVER.__doc__

    def test_kinds_registered(self):
        assert _REAL_RESUME.work_kind == generate_work.KIND_RESUME
        assert _REAL_COVER.work_kind == generate_work.KIND_COVER_LETTER
        assert generate_work.KIND_RESUME in work._KINDS
        assert generate_work.KIND_COVER_LETTER in work._KINDS


class TestTrackedExecution:
    def _decorate(self, fn, kind="test.kind"):
        return generate_work.tracked(kind, system_prompt=lambda: "SYS")(fn)

    def test_returns_the_functions_value_and_writes_a_row(self, isolated_server, monkeypatch):
        monkeypatch.setattr(generate, "_model", lambda: "gpt-test")
        wrapped = self._decorate(lambda company, role: f"doc for {role} @ {company}")
        out = wrapped("Acme", "Engineer")
        # The function's value ships first; the wrapper appends the audit line
        # so chat clients can show the run went THROUGH the control plane.
        assert out.startswith("doc for Engineer @ Acme")
        assert "control plane: work item #" in out

        rows = [r for r in work.list_items() if r["kind"] == "test.kind"]
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "succeeded"
        assert row["inputs"] == {"company": "Acme", "role": "Engineer"}
        assert row["artifacts"]["model"] == "gpt-test"
        assert row["artifacts"]["prompt_version"] == generate_work.prompt_version("SYS")

    def test_positional_and_keyword_calls_record_identically(self, isolated_server, monkeypatch):
        monkeypatch.setattr(generate, "_model", lambda: "m")
        wrapped = self._decorate(lambda company, role: "x")
        wrapped("Acme", "Engineer")
        wrapped(company="Acme", role="Engineer")
        rows = [r for r in work.list_items() if r["kind"] == "test.kind"]
        assert rows[0]["inputs"] == rows[1]["inputs"] == {"company": "Acme", "role": "Engineer"}

    def test_raising_generator_becomes_a_failed_row_not_an_exception(
        self, isolated_server, monkeypatch
    ):
        """These generators report failure in their return value and callers
        render it — raising would turn a handled failure into an unhandled one."""
        monkeypatch.setattr(generate, "_model", lambda: "m")

        def _boom(company, role):
            raise RuntimeError("model exploded")

        out = self._decorate(_boom)("Acme", "Engineer")
        assert out.startswith("✗ Generation failed")
        assert "model exploded" in out
        row = [r for r in work.list_items() if r["kind"] == "test.kind"][0]
        assert row["status"] == "failed"
        assert "model exploded" in row["error"]

    def test_control_plane_failure_still_produces_the_document(
        self, isolated_server, monkeypatch
    ):
        """A row we couldn't write is a lost audit record, not a lost document."""
        monkeypatch.setattr(
            work, "run_now",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db locked")),
        )
        wrapped = self._decorate(lambda company, role: "document survived")
        assert wrapped("Acme", "Engineer") == "document survived"


class TestRunNow:
    def test_row_is_durable_and_carries_artifacts(self, isolated_server):
        work.register_kind("t.ok", lambda inputs: {"echo": inputs["v"]})
        row = work.run_now("t.ok", {"v": 7}, origin="unit")
        assert row["status"] == "succeeded"
        assert row["artifacts"] == {"echo": 7}
        assert row["origin"] == "unit"
        assert work.get_item(row["id"])["status"] == "succeeded"

    def test_executor_failure_is_recorded_not_raised(self, isolated_server):
        work.register_kind("t.boom", lambda inputs: (_ for _ in ()).throw(ValueError("no")))
        row = work.run_now("t.boom", {})
        assert row["status"] == "failed"
        assert "no" in row["error"]

    def test_unknown_kind_raises(self, isolated_server):
        with pytest.raises(ValueError):
            work.run_now("t.nonexistent", {})


class TestAssessmentKind:
    """run_job_assessment calls a model and produces a document, so it belongs
    on the control plane. The other two names in the P1 roadmap entry do not —
    see TestContextPackersAreNotTracked."""

    def test_registered_with_its_own_kind(self):
        assert _REAL_ASSESSMENT.work_kind == generate_work.KIND_ASSESSMENT
        assert generate_work.KIND_ASSESSMENT in work._KINDS
        assert "LLM-powered fitment assessment" in _REAL_ASSESSMENT.__doc__

    def test_stamps_the_assessment_model_not_the_generator_model(
        self, isolated_server, monkeypatch
    ):
        """Assessment resolves its own model via task='assessment'. Stamping it
        with generate._model() would attribute the output to whatever model is
        configured for resume generation."""
        monkeypatch.setattr(generate, "_model", lambda: "resume-model")
        wrapped = generate_work.tracked(
            "test.assess",
            system_prompt=lambda: "SYS",
            model=lambda: "assessment-model",
        )(lambda company: "assessed")

        assert wrapped("Acme").startswith("assessed")
        row = [r for r in work.list_items() if r["kind"] == "test.assess"][0]
        assert row["artifacts"]["model"] == "assessment-model"

    def test_unstampable_model_still_ships_the_document(self, isolated_server):
        """A model we can't resolve is a weaker audit record, not a reason to
        fail a document that generated fine."""
        wrapped = generate_work.tracked(
            "test.nomodel",
            system_prompt=lambda: "SYS",
            model=lambda: (_ for _ in ()).throw(RuntimeError("no provider")),
        )(lambda company: "document")

        assert wrapped("Acme").startswith("document")
        row = [r for r in work.list_items() if r["kind"] == "test.nomodel"][0]
        assert row["status"] == "succeeded"
        assert row["artifacts"]["model"] == ""


class TestContextPackersAreNotTracked:
    """The P1 entry named 'assessment / interview-prep' generation, but two of
    those are context packers: they read the master resume and return a prompt
    for the orchestrating agent. No model call, no document, nothing to
    attribute — a work row would be noise in the table you query to attribute a
    regression. Pinned so a later change doesn't wrap them by reflex."""

    def test_assess_job_fitment_is_untracked(self):
        assert not hasattr(_fitment.assess_job_fitment, "work_kind")

    def test_interview_prep_context_is_untracked(self):
        from tools import interview

        assert not hasattr(interview.generate_interview_prep_context, "work_kind")
