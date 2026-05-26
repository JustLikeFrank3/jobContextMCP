"""Tests for PersonaService and persona HTTP endpoints."""

import json
import pytest

from services import PersonaService, PersonaConfig, UnknownPersonaError, ResumeService


class TestPersonaService:
    def test_list_includes_bundled_personas(self):
        names = PersonaService.list_personas()
        assert "default" in names
        assert "executive_polish" in names
        assert "faang_technical" in names
        assert "startup_founder" in names

    def test_get_default_when_name_none(self):
        p = PersonaService.get(None)
        assert isinstance(p, PersonaConfig)
        assert p.name == "default"
        assert "preferred_punctuation" in p.tone_modifiers
        assert p.tone_modifiers["preferred_punctuation"]["no_em_dash"] is True

    def test_get_executive_polish(self):
        p = PersonaService.get("executive_polish")
        assert p.name == "executive_polish"
        assert p.weighting["leadership_keywords_boost"] == 1.5

    def test_get_unknown_raises(self):
        with pytest.raises(UnknownPersonaError, match="Unknown persona"):
            PersonaService.get("nonexistent")

    def test_to_prompt_block_includes_sections(self):
        block = PersonaService.get("default").to_prompt_block()
        assert "# Persona: default" in block
        assert "## Tone modifiers" in block
        assert "## Weighting" in block
        assert "## Formatting rules" in block

    def test_user_override_dir_takes_precedence(self, isolated_server, tmp_path):
        """A persona JSON dropped into <DATA_FOLDER>/personas/ should shadow the bundled set."""
        from lib import config as cfg
        user_dir = cfg.DATA_FOLDER / "personas"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "custom.json").write_text(json.dumps({
            "name": "custom",
            "description": "user-defined",
            "tone_modifiers": {"register": "custom-register"},
            "weighting": {},
            "formatting_rules": {},
        }))
        names = PersonaService.list_personas()
        # User dir wins: only "custom" should be listed, not the bundled defaults.
        assert names == ["custom"]
        assert PersonaService.get("custom").tone_modifiers["register"] == "custom-register"


class TestResumeServicePersonaWiring:
    def test_default_persona_used_when_omitted(self, isolated_server):
        events = []
        ResumeService.generate(
            company="X", role="Y", job_description="JD",
            on_progress=events.append,
        )
        starting = events[0]
        assert starting.stage == "starting"
        assert starting.payload["persona"] == "default"

    def test_named_persona_recorded_in_event(self, isolated_server):
        events = []
        ResumeService.generate(
            company="X", role="Y", job_description="JD",
            persona="faang_technical",
            on_progress=events.append,
        )
        assert events[0].payload["persona"] == "faang_technical"

    def test_unknown_persona_raises_before_generation(self, isolated_server):
        with pytest.raises(UnknownPersonaError):
            ResumeService.generate(
                company="X", role="Y", job_description="JD",
                persona="ghost",
            )


class TestPersonaHttpEndpoints:
    def test_list_personas(self, http_client_noauth):
        r = http_client_noauth.get("/personas")
        assert r.status_code == 200
        assert "default" in r.json()["personas"]

    def test_get_persona(self, http_client_noauth):
        r = http_client_noauth.get("/personas/executive_polish")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "executive_polish"
        assert body["weighting"]["leadership_keywords_boost"] == 1.5

    def test_get_unknown_persona_404(self, http_client_noauth):
        r = http_client_noauth.get("/personas/ghost")
        assert r.status_code == 404

    def test_resume_generate_accepts_persona(self, http_client_noauth):
        r = http_client_noauth.post("/resumes/generate", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "JD",
            "kind": "resume",
            "persona": "faang_technical",
        })
        assert r.status_code == 200
        # Persona is applied as prompt-bias inside the generate tool — visible
        # in the keyless context-package content which echoes the augmented JD.
        body = r.json()
        assert body["company"] == "Stripe"
