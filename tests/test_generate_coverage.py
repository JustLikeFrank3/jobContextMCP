import types

import pytest

from tools import generate

_REAL_GENERATE_RESUME = generate.generate_resume
_REAL_GENERATE_COVER_LETTER = generate.generate_cover_letter


@pytest.fixture(autouse=True)
def _restore_generate_entrypoints(monkeypatch):
    monkeypatch.setattr(generate, "generate_resume", _REAL_GENERATE_RESUME)
    monkeypatch.setattr(generate, "generate_cover_letter", _REAL_GENERATE_COVER_LETTER)


class _FakeResponse:
    def __init__(self, content: str, prompt_tokens: int = 100, completion_tokens: int = 50):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        self.usage = types.SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def test_load_cover_letter_master_context_filters_and_falls_back(isolated_server, monkeypatch):
    import lib.config as cfg

    master = cfg.get_active_master_resume_path()
    master.write_text(
        "CORE TECHNICAL SKILLS\n"
        "Languages & Frameworks: Python, FastAPI\n"
        "Built an MCP server with 98% SLA\n"
        "Completely unrelated gardening sentence\n",
        encoding="utf-8",
    )

    out = generate._load_cover_letter_master_context("AI Platform Engineer", "Need MCP and FastAPI")
    assert "COVER LETTER MASTER RESUME EXTRACT" in out
    assert "CORE TECHNICAL SKILLS" in out
    assert "98% SLA" in out

    monkeypatch.setattr(cfg, "get_active_master_resume_path", lambda: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(generate, "_load_master_context", lambda: "fallback-context")
    assert generate._load_cover_letter_master_context("x", "y") == "fallback-context"


def test_clean_job_description_for_prompt_strips_noise(isolated_server):
    raw = """
    ![img](http://x)
    [Apply](https://example.com/apply)
    abc1234567890defghijklmnop
    Sign in to continue
    We need engineers to build AI agents and backend APIs.
    """
    cleaned = generate._clean_job_description_for_prompt("Acme", "Engineer", raw, max_chars=400)
    assert cleaned.startswith("Company: Acme")
    assert "Sign in" not in cleaned
    assert "http" not in cleaned
    assert "build AI agents" in cleaned


def test_build_resume_user_message_includes_context_blocks(isolated_server, monkeypatch):
    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {
        "resume_max_tokens": 5000,
        "cover_letter_max_tokens": 6000,
        "safety_margin_tokens": 100,
        "tone_token_budget": 400,
        "max_tone_samples": 2,
    })
    monkeypatch.setattr(generate, "_load_master_context", lambda: "MASTER")
    monkeypatch.setattr(generate, "_portfolio_metrics_block", lambda: "METRICS")
    monkeypatch.setattr(generate, "get_tone_profile_budgeted", lambda **_: "TONE")
    monkeypatch.setattr(generate, "get_customization_strategy", lambda _: "STRATEGY")
    monkeypatch.setattr(generate, "get_interview_context", lambda **_: "INTERVIEW")
    monkeypatch.setattr(generate, "_dynamic_personal_budget", lambda *_: 123)
    monkeypatch.setattr(generate, "_build_personal_context_block", lambda *_a, **_k: ("PERSONAL", None))
    monkeypatch.setattr(generate, "_enforce_token_ceiling", lambda text, _max: text)

    msg = generate._build_resume_user_message("Acme", "Engineer", "JD")
    assert "TARGET COMPANY: Acme" in msg
    assert "MASTER RESUME" in msg
    assert "PERSONAL" in msg
    assert "INTERVIEW" in msg


def test_build_cover_letter_user_message_includes_cleaned_jd_and_contact(isolated_server, monkeypatch):
    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {
        "resume_max_tokens": 5000,
        "cover_letter_max_tokens": 7000,
        "safety_margin_tokens": 100,
        "tone_token_budget": 400,
        "max_tone_samples": 2,
    })
    monkeypatch.setattr(generate, "_clean_job_description_for_prompt", lambda *a, **k: "CLEAN JD")
    monkeypatch.setattr(generate, "_load_cover_letter_master_context", lambda *_: "MASTER")
    monkeypatch.setattr(generate, "_portfolio_metrics_block", lambda: "METRICS")
    monkeypatch.setattr(generate, "get_cover_letter_tone_profile_budgeted", lambda **_: "TONE")
    monkeypatch.setattr(generate, "get_customization_strategy", lambda _: "STRATEGY")
    monkeypatch.setattr(generate, "_assessment_context_block", lambda *_: "ASSESS")
    monkeypatch.setattr(generate, "_cover_letter_narrative_plan", lambda *_: "PLAN")
    monkeypatch.setattr(generate.config, "get_contact_info", lambda: {
        "name": "Jane Doe", "phone": "123", "email": "j@x.com", "linkedin": "https://www.linkedin.com/in/jd",
    })
    monkeypatch.setattr(generate, "get_interview_context", lambda **_: "INTERVIEW")
    monkeypatch.setattr(generate, "_dynamic_personal_budget", lambda *_: 123)
    monkeypatch.setattr(generate, "_build_personal_context_block", lambda *_a, **_k: ("PERSONAL", None))
    monkeypatch.setattr(generate, "_enforce_token_ceiling", lambda text, _max: text)

    msg = generate._build_cover_letter_user_message("Acme", "Engineer", "JD")
    assert "JOB DESCRIPTION:\nCLEAN JD" in msg
    assert "CONTACT BLOCK" in msg
    assert "JANE DOE" in msg
    assert "PERSONAL" in msg


