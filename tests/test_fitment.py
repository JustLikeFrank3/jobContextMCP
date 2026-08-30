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
from tools import fitment


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

    def test_unknown_persona_rejected_with_valid_set(self, isolated_server):
        # A silent fallback ships a persona the caller never asked for; the
        # rejection carries the valid values so an agent can self-correct.
        out = srv.assess_job_fitment("Stripe", "Staff Engineer", JD, persona="nonexistent")
        assert out.startswith("✗")
        assert "Available:" in out
        assert "default" in out
        assert "FITMENT ASSESSMENT" not in out


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

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
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

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
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

    @pytest.mark.live_llm
    def test_unknown_persona_rejected_before_llm_and_save(self, isolated_server, monkeypatch):
        from lib import config

        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")

        fake_client = MagicMock()

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
            out = srv.run_job_assessment(
                "ACME/AI",
                "AI Platform Engineer",
                "Build MCP and RAG workflows.",
                persona="missing_persona",
            )

        saved = fitment.config.get_active_job_assessments_dir() / "run_job_assessment" / "ACME-AI AI Platform Engineer - Fitment Assessment.md"
        assert out.startswith("✗")
        assert "Available:" in out
        fake_client.chat.completions.create.assert_not_called()
        assert not saved.exists()

    @pytest.mark.live_llm
    def test_ai_role_includes_ai_evidence_in_user_message(self, isolated_server, monkeypatch):
        from lib import config

        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="FITMENT SCORE: 8/10"))]
        fake_response.usage = None
        fake_client.chat.completions.create.return_value = fake_response

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")), patch(
            "tools.fitment._load_master_context",
            return_value="Built an MCP server for agent workflows.\nPlain Java service line.",
        ):
            srv.run_job_assessment(
                "Stripe",
                "AI Platform Engineer",
                "Build RAG agents and MCP tooling.",
                auto_save=False,
            )

        user_msg = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "AI PLATFORM EVIDENCE EXTRACTED FROM MASTER RESUME" in user_msg
        assert "- Built an MCP server for agent workflows." in user_msg


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


class TestFitmentCoverageExtras:
    def test_extract_ai_platform_evidence_returns_empty_without_matches(self):
        assert fitment._extract_ai_platform_evidence("Plain Java backend. Spring services only.") == ""

    def test_get_customization_strategy_reports_unknown_role_type(self):
        out = fitment.get_customization_strategy("mystery_role")

        assert "Unknown role type: 'mystery_role'" in out
        assert "backend" in out
        assert "cloud" in out

    def test_save_job_assessment_sanitizes_source_and_extension(self, isolated_server):
        out = fitment.save_job_assessment(
            "ACME/AI",
            "Line one  \nLine two  ",
            filename="summary",
            source="Referral\\Team",
        )

        saved = fitment.config.get_active_job_assessments_dir() / "Referral-Team" / "summary.md"
        assert "Referral-Team/summary.md" in out
        assert saved.read_text(encoding="utf-8") == "Line one\nLine two"

    def test_save_job_assessment_sanitizes_windows_illegal_chars(self, isolated_server):
        fitment.save_job_assessment(
            "Coke",
            "content",
            filename="Coke Senior Software Engineer | Atlanta, GA US | Coca-Cola - Fitment Assessment.md",
            source="run_job_assessment",
        )

        saved = (
            fitment.config.get_active_job_assessments_dir()
            / "run_job_assessment"
            / "Coke Senior Software Engineer - Atlanta, GA US - Coca-Cola - Fitment Assessment.md"
        )
        assert saved.is_file()

    def test_save_job_assessment_keeps_txt_extension(self, isolated_server):
        """A .txt filename must stay .txt — forcing .md onto it produced
        '….txt.md' and blocked plain text as a preview fallback."""
        fitment.save_job_assessment("Acme", "content", filename="assessment.txt")

        folder = fitment.config.get_active_job_assessments_dir()
        assert (folder / "assessment.txt").is_file()
        assert not (folder / "assessment.txt.md").exists()

    def test_save_job_assessment_default_filename_is_sanitized(self, isolated_server):
        fitment.save_job_assessment('Acme <Labs>: "AI"', "content")

        folder = fitment.config.get_active_job_assessments_dir()
        names = [p.name for p in folder.glob("*.md")]
        assert names, "assessment file was not saved"
        for name in names:
            assert not set('<>:"/\\|?*') & set(name), name

    @pytest.mark.live_llm
    def test_run_job_assessment_slug_is_representable_on_every_platform(
        self, isolated_server, monkeypatch
    ):
        """run_job_assessment builds its own filename from company + role, so
        a hostile role must be sanitized before it hits disk. The cloud runs
        Linux, where these names are legal — they get written happily and then
        skip on every desktop sync forever."""
        from lib import config

        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="FITMENT SCORE: 7/10"))]
        fake_response.usage = None
        fake_client.chat.completions.create.return_value = fake_response

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
            out = fitment.run_job_assessment(
                "Coke",
                r'Senior Engineer: <html> | Home, RI ? * \ /',
                "Build things.",
            )

        assert "Saved job assessment" in out
        folder = fitment.config.get_active_job_assessments_dir() / "run_job_assessment"
        names = [p.name for p in folder.glob("*.md")]
        assert names, "assessment file was not saved"
        for name in names:
            assert not set('<>:"/\\|?*') & set(name), name
        saved = folder / names[0]
        assert saved.read_text(encoding="utf-8") == "FITMENT SCORE: 7/10"

    def test_run_job_assessment_handles_llm_client_boot_failure(self, isolated_server):
        with patch("lib.config.get_llm_client", side_effect=RuntimeError("boom")):
            out = fitment.run_job_assessment("Stripe", "Staff Engineer", JD)

        assert out == "✗ Failed to load LLM client. Check config.json llm_provider settings."

    def test_run_job_assessment_handles_openai_errors(self, isolated_server):
        fake_client = object()

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")), patch(
            "tools.fitment.create_chat_completion",
            side_effect=RuntimeError("rate limited"),
        ):
            out = fitment.run_job_assessment("Stripe", "Staff Engineer", JD, auto_save=False)

        assert out == "✗ OpenAI API error: rate limited"


