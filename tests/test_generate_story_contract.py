from tools import generate
from tools import tone


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


def test_non_company_story_can_remain_without_becoming_hook_for_non_ai_role(monkeypatch):
    def fake_retrieve_stories(*args, **kwargs):
        return [GM_STORY], None

    monkeypatch.setattr(generate, "retrieve_stories", fake_retrieve_stories)

    block, _diag = generate._build_personal_context_block(
        role="Software Engineer, Retail Platform",
        job_description="Workday retail platform role building backend workflows.",
        company="Workday",
        token_budget=500,
        boost_tags=generate._COVER_LETTER_HOOK_TAGS,
        semantic=True,
    )

    assert "NO COMPANY-SPECIFIC PERSONAL STORY FOUND for Workday" in block
    assert "PRIMARY COVER LETTER HOOK" not in block
    assert "AI adoption" in block


def test_ai_role_detection_does_not_match_ai_inside_retail():
    assert not generate._is_ai_role(
        "Software Engineer, Retail Platform",
        "Build retail workflows, payment APIs, and store operations tooling.",
    )


def test_cover_letter_tone_prefers_high_signal_cover_samples(tmp_path, monkeypatch):
    """Cover-letter sources should rank above other sample types."""
    import json
    import lib.config as cfg

    tone_file = tmp_path / "tone.json"
    tone_file.write_text(json.dumps({"samples": [
        {"id": 1, "source": "cover_letter_ford_motor_credit",
         "text": "Ford Motor Credit cover letter sample text." * 10, "context": ""},
        {"id": 2, "source": "cover_letter_airbnb_listings",
         "text": "Airbnb cover letter sample text." * 10, "context": ""},
        {"id": 3, "source": "linkedin_post_unhinged_bio_2026_05_25",
         "text": "LinkedIn post sample text." * 10, "context": ""},
        {"id": 4, "source": "resume_google",
         "text": "Resume sample text." * 10, "context": ""},
    ]}))

    monkeypatch.setattr(cfg, "TONE_FILE", tone_file)
    profile = tone.get_cover_letter_tone_profile_budgeted(token_budget=1800, max_samples=7)

    assert "cover_letter_ford_motor_credit" in profile
    assert "cover_letter_airbnb_listings" in profile
    assert "linkedin_post_unhinged_bio_2026_05_25" in profile


def test_ai_cover_letter_narrative_plan_uses_current_jobcontextmcp():
    plan = generate._cover_letter_narrative_plan(
        "Workday",
        "Software Engineer, AI Platform",
        "Build AI agents, RAG workflows, and platform APIs.",
    )

    assert "current AI platform builder" in plan
    assert "Do not lead with cloud migration" in plan
    assert "cloned X times" in plan  # phrasing rule present
    assert "aligns perfectly" in plan  # alignment rule present


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


def test_cover_letter_sanitizer_removes_corporate_sludge_from_uncle_roy_output():
    raw = """Dear Hiring Manager,

Uncle Roy worked at Intellicorp building expert systems on Lisp in the eighties. He handed me one of the first Raspberry Pis, and there's a direct line from that to the jobContextMCP server I maintain today. This role at Sema4.ai feels like the same thread at production scale. Your mission to enable collaboration between people and AI agents resonates with the work I've been doing, turning cognitive architectures into reliable, scalable platforms.

I built and maintain jobContextMCP, an AI persistent job search assistant that structures memory for GitHub Copilot and Claude. It currently shows 338 clones in the last 14 days. The server uses 77 MCP tools for job tracking, resume generation, and semantic search, all under $0.10 to index a complete job search corpus. The architecture follows FastAPI best practices, with tools organized into specialized modules. This project demonstrates my ability to translate AI capabilities into durable backend systems.

At GM, I led the AI adoption initiative, achieving a 35%+ organizational uptake. I also ensured platform reliability with zero downtime and a 98% SLA using Kafka. My work on LiveVox's cross-platform audio monitoring application achieved 2.8ms latency on web and 12.7ms on iPhone, showcasing elite-level performance optimization. These projects highlight my capability to build robust systems that perform at scale.

Sema4.ai's focus on transforming knowledge work aligns with my experience in building platforms that are not just intelligent but operable and reliable. I want a conversation to explore how my background can contribute to your Agent Platform's success.

Regards,
Frank MacBride"""

    cleaned = generate._sanitize_cover_letter_output(raw)
    lowered = cleaned.lower()

    for bad in [
        "resonates with",
        "demonstrates my ability",
        "best practices",
        "showcasing",
        "not a slide",
        "highlight my capability",
        "aligns with my experience",
        "contribute to your agent platform's success",
        "frank v. macbride",
    ]:
        assert bad not in lowered

    assert "how to turn agentic AI into something people can actually use" in cleaned
    assert "one giant prompt-shaped blob" in cleaned
    assert "measured round-trip audio latency from microphone input to speaker output" in cleaned
    assert "My uncle Roy worked at Intellicorp" in cleaned
    assert "\nUncle Roy worked" not in cleaned
    assert "direct line from that to the MCP server" in cleaned
    assert cleaned.count("jobContextMCP") == 1
    assert "Kindest Regards," in cleaned
    assert "Frank MacBride" in cleaned
