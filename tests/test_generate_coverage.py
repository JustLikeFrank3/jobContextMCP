import types

import pytest

from tools import generate

_REAL_GENERATE_RESUME = generate.generate_resume
_REAL_GENERATE_COVER_LETTER = generate.generate_cover_letter


@pytest.fixture(autouse=True)
def _restore_generate_entrypoints(monkeypatch, _mock_llm):
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
    """Stories reach the resume prompt inside the master bundle, not as a
    separately retrieved PERSONAL CONTEXT block — the gate's sources are this
    prompt, so one evidence document means gate == judge == generator."""
    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {
        "resume_max_tokens": 5000,
        "cover_letter_max_tokens": 6000,
        "safety_margin_tokens": 100,
        "tone_token_budget": 400,
        "max_tone_samples": 2,
    })
    monkeypatch.setattr(
        generate, "_load_master_context",
        lambda stories_token_budget=None: (
            "MASTER" if stories_token_budget == 0 else "MASTER\nSTORY-FACT"
        ),
    )
    monkeypatch.setattr(generate, "_portfolio_metrics_block", lambda: "METRICS")
    monkeypatch.setattr(generate, "get_tone_profile_budgeted", lambda **_: "TONE")
    monkeypatch.setattr(generate, "get_customization_strategy", lambda _: "STRATEGY")
    monkeypatch.setattr(generate, "get_interview_context", lambda **_: "INTERVIEW")
    monkeypatch.setattr(generate, "_enforce_token_ceiling", lambda text, _max: text)

    msg = generate._build_resume_user_message("Acme", "Engineer", "JD")
    assert "TARGET COMPANY: Acme" in msg
    assert "MASTER RESUME" in msg
    assert "STORY-FACT" in msg           # stories arrive via the bundle
    assert "PERSONAL CONTEXT" not in msg  # the separate block is gone
    assert "INTERVIEW" in msg


def test_build_resume_user_message_trims_stories_not_the_format_spec(isolated_server, monkeypatch):
    """When the bundle would blow the ceiling, the STORIES tail shrinks; the
    format spec and instructions at the end of the prompt survive intact."""
    captured: list = []

    def fake_bundle(stories_token_budget=None):
        # Fill the granted budget exactly as production does: measured with the
        # SAME estimator the builder uses (tiktoken in CI, chars/4 without it).
        # A chars-imply-tokens shortcut here failed on CI's tiktoken while
        # passing on the fallback estimator — the bug it caught was real and
        # is now fixed in _format_personal_stories, which shares the estimator.
        captured.append(stories_token_budget)
        if not stories_token_budget:
            return "MASTER"
        words: list = []
        while generate.estimate_tokens(" ".join([*words, "story"])) <= stories_token_budget:
            words.append("story")
        return "MASTER\n" + " ".join(words)

    monkeypatch.setattr(generate.config, "get_generation_budgets", lambda: {
        "resume_max_tokens": 2000,
        "cover_letter_max_tokens": 6000,
        "safety_margin_tokens": 100,
        "tone_token_budget": 400,
        "max_tone_samples": 2,
    })
    monkeypatch.setattr(generate, "_load_master_context", fake_bundle)
    monkeypatch.setattr(generate, "_portfolio_metrics_block", lambda: "")
    monkeypatch.setattr(generate, "get_tone_profile_budgeted", lambda **_: "TONE")
    monkeypatch.setattr(generate, "get_customization_strategy", lambda _: "STRATEGY")
    monkeypatch.setattr(generate, "get_interview_context", lambda **_: "")

    msg = generate._build_resume_user_message("Acme", "Engineer", "JD")
    # First call measures with zero stories; second passes the real headroom.
    assert captured[0] == 0
    assert len(captured) == 2 and captured[1] > 0
    assert "[context truncated" not in msg
    assert msg.rstrip().endswith("Output the raw .txt content only.")


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