def test_generate_helper_blocks_and_budgets(isolated_server, monkeypatch):
    monkeypatch.setattr(generate.config, "get_contact_name", lambda _default="": "Jane Doe")
    assert generate._safe_filename("Acme!", "Eng #1", "Resume").startswith("Jane Doe Resume -")
    monkeypatch.setattr(generate.config, "get_contact_name", lambda _default="": "")
    assert generate._safe_filename("Acme!", "Eng #1", "Resume").endswith(".txt")

    hook = generate._semantic_story_prefix([{"tags": ["ai_role_hook"]}], "Acme")
    assert "AI ROLE" in hook
    monkeypatch.setattr(generate, "_story_has_company_hook_tags", lambda _s: True)
    company_hook = generate._semantic_story_prefix([{"tags": ["home-depot"], "title": "Home Depot"}], "Home Depot")
    assert "PRIMARY COVER LETTER HOOK" in company_hook
    assert "NO COMPANY-SPECIFIC PERSONAL STORY FOUND" in generate._semantic_story_prefix([], "Other")

    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {"personal_context_token_budget": 700})
    budget = generate._dynamic_personal_budget(["abc"], max_tokens=100, safety=10)
    assert budget >= 0
    assert "[context truncated" in generate._enforce_token_ceiling("x" * 1000, 5)


def test_portfolio_and_assessment_context_blocks(isolated_server, monkeypatch, tmp_path):
    import tools.github as gh_tool

    monkeypatch.setattr(gh_tool, "get_portfolio_metrics", lambda: "No portfolio metrics recorded yet.")
    assert generate._portfolio_metrics_block() == ""
    monkeypatch.setattr(gh_tool, "get_portfolio_metrics", lambda: "⚠ issue")
    assert generate._portfolio_metrics_block() == ""
    monkeypatch.setattr(gh_tool, "get_portfolio_metrics", lambda: "# GitHub portfolio traffic")
    assert "GITHUB PORTFOLIO METRICS" in generate._portfolio_metrics_block()

    import lib.io as io_mod
    jobs = {
        "jobs": [
            {"company": "Acme", "role": "Engineer", "fitment_context": "Strong fit", "status": "queued", "fitment_score": 91, "added_date": "2026-01-01"},
            {"company": "Other", "role": "Engineer", "fitment_context": "skip", "added_date": "2026-01-02"},
        ]
    }
    monkeypatch.setattr(io_mod, "_load_json", lambda *_a, **_k: jobs)
    block = generate._assessment_context_block("Acme", "Engineer")
    assert "STRUCTURED FITMENT ASSESSMENT" in block
    assert "Strong fit" in block


def test_build_personal_context_block_and_ranked_paths(isolated_server, monkeypatch):
    original_ranked = generate._ranked_personal_context_block
    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {"personal_context_token_budget": 400, "max_personal_stories": 2})
    monkeypatch.setattr(generate, "_ranked_personal_context_block", lambda *a, **k: ("RANKED", None))
    block, _diag = generate._build_personal_context_block(role="Engineer", job_description="JD", company="Acme")
    assert block == "RANKED"

    monkeypatch.setattr(generate, "get_personal_context", lambda: generate._NO_PERSONAL_STORIES)
    assert generate._build_personal_context_block()[0] == ""
    monkeypatch.setattr(generate, "get_personal_context", lambda: "story")
    assert generate._build_personal_context_block()[0].startswith("──── PERSONAL CONTEXT")
    monkeypatch.setattr(generate, "_ranked_personal_context_block", original_ranked)

    selected = [{"id": 2, "title": "Work Story", "tags": ["engineering"], "story": "Built stuff."}]
    monkeypatch.setattr(generate, "retrieve_stories", lambda *a, **k: (selected, None))
    monkeypatch.setattr(generate, "_is_ai_role", lambda *_: True)
    monkeypatch.setattr(generate, "_load_ai_role_hook_stories", lambda: [{"id": 1, "title": "Hook", "tags": ["ai_role_hook"], "story": "Origin"}])
    monkeypatch.setattr(generate, "format_stories", lambda rows: "|".join(str(s["id"]) for s in rows))
    out, _ = generate._ranked_personal_context_block("AI Engineer", "JD", "Acme", 500, 3, {"x"}, True)
    assert "1|2" in out


