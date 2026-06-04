from tools import generate


HOME_DEPOT_STORY = {
    "id": 41,
    "title": "Home Depot — Every Saturday, Childhood Brand Memory",
    "story": "Every Saturday growing up, my family went to Home Depot.",
    "tags": ["home-depot", "childhood", "brand-connection", "cover-letter-anchor"],
}

GM_STORY = {
    "id": 7,
    "title": "GM — AI adoption and engineering enablement",
    "story": "Drove AI-assisted engineering adoption and production tooling improvements.",
    "tags": ["ai_adoption", "engineering", "leadership"],
}


def test_workday_rejects_home_depot_company_hook(monkeypatch):
    def fake_retrieve_stories(*args, **kwargs):
        return [HOME_DEPOT_STORY], None

    monkeypatch.setattr(generate, "retrieve_stories", fake_retrieve_stories)

    block, _diag = generate._build_personal_context_block(
        role="Software Engineer, AI Platform",
        job_description="Workday AI Platform role building agentic workflows.",
        company="Workday",
        token_budget=500,
        boost_tags=generate._COVER_LETTER_HOOK_TAGS,
        semantic=True,
    )

    assert "NO COMPANY-SPECIFIC PERSONAL STORY FOUND for Workday" in block
    assert "Home Depot" not in block
    assert "Every Saturday" not in block


def test_home_depot_keeps_home_depot_company_hook(monkeypatch):
    def fake_retrieve_stories(*args, **kwargs):
        return [HOME_DEPOT_STORY], None

    monkeypatch.setattr(generate, "retrieve_stories", fake_retrieve_stories)

    block, _diag = generate._build_personal_context_block(
        role="Software Engineer",
        job_description="Home Depot retail technology platform role.",
        company="Home Depot",
        token_budget=500,
        boost_tags=generate._COVER_LETTER_HOOK_TAGS,
        semantic=True,
    )

    assert "PRIMARY COVER LETTER HOOK" in block
    assert "explicitly tied to Home Depot" in block
    assert "Home Depot" in block
    assert "Every Saturday" in block


def test_non_company_story_can_remain_without_becoming_hook(monkeypatch):
    def fake_retrieve_stories(*args, **kwargs):
        return [GM_STORY], None

    monkeypatch.setattr(generate, "retrieve_stories", fake_retrieve_stories)

    block, _diag = generate._build_personal_context_block(
        role="Software Engineer, AI Platform",
        job_description="Workday AI Platform role building agentic workflows.",
        company="Workday",
        token_budget=500,
        boost_tags=generate._COVER_LETTER_HOOK_TAGS,
        semantic=True,
    )

    assert "NO COMPANY-SPECIFIC PERSONAL STORY FOUND for Workday" in block
    assert "PRIMARY COVER LETTER HOOK" not in block
    assert "AI adoption" in block


def test_ai_cover_letter_narrative_plan_uses_current_jobcontextmcp():
    plan = generate._cover_letter_narrative_plan(
        "Workday",
        "Software Engineer, AI Platform",
        "Build AI agents, RAG workflows, and platform APIs.",
    )

    assert "current AI platform builder" in plan
    assert "I built and maintain jobContextMCP" in plan
    assert "Do not lead with the Azure migration" in plan
    assert "never only as a completed past-tense artifact" in plan


def test_cover_letter_sanitizer_fixes_awkward_clone_phrasing():
    raw = (
        "Workday's focus on AI platform development aligns perfectly with my experience.\n"
        "I built a Model Context Protocol (MCP) server, open-sourced and cloned 371 times in the last 14 days."
    )

    cleaned = generate._sanitize_cover_letter_output(raw)

    assert "aligns perfectly" not in cleaned
    assert "cloned 371 times" not in cleaned
    assert "I built and maintain jobContextMCP" in cleaned
    assert "currently shows 371 clones in the last 14 days" in cleaned