def test_generate_resume_rejects_unknown_style_before_any_generation(isolated_server, monkeypatch):
    # Fail-fast pin: an unknown style must error out before the prompt is even
    # built (i.e. before any LLM spend or saved .txt), naming the valid set.
    monkeypatch.setattr(
        generate, "_build_resume_user_message",
        lambda *_: (_ for _ in ()).throw(AssertionError("prompt built for an invalid style")),
    )
    out = generate.generate_resume("Acme", "Engineer", "JD", style="ai-platform")
    assert out.startswith("Error: unknown style 'ai-platform'")
    assert "navy" in out and "classic" in out


def test_generate_resume_rejects_unknown_template_before_any_generation(isolated_server, monkeypatch):
    monkeypatch.setattr(
        generate, "_build_resume_user_message",
        lambda *_: (_ for _ in ()).throw(AssertionError("prompt built for an invalid template")),
    )
    out = generate.generate_resume("Acme", "Engineer", "JD", template="fancy")
    assert out.startswith("Error: unknown template 'fancy'")
    assert "modern" in out


def test_generate_cover_letter_rejects_unknown_style_before_any_generation(isolated_server, monkeypatch):
    monkeypatch.setattr(
        generate, "_build_cover_letter_user_message",
        lambda *_: (_ for _ in ()).throw(AssertionError("prompt built for an invalid style")),
    )
    out = generate.generate_cover_letter("Acme", "Engineer", "JD", cl_style="ai-platform")
    assert out.startswith("Error: unknown style 'ai-platform'")
    assert "navy" in out
    err_template = generate.generate_cover_letter("Acme", "Engineer", "JD", cl_template="fancy")
    assert err_template.startswith("Error: unknown CL template 'fancy'")


def test_generate_resume_success_and_api_error_paths(isolated_server, monkeypatch):
    monkeypatch.setattr(generate, "_build_resume_user_message", lambda *_: "USER")
    monkeypatch.setattr(generate, "_openai_client", lambda: object())
    monkeypatch.setattr(generate, "_safe_filename", lambda *_: "out.txt")
    monkeypatch.setattr(generate, "save_resume_txt", lambda *_: "saved")
    monkeypatch.setattr(generate, "_model", lambda: "gpt-test")

    import tools.export as export_mod
    monkeypatch.setattr(export_mod, "export_resume_pdf", lambda *_, **__: "pdf")
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


# ── single-shot correction pass (provenance violations re-drafted) ──────────