class TestWorkspaceSignalInjection:
    """The assessment path must consult the workspace server-side — a foreign
    MCP client generated interviewer-blind output because nothing pulled the
    people domain for it (2026-08-28 report, BUG-1)."""

    def _seed_workspace(self):
        srv.log_person(
            "Umesh Misra",
            "hiring manager",
            "Mercedes-Benz USA",
            "Leads the AI productization group.",
            notes="Interview confirmed for 2099-08-31 2:00 PM ET.",
        )
        srv.update_application("Mercedes-Benz USA", "AI Productization Engineer", "interviewing")

    def test_assess_includes_workspace_signal(self, isolated_server):
        self._seed_workspace()
        out = srv.assess_job_fitment("Mercedes-Benz USA", "AI Productization Engineer", JD)
        assert "WORKSPACE SIGNAL" in out
        assert "Umesh Misra" in out
        assert "hiring manager" in out

    def test_assess_without_workspace_data_omits_signal_block(self, isolated_server):
        out = srv.assess_job_fitment("Stripe", "Staff Engineer", JD)
        assert "WORKSPACE SIGNAL" not in out

    def test_signal_includes_future_interviews_and_events(self, isolated_server):
        self._seed_workspace()
        srv.log_application_event(
            "Mercedes-Benz USA", "AI Productization Engineer", "recruiter_contact",
            notes="Recruiter confirmed HM round.",
        )
        srv.log_interview(
            company="Mercedes-Benz USA",
            role="AI Productization Engineer",
            interview_date="2099-08-31 14:00",
            interview_type="hiring_manager",
            interviewer="Umesh Misra",
            interviewer_role="Hiring Manager",
        )
        from tools.interviews import get_company_signal_context
        block = get_company_signal_context("Mercedes-Benz USA", "AI Productization Engineer")
        assert "SCHEDULED INTERVIEWS" in block
        assert "2099-08-31" in block
        assert "recruiter_contact" in block

    def test_signal_matches_company_name_variants(self, isolated_server):
        # Record says 'Mercedes-Benz', query says 'Mercedes-Benz USA' — records
        # and queries disagree on suffixes constantly.
        srv.log_person("Umesh Misra", "hiring manager", "Mercedes-Benz", "Leads the group.")
        from tools.interviews import get_company_signal_context
        assert "Umesh Misra" in get_company_signal_context("Mercedes-Benz USA")

    @pytest.mark.live_llm
    def test_full_assessment_prompt_carries_interviewer(self, isolated_server, monkeypatch):
        from lib import config

        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")
        self._seed_workspace()

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="FITMENT SCORE: 9/10"))]
        fake_response.usage = None
        fake_client.chat.completions.create.return_value = fake_response

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
            srv.run_job_assessment(
                "Mercedes-Benz USA", "AI Productization Engineer", JD, auto_save=False,
            )

        user_msg = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "WORKSPACE SIGNAL" in user_msg
        assert "Umesh Misra" in user_msg


class TestAssessmentReuse:
    """One role produced four near-identical metered assessments in the first
    live bridge run — regeneration must be a deliberate act (BUG-3)."""

    def test_existing_assessment_returned_without_regenerating(self, isolated_server):
        srv.save_job_assessment(
            "Mercedes-Benz USA",
            "FITMENT SCORE: 9/10 (prior run)",
            filename="Mercedes-Benz USA AI Productization Engineer - Fitment Assessment.md",
        )
        out = srv.run_job_assessment("Mercedes-Benz USA", "AI Productization Engineer", JD)
        assert "Existing assessment" in out
        assert "FITMENT SCORE: 9/10 (prior run)" in out
        assert "force=True" in out

    def test_dedupe_is_punctuation_insensitive(self, isolated_server):
        srv.save_job_assessment(
            "ACME/AI",
            "prior content",
            filename="ACME-AI Staff Engineer - Fitment Assessment.md",
        )
        out = srv.run_job_assessment("ACME/AI", "Staff Engineer", JD)
        assert "Existing assessment" in out

    def test_different_role_does_not_match(self, isolated_server):
        srv.save_job_assessment(
            "ACME",
            "prior content",
            filename="ACME Staff Engineer - Fitment Assessment.md",
        )
        # Offline stub → falls through to the context pack, proving no reuse hit.
        out = srv.run_job_assessment("ACME", "Engineering Manager", JD)
        assert "Existing assessment" not in out

    @pytest.mark.live_llm
    def test_force_regenerates_over_existing(self, isolated_server, monkeypatch):
        from lib import config

        monkeypatch.setitem(config._cfg, "openai_api_key", "sk-real-test-key")
        srv.save_job_assessment(
            "ACME",
            "stale content",
            filename="ACME Staff Engineer - Fitment Assessment.md",
        )

        fake_client = MagicMock()
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content="fresh content"))]
        fake_response.usage = None
        fake_client.chat.completions.create.return_value = fake_response

        with patch("lib.config.get_llm_client", return_value=(fake_client, "gpt-4o")):
            out = srv.run_job_assessment("ACME", "Staff Engineer", JD, auto_save=False, force=True)

        fake_client.chat.completions.create.assert_called_once()
        assert "fresh content" in out
