"""
Tests for persona-aware fitment tooling.

Covers:
  assess_job_fitment(persona=...)  ... persona block injected
  evaluate_queued_job(persona=...) ... persona threaded through
  run_job_assessment(persona=...)  ... persona prepended to system prompt
  JobAnalysisService.evaluate(persona=...) ... orchestrator pass-through
"""

from unittest.mock import MagicMock, patch

import pytest

import server as srv
from services import JobAnalysisService
from services.persona_service import PersonaService


JD = "We need a senior engineer with React, Node, and AWS."


class TestAssessJobFitmentPersona:
    def test_no_persona_omits_lens_section(self, isolated_server):
        out = srv.assess_job_fitment("Stripe", "Staff Engineer", JD)
        assert "PERSONA LENS" not in out
        assert "JOB DESCRIPTION" in out

    def test_persona_injects_lens_block(self, isolated_server):
        out = srv.assess_job_fitment("Stripe", "Staff Engineer", JD, persona="faang_technical")
        assert "PERSONA LENS" in out
        expected = PersonaService.get("faang_technical").to_prompt_block()
        assert expected in out

    def test_unknown_persona_emits_warning_not_crash(self, isolated_server):
        out = srv.assess_job_fitment("Stripe", "Staff Engineer", JD, persona="nonexistent")
        assert "PERSONA LENS" in out
        assert "warning" in out.lower()


class TestEvaluateQueuedJobPersona:
    def test_persona_passed_to_assess(self, isolated_server):
        # The autouse _mock_llm fixture forces the offline fallback, so
        # evaluate_queued_job routes through assess_job_fitment and emits the
        # PERSONA LENS pack deterministically (no live OpenAI call).
        srv.queue_job("Stripe", "Staff Engineer", JD)
        out = srv.evaluate_queued_job("Stripe", "Staff Engineer", persona="executive_polish")
        assert "PERSONA LENS" in out
        expected = PersonaService.get("executive_polish").to_prompt_block()
        assert expected in out

    def test_default_no_persona(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", JD)
        out = srv.evaluate_queued_job("Stripe", "Staff Engineer")
        assert "PERSONA LENS" not in out


class TestRunJobAssessmentPersona:
    @pytest.mark.live_llm
    def test_persona_prepended_to_system_prompt(self, isolated_server, monkeypatch):
        """When OpenAI is configured, persona block must be prepended to the system prompt."""
        from lib import config
        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="FITMENT SCORE: 9/10"))]
        fake_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        fake_client.chat.completions.create.return_value = fake_response

        with patch("openai.OpenAI", return_value=fake_client):
            out = srv.run_job_assessment(
                "Stripe", "Staff Engineer", JD,
                persona="faang_technical", auto_save=False,
            )

        call_kwargs = fake_client.chat.completions.create.call_args.kwargs
        system_msg = call_kwargs["messages"][0]["content"]
        expected_block = PersonaService.get("faang_technical").to_prompt_block()
        assert expected_block in system_msg
        assert "FITMENT SCORE" in system_msg  # original system text still present
        assert "persona: faang_technical" in out

    @pytest.mark.live_llm
    def test_no_persona_uses_bare_system_prompt(self, isolated_server, monkeypatch):
        from lib import config
        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="FITMENT SCORE: 7/10"))]
        fake_response.usage = MagicMock(prompt_tokens=80, completion_tokens=40)
        fake_client.chat.completions.create.return_value = fake_response

        with patch("openai.OpenAI", return_value=fake_client):
            srv.run_job_assessment("Stripe", "Staff Engineer", JD, auto_save=False)

        system_msg = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        for name in ("faang_technical", "executive_polish", "startup_founder"):
            block = PersonaService.get(name).to_prompt_block()
            assert block not in system_msg

    def test_no_openai_key_falls_back_to_context_pack_with_persona(self, isolated_server):
        # The autouse _mock_llm fixture forces get_llm_client -> (None, None),
        # so run_job_assessment falls back to the context pack with the persona.
        out = srv.run_job_assessment("Stripe", "Staff Engineer", JD, persona="executive_polish")
        assert PersonaService.get("executive_polish").to_prompt_block() in out


class TestJobAnalysisServicePersona:
    def test_evaluate_threads_persona_to_pack(self, isolated_server):
        # Offline fallback (via autouse fixture): the orchestrator accepts the
        # legacy context-pack format, so PERSONA LENS threads through.
        result = JobAnalysisService.evaluate(
            company="Stripe",
            role="Staff Engineer",
            job_description=JD,
            source="test",
            persona="faang_technical",
        )
        assert result.evaluated is True
        assert "PERSONA LENS" in result.fitment_context
        assert PersonaService.get("faang_technical").to_prompt_block() in result.fitment_context

    def test_evaluate_default_no_persona(self, isolated_server):
        result = JobAnalysisService.evaluate(
            company="Stripe",
            role="Staff Engineer",
            job_description=JD,
        )
        assert result.evaluated is True
        assert "PERSONA LENS" not in result.fitment_context

    def test_assess_threads_persona(self, isolated_server):
        out = JobAnalysisService.assess(
            company="Stripe",
            role="Staff Engineer",
            job_description=JD,
            persona="startup_founder",
        )
        assert "PERSONA LENS" in out
        assert PersonaService.get("startup_founder").to_prompt_block() in out