class TestCorrectUnsourcedClaims:
    """The gate used to run AFTER save_resume_txt and the PDF export, so a
    violation was a report line on an already-shipped document. These pin the
    correction pass and — more importantly — that every failure mode falls
    back to the original draft rather than losing it."""

    SYSTEM = "sys"
    USER = "Master resume says 34% latency cut and $1.2M saved."

    def _client(self):
        return object()

    def test_clean_draft_makes_no_second_call(self, monkeypatch):
        calls = []
        monkeypatch.setattr(generate, "_chat_completion_create",
                            lambda *a, **k: calls.append(k) or _FakeResponse("x"))
        out, n = generate._correct_unsourced_claims(
            self._client(), label="resume_generate", system=self.SYSTEM,
            user_msg=self.USER, content="Cut latency 34%, saved $1.2M.",
        )
        assert (out, n) == ("Cut latency 34%, saved $1.2M.", 0)
        assert calls == [], "clean draft must not pay for a correction call"

    def test_fabricated_number_triggers_one_correction(self, monkeypatch):
        seen = {}

        def _fake(_client, **kwargs):
            seen.update(kwargs)
            return _FakeResponse("Cut latency 34%.")

        monkeypatch.setattr(generate, "_chat_completion_create", _fake)
        out, n = generate._correct_unsourced_claims(
            self._client(), label="resume_generate", system=self.SYSTEM,
            user_msg=self.USER, content="Cut latency 34% and uptime 99.99%.",
        )
        assert (out, n) == ("Cut latency 34%.", 1)
        assert seen["label"] == "resume_generate_correct"
        msgs = seen["messages"]
        assert "99.99%" in msgs[-1]["content"], "the violation must be named"
        # The draft is replayed as history, NOT as a trailing assistant prefill
        # (which 400s on Claude 4.6+ and would break the anthropic provider).
        assert msgs[-1]["role"] == "user"
        assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]

    def test_correction_api_failure_keeps_the_original_draft(self, monkeypatch):
        monkeypatch.setattr(generate, "_chat_completion_create",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
        draft = "Cut latency 34% and uptime 99.99%."
        assert generate._correct_unsourced_claims(
            self._client(), label="l", system=self.SYSTEM,
            user_msg=self.USER, content=draft,
        ) == (draft, 0)

    def test_empty_correction_keeps_the_original_draft(self, monkeypatch):
        """A truncated or empty correction must not be saved over a real
        document — losing the draft is worse than shipping it with a ⚠."""
        monkeypatch.setattr(generate, "_chat_completion_create",
                            lambda *a, **k: _FakeResponse("   "))
        draft = "Cut latency 34% and uptime 99.99%."
        assert generate._correct_unsourced_claims(
            self._client(), label="l", system=self.SYSTEM,
            user_msg=self.USER, content=draft,
        ) == (draft, 0)

    # ── verification pass (2026-08-31): the revised text gets re-checked ──

    def test_unfixed_violation_gets_a_second_and_final_pass(self, monkeypatch):
        """A revise that fails to fix everything used to ship unverified —
        the 08-26/08-31 nightlies measured contradicted placement claims
        reaching final documents. The loop now re-checks and pays for one
        more pass, then stops: never a third correction call."""
        bodies = ["Cut 34% and uptime 98%.", "Cut 34% and uptime 97%."]
        calls = []

        def _fake(_client, **kwargs):
            calls.append(kwargs)
            return _FakeResponse(bodies[len(calls) - 1])

        monkeypatch.setattr(generate, "_chat_completion_create", _fake)
        out, n = generate._correct_unsourced_claims(
            self._client(), label="l", system=self.SYSTEM,
            user_msg=self.USER, content="Cut 34% and uptime 99.99%.",
        )
        assert (out, n) == ("Cut 34% and uptime 97%.", 2)
        assert len(calls) == 2, "budget is two revisions, hard stop"
        assert "98%" in calls[1]["messages"][-1]["content"], (
            "the second pass must name the SURVIVING violation from the revised text")

    def test_critic_finding_on_revised_text_is_caught_by_verification(self, monkeypatch):
        """The verification pass re-runs the critic on what the revise
        produced — a first-sample miss or an unfixed contradicted finding no
        longer ships silently."""
        critiques = []

        def _fake_critique(_bundle, _content):
            critiques.append(_content)
            if len(critiques) == 1:
                return {"model": "m", "findings": [{
                    "claim": "Fabric migration under Level 5",
                    "verdict": "contradicted",
                    "evidence": "master: Fabric migration was Level 6 work",
                }]}
            return {"model": "m", "findings": []}

        monkeypatch.setattr("evals.critic.critique_document", _fake_critique)
        monkeypatch.setattr("evals.critic.enforcement_enabled", lambda: True)
        monkeypatch.setattr(generate, "_chat_completion_create",
                            lambda *a, **k: _FakeResponse("Cut latency 34%. Relocated."))
        out, n = generate._correct_unsourced_claims(
            self._client(), label="l", system=self.SYSTEM,
            user_msg=self.USER, content="Cut latency 34%.",  # numerically clean
        )
        assert (out, n) == ("Cut latency 34%. Relocated.", 1)
        assert len(critiques) == 2, "revised content must get its own critique"
        assert critiques[1] == "Cut latency 34%. Relocated."

    def test_second_pass_failure_keeps_the_first_revision(self, monkeypatch):
        """Fail-soft direction matters: a pass-two error returns the pass-one
        revision (strictly better than the draft), never the original."""
        calls = []

        def _fake(_client, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("429")
            return _FakeResponse("Cut 34% and uptime 98%.")  # still dirty

        monkeypatch.setattr(generate, "_chat_completion_create", _fake)
        out, n = generate._correct_unsourced_claims(
            self._client(), label="l", system=self.SYSTEM,
            user_msg=self.USER, content="Cut 34% and uptime 99.99%.",
        )
        assert (out, n) == ("Cut 34% and uptime 98%.", 1)


def test_generate_resume_corrects_before_saving(isolated_server, monkeypatch):
    """The whole point: what reaches save_resume_txt is the corrected text."""
    monkeypatch.setattr(generate, "_build_resume_user_message",
                        lambda *_: "Master says 34% latency cut.")
    monkeypatch.setattr(generate, "_openai_client", lambda: object())
    monkeypatch.setattr(generate, "_safe_filename", lambda *_: "out.txt")
    monkeypatch.setattr(generate, "_model", lambda: "gpt-test")

    saved = {}
    monkeypatch.setattr(generate, "save_resume_txt",
                        lambda _f, c: saved.setdefault("content", c) or "saved")
    import tools.export as export_mod
    monkeypatch.setattr(export_mod, "export_resume_pdf", lambda *_, **__: "pdf")

    bodies = iter(["Cut latency 34% and uptime 99.99%.", "Cut latency 34%."])
    monkeypatch.setattr(generate, "_chat_completion_create",
                        lambda *a, **k: _FakeResponse(next(bodies)))

    out = generate.generate_resume("Acme", "Engineer", "JD")
    assert saved["content"] == "Cut latency 34%.", "the fabricated draft was saved"
    assert "99.99%" not in out
    assert "Provenance: ✓ PASS" in out


class TestNumericIntegrityRules:
    """The 2026-08-12 nightly flagged hallucinations in every run AFTER the
    correction loop -- all in classes the regex gate cannot see (scope-shifted
    numbers, double-counted metrics, reconstructed figures). These rules are
    the prompt-side countermeasure; pin them so a later prompt edit doesn't
    silently drop the constraints the eval trend depends on."""

    def test_resume_prompt_carries_the_three_rules(self):
        from tools.generate_prompts import RESUME_SYSTEM

        assert "NUMERIC INTEGRITY" in RESUME_SYSTEM
        assert "never migrate to a different claim" in RESUME_SYSTEM   # scope-shift
        assert "WITHOUT a\n   number" in RESUME_SYSTEM.replace("    ", "   ") or \
               "WITHOUT a" in RESUME_SYSTEM                            # verbatim-or-omit
        assert "EXACTLY ONE place" in RESUME_SYSTEM                    # anti-double-count

    def test_cover_letter_prompt_carries_the_rules(self):
        from tools.generate_prompts import COVER_LETTER_SYSTEM

        assert "NUMERIC INTEGRITY" in COVER_LETTER_SYSTEM
        assert "never moved onto a different claim" in COVER_LETTER_SYSTEM
        assert "at most once" in COVER_LETTER_SYSTEM


class TestAttributionDisciplineRules:
    """Round 3 prompt-side countermeasure: after the 2026-08-19 run, ALL
    surviving semantic flags were attribution-shaped — bullets under the role
    the master explicitly corrects away from, one project's timeframe annexing
    sibling work, JD titles worn as held titles. Pin the rules so a later
    prompt edit can't silently drop the constraints Friday's trend measures."""

    def test_resume_system_carries_attribution_rules(self):
        from tools.generate_prompts import RESUME_SYSTEM

        assert "ATTRIBUTION DISCIPLINE" in RESUME_SYSTEM
        assert "that\n       note is BINDING" in RESUME_SYSTEM or "note is BINDING" in RESUME_SYSTEM
        assert "does not cover any\n       other migration" in RESUME_SYSTEM \
            or "does not cover any" in RESUME_SYSTEM
        assert "titles the master states the\n       candidate actually held" in RESUME_SYSTEM \
            or "candidate actually held" in RESUME_SYSTEM
        assert "character-for-character" in RESUME_SYSTEM

    def test_cover_letter_system_carries_attribution_rule(self):
        from tools.generate_prompts import COVER_LETTER_SYSTEM

        assert "ATTRIBUTION" in COVER_LETTER_SYSTEM
        assert "timeline correction note" in COVER_LETTER_SYSTEM


class TestCriticEnforcementInCorrectionPass:
    """Phase 3: contradicted-with-evidence critic findings drive the SAME
    single correction pass the numeric gate uses. Earned 2026-08-21 (11/11
    maiden precision). Fail-soft is the contract: a critic outage must never
    block generation or discard the numeric gate's verdict."""

    def _run(self, monkeypatch, *, numeric_violations, critic_result, enforce="1"):
        import evals.critic as critic_mod
        import lib.provenance as prov_mod

        monkeypatch.setenv("CRITIC_ENFORCE", enforce)
        monkeypatch.setattr(generate, "_load_master_context",
                            lambda *a, **k: "BUNDLE")
        # Content-sensitive mocks: the flags apply to the DRAFT; the corrected
        # text checks clean — otherwise the verification pass (2026-08-31)
        # would rightly see the "still-dirty" constant and spend its second
        # revision, which is the loop working, not these contracts.
        monkeypatch.setattr(
            prov_mod, "check_claims",
            lambda draft, *a, **k: list(numeric_violations) if draft == "DRAFT" else [])

        def critique(_bundle, doc, *a, **k):
            if isinstance(critic_result, Exception):
                raise critic_result
            return critic_result if doc == "DRAFT" else {"findings": []}
        monkeypatch.setattr(critic_mod, "critique_document", critique)

        calls = []

        def fake_create(client, **kwargs):
            calls.append(kwargs)
            return _FakeResponse("CORRECTED DOC")

        monkeypatch.setattr(generate, "_chat_completion_create", fake_create)
        content, revisions = generate._correct_unsourced_claims(
            client=object(), label="resume", system="SYS",
            user_msg="USER", content="DRAFT",
        )
        return content, revisions, calls

    def test_contradiction_alone_triggers_correction(self, monkeypatch):
        content, revisions, calls = self._run(
            monkeypatch, numeric_violations=[],
            critic_result={"findings": [{"claim": "Azure under L5",
                                         "verdict": "contradicted",
                                         "evidence": "never place Azure under Level 5"}]},
        )
        assert (content, revisions) == ("CORRECTED DOC", 1)
        prompt = calls[0]["messages"][-1]["content"]
        assert "ENTAILMENT VIOLATIONS" in prompt
        assert "never place Azure under Level 5" in prompt

    def test_numeric_and_critic_feedback_combine_in_one_pass(self, monkeypatch):
        content, revisions, calls = self._run(
            monkeypatch, numeric_violations=["47%"],
            critic_result={"findings": [{"claim": "c", "verdict": "contradicted",
                                         "evidence": "e"}]},
        )
        assert revisions == 1
        prompt = calls[0]["messages"][-1]["content"]
        assert "PROVENANCE VIOLATIONS" in prompt and "ENTAILMENT VIOLATIONS" in prompt
        assert len(calls) == 1                        # one pass, both kinds

    def test_unsupported_findings_do_not_trigger_correction(self, monkeypatch):
        content, revisions, calls = self._run(
            monkeypatch, numeric_violations=[],
            critic_result={"findings": [{"claim": "c", "verdict": "unsupported",
                                         "evidence": "NONE"}]},
        )
        assert (content, revisions) == ("DRAFT", 0)
        assert calls == []

    def test_critic_outage_fails_soft_numeric_gate_still_corrects(self, monkeypatch):
        content, revisions, calls = self._run(
            monkeypatch, numeric_violations=["47%"],
            critic_result=RuntimeError("critic upstream down"),
        )
        assert (content, revisions) == ("CORRECTED DOC", 1)
        assert "PROVENANCE VIOLATIONS" in calls[0]["messages"][-1]["content"]

    def test_kill_switch_restores_numeric_only_behavior(self, monkeypatch):
        content, revisions, calls = self._run(
            monkeypatch, numeric_violations=[],
            critic_result={"findings": [{"claim": "c", "verdict": "contradicted",
                                         "evidence": "e"}]},
            enforce="0",
        )
        assert (content, revisions) == ("DRAFT", 0)
        assert calls == []
