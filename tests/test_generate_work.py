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
from tools import generate, generate_work

# Captured at import, before conftest's autouse fixture replaces both generators
# with stubs for every non-live_llm test — same pattern as
# test_generate_coverage._REAL_GENERATE_RESUME. Asserting on the module
# attribute instead would inspect the lambda, not the wrapper.
_REAL_RESUME = generate.generate_resume
_REAL_COVER = generate.generate_cover_letter


class TestPromptVersion:
    def test_stable_for_identical_text(self):
        assert generate_work.prompt_version("abc") == generate_work.prompt_version("abc")

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
        assert wrapped("Acme", "Engineer") == "doc for Engineer @ Acme"

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