def test_expand_cover_letter_if_short_returns_expanded_content(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_cover_letter_body_word_count", lambda text: 100 if "short" in text else 420)
    monkeypatch.setattr(generate, "_model", lambda: "m")
    monkeypatch.setattr(generate, "_chat_completion_create", lambda *_a, **_k: _FakeResponse("expanded"))

    out = generate._expand_cover_letter_if_short(object(), "short", "user-msg", floor=380)
    assert out == "expanded"


def test_expand_cover_letter_if_short_handles_errors(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_cover_letter_body_word_count", lambda _text: 100)
    monkeypatch.setattr(generate, "_chat_completion_create", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    assert generate._expand_cover_letter_if_short(object(), "orig", "user", floor=380) == "orig"


def test_generate_resume_returns_context_fallback_when_no_client(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_build_resume_user_message", lambda *_: "USER")
    monkeypatch.setattr(generate, "_openai_client", lambda: None)
    out = generate.generate_resume("Acme", "Engineer", "JD")
    assert "No openai_api_key found" in out
    assert "GENERATE_RESUME" in out


def test_generate_resume_success_and_api_error_paths(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_build_resume_user_message", lambda *_: "USER")
    monkeypatch.setattr(generate, "_openai_client", lambda: object())
    monkeypatch.setattr(generate, "_safe_filename", lambda *_: "out.txt")
    monkeypatch.setattr(generate, "save_resume_txt", lambda *_: "saved")
    monkeypatch.setattr(generate, "_model", lambda: "gpt-test")

    import tools.export as export_mod
    monkeypatch.setattr(export_mod, "export_resume_pdf", lambda *_: "pdf")
    monkeypatch.setattr(generate, "_chat_completion_create", lambda *_a, **_k: _FakeResponse("resume body"))
    ok = generate.generate_resume("Acme", "Engineer", "JD")
    assert "✓ Resume generated" in ok
    assert "saved" in ok and "pdf" in ok

    monkeypatch.setattr(generate, "_chat_completion_create", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("api down")))
    err = generate.generate_resume("Acme", "Engineer", "JD")
    assert "OpenAI API error" in err
    assert "Falling back to context package" in err


def test_generate_cover_letter_success_and_latex(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_build_cover_letter_user_message", lambda *_: "USER")
    monkeypatch.setattr(generate, "_openai_client", lambda: object())
    monkeypatch.setattr(generate, "_safe_filename", lambda *_: "cover.txt")
    monkeypatch.setattr(generate, "_sanitize_cover_letter_output", lambda c: c)
    monkeypatch.setattr(generate, "save_cover_letter_txt", lambda *_: "saved")
    monkeypatch.setattr(generate, "_model", lambda: "gpt-test")
    monkeypatch.setattr(generate, "_chat_completion_create", lambda *_a, **_k: _FakeResponse("Dear Hiring Manager,\n\nBody"))

    import tools.export as export_mod
    monkeypatch.setattr(export_mod, "export_cover_letter_pdf", lambda *_a, **_k: "pdf")
    out = generate.generate_cover_letter("Acme", "Engineer", "JD")
    assert "✓ Cover letter generated" in out
    assert "export pipeline: html" in out

    import tools.latex_export as latex_mod
    monkeypatch.setattr(generate, "_extract_cover_letter_body", lambda _c: "body")
    monkeypatch.setattr(latex_mod, "generate_cover_letter_latex", lambda **_: "/tmp/letter.pdf")
    out_latex = generate.generate_cover_letter("Acme", "Engineer", "JD", export_pipeline="latex")
    assert "PDF exported (LaTeX)" in out_latex


def test_generate_cover_letter_returns_context_fallback_when_no_client(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_build_cover_letter_user_message", lambda *_: "USER")
    monkeypatch.setattr(generate, "_openai_client", lambda: None)
    out = generate.generate_cover_letter("Acme", "Engineer", "JD")
    assert "No openai_api_key found" in out
    assert "GENERATE_COVER_LETTER" in out
