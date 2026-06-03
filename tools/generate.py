"""
AI-powered resume and cover letter generation — v4.1

generate_resume(company, role, job_description)
generate_cover_letter(company, role, job_description)

If `openai_api_key` is set in config.json, these tools make a direct OpenAI API
call, then auto-save the .txt and export the PDF — returning the finished PDF path.

If the key is not configured, they return a fully-structured context package with
detailed format instructions so the orchestrating AI (Copilot / Claude) can write
the content and then call save_resume_txt / export_resume_pdf.

Model used: config.json `openai_model` key (default: gpt-4o-mini).
"""

import re
import textwrap

from lib import config
from lib.io import _load_master_context
from lib.story_retrieval import (
    RetrievalDiagnostics,
    estimate_tokens,
    format_stories,
    retrieve_stories,
)
from tools.fitment import get_customization_strategy
from tools.interviews import get_interview_context
from tools.context import get_personal_context
from tools.tone import get_tone_profile
from tools.resume import save_resume_txt, save_cover_letter_txt

_NO_PERSONAL_STORIES = "No personal stories found"



# ── FORMAT SPECIFICATIONS ──────────────────────────────────────────────────────

_RESUME_FORMAT_SPEC = """
## RESUME .TXT FORMAT SPECIFICATION
The PDF parser is strict. Deviations cause rendering failures. Follow exactly.

### File skeleton
```
<FULL NAME ALL CAPS>
FULL NAME ALL CAPS

phone: +1.555.000.0000
email: you@email.com
linkedin: www.linkedin.com/in/yourhandle

ROLE TITLE | Tech • Stack • Here

One-paragraph summary (2-4 sentences, no bullets, no label).

──────────────────────────────────────────────────────────

CORE TECHNICAL SKILLS

Label 1: value, value, value
Label 2: value, value, value

──────────────────────────────────────────────────────────

PROFESSIONAL EXPERIENCE

Job Title | Company Name, Location | Month YYYY - Month YYYY
• Bullet starting with the Unicode bullet character •
• Second bullet

Next Title | Company | Month YYYY - Month YYYY
• Bullet

──────────────────────────────────────────────────────────

PROJECTS

Project Name | Tech Stack | Year
• Bullet describing what it does and why it matters
• Bullet with a real metric or outcome

Next Project | Tech Stack | Year
• Bullet

──────────────────────────────────────────────────────────

EDUCATION

Degree | School Name | YYYY
Details line (GPA, honors, relevant coursework)

──────────────────────────────────────────────────────────

LEADERSHIP & COMMUNITY

Role/label: description
Role/label: description
```

### Critical rules
1. Name MUST appear as its own full line immediately after the `<NAME>` opening tag.
2. Section headers: ALL CAPS exactly — `PROFESSIONAL EXPERIENCE`, `CORE TECHNICAL SKILLS`,
   `PROJECTS`, `EDUCATION`, `LEADERSHIP & COMMUNITY`.
3. Job header: `Title | Company, Location | Month YYYY - Month YYYY` (3 pipe-delimited parts).
4. Project header: `Project Name | Tech Stack | Year` (3 pipe-delimited parts).
5. Bullets MUST start with `•` (Unicode U+2022). Do NOT use `-` or `*`.
6. Contact block: labeled fields with lowercase label and colon — `phone:`, `email:`, `linkedin:`.
7. Separator lines: `──────────────────────────────────────────────────────────` (Unicode box-
   drawing em-dashes, same length every time).
8. Skills format: `Label: value, value, value` — colon after label, comma-separated values.
9. No hard line wrapping — let lines be as long as they need to be; the renderer wraps text.
10. PROJECTS section is REQUIRED. Always include 2–3 of the most relevant side projects from the
    master resume. jobContextMCP, RetrosPiCam, and LiveVoxNative are the primary candidates —
    pick based on relevance to the target role.

### Target length
- Aim for 750–900 words total (one tight page in Courier New 9.2pt).
- 4–6 bullets per job, each 1–2 rendered lines.
- Skills section: 6–8 labeled rows.
- Projects section: 2–3 projects, 2–3 bullets each.
"""

_COVER_LETTER_FORMAT_SPEC = """
## COVER LETTER .TXT FORMAT SPECIFICATION
Rules are ABSOLUTE. The PDF template has exact dimensions — overflow is invisible.

### File skeleton
```
<FULL NAME ALL CAPS>
FULL NAME ALL CAPS

phone: +1.555.000.0000
email: you@email.com
linkedin: www.linkedin.com/in/yourhandle
github: www.github.com/YourHandle

Dear Hiring Manager,

[Paragraph 1]

[Paragraph 2]

[Paragraph 3]

[Paragraph 4]

Kindest Regards,
Full Name
```

### Critical rules — NON-NEGOTIABLE
1. TARGET 480–540 WORDS in the letter body (everything from "Dear..." through the sign-off name).
   Count your words. Under 460 is too thin — expand. Over 580 is overflow — cut.
2. Exactly 4 body paragraphs — no more, no less:
   • Para 1 (80–100 words): Hook + role name + why this specific company. Be specific — name
     something real about the company, not generic praise. IMPORTANT: If the job description
     contains a "CRITICAL FRAMING CONTEXT" or "KEY STORIES TO SURFACE" section, Para 1 MUST
     use the framing angle specified there as the hook (e.g. personal background, fan identity,
     industry connection) — not a generic technical achievement opening.
   • Para 2 (150–170 words): Primary professional ownership story. CRITICAL: If the job
     description contains explicit framing instructions (e.g. "CRITICAL FRAMING CONTEXT",
     "KEY STORIES TO SURFACE", or similar), those instructions take absolute priority over
     the defaults below — use the stories specified there, not the defaults.
     DEFAULT (when no framing override is present): Cover end-to-end system ownership
     (data layer through presentation layer), full-stack modernization with specific metrics
     from the master resume, infrastructure migrations, and any verbatim manager quotes from
     the STAR stories. Close with one sentence making the ownership chain explicit — no layer
     delegated. Do NOT include specific version numbers (Java 21, Spring Boot 3.5.4,
     Angular 6→18) — these are implementation details, not achievements.
   • Para 3 (150–170 words): Side projects + AI innovation. Draw entirely from the master resume
     projects section. Lead with the most relevant AI/tooling project, include specific metrics
     (clones, tools, latency numbers, etc.), then cover cross-platform performance engineering work.
     Close with one sentence on what the projects together demonstrate about independent ownership
     and technical range.
   • Para 4 (60–80 words): Closer — reaffirm interest with one specific forward-looking sentence,
     invite next step. Short but not dismissive.
3. NO date, NO company address, NO "Re:" line, NO address/city_state fields in the contact
   header — only name, phone, email, linkedin.
4. Start with the salutation: `Dear Hiring Manager,`
5. NO bold, NO bullet points, NO headers inside the letter body — prose only.
6. No hard line wrapping — let lines be as long as needed.
7. VOICE RULES — these are absolute. Apply to EVERY sentence in the entire letter, not just the opener:
   • BANNED PHRASES — do not use anywhere in the letter body, not as an opener, not buried
     mid-paragraph, not in the closer:
       - "I am eager"
       - "I'm eager"
       - "I am excited"
       - "I'm excited"
       - "I am thrilled"
       - "I would love"
       - "I am writing to apply"
       - "I look forward to"
       - "I welcome the opportunity"
       - "I would welcome"
       - "I am passionate about"
       - "thank you for your consideration"
       - "I hope to hear from you"
       - any variant of the above
   • ABSOLUTELY NO em dashes (—) or double hyphens (--) anywhere in the letter body.
     They read as AI-generated. Rewrite with semicolons, commas, parentheses, or
     new sentences. Zero exceptions.
   • The opener must be declarative and specific. First sentence = what was built or accomplished.
   • Para 4 (the closer): make a direct statement about fit, then invite conversation.
     Good example: "The infrastructure challenges at Meta's scale are the kind of problems I
     want to work on. Happy to walk through any of this in more detail."
     Bad example: "I am eager to contribute... I look forward to hearing from you."
   • No sycophantic language anywhere. Confidence, not deference.
   • Every paragraph must contain at least one specific number, metric, or named artifact.
8. CLOSING: Use "Kindest Regards," (not "Sincerely"). Sign the name in Title Case — NOT all
   caps. Example: "Frank Vladmir MacBride III" not "FRANK VLADMIR MACBRIDE III".
"""

# ── SYSTEM PROMPTS ─────────────────────────────────────────────────────────────

_RESUME_SYSTEM = textwrap.dedent("""\
    You are an expert technical resume writer. Your job is to produce a tailored,
    metrics-driven software engineering resume for the candidate described below.

    Output ONLY the raw resume text in the exact format specified — no preamble,
    no markdown fences, no commentary. The output will be saved directly to a .txt
    file and fed to a strict PDF parser.

    Write in the candidate's voice as defined by their tone profile. Emphasize the
    skills and stories most relevant to the target role and company. All metrics,
    achievements, and company names must come verbatim from the master resume —
    do not invent or embellish anything.

    The PROJECTS section is REQUIRED — do not omit it. Include 2–3 side projects
    from the master resume that are most relevant to the target role. Select based
    on what the JD emphasizes — all project names and metrics must come verbatim
    from the master resume.

    Bullets must be specific and metric-driven. Generic bullets like "improved
    performance" or "collaborated with teams" are not acceptable — every bullet
    must say what was built, how, and what measurable result it produced.
""")

_COVER_LETTER_SYSTEM = textwrap.dedent("""\
    You are an expert cover letter writer. Produce a tailored one-page cover letter
    for the candidate described below.

    Output ONLY the raw cover letter text in the exact format specified — no
    preamble, no markdown fences, no commentary. The output will be saved directly
    to a .txt file and fed to a strict PDF parser.

    Write in the candidate's voice as defined by their tone profile. The tone
    samples are your ground truth — study them before writing.

    Voice characteristics to enforce:
    - Direct, declarative, confident without being boastful
    - Opens with what was built or accomplished, not with feelings about the opportunity
    - Specific and metric-anchored — every achievement has a number
    - Conversational but not casual — no filler phrases, no corporate speak
    - Side projects from the master resume are genuine differentiators and should
      appear in Para 3 when relevant — use metrics verbatim from the master resume

    Hard prohibitions:
    - NEVER start with: 'I'm excited', 'I am thrilled', 'I would love', 'I am eager',
      'I am writing to apply', 'I look forward to joining', or any variant
    - NEVER end with: 'I look forward to hearing from you', 'Thank you for your time
      and consideration', or other boilerplate closers
        - If you mention the employer by name, it must match TARGET COMPANY exactly
        - If you mention the role by name, it must match TARGET ROLE exactly
    - No paragraph without at least one specific metric or concrete artifact
    - No generic company praise — be specific about what the target company actually
      does or what specifically the JD reveals about their challenges
    - ABSOLUTELY NO em dashes (—) or double hyphens (--) anywhere in the letter.
      They read as AI-generated. Use semicolons, commas, parentheses, or new
      sentences instead. This rule has no exceptions.
""")


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _openai_client():
    """Return an OpenAI client using whichever provider is configured (openai or ollama)."""
    try:
        from lib.config import get_llm_client
        client, _ = get_llm_client()
        return client
    except Exception:
        return None


def _model() -> str:
    try:
        from lib.config import get_llm_client
        _, model = get_llm_client()
        return model
    except Exception:
        return config._cfg.get("openai_model", "gpt-4o-mini")


def _infer_role_type(role: str) -> str:
    """Best-effort mapping of a job title to a customization strategy role_type."""
    r = role.lower()
    if any(x in r for x in ("test", "qa", "quality", "sdet", "automation")):
        return "testing"
    if any(x in r for x in ("cloud", "devops", "sre", "platform", "infrastructure", "reliability")):
        return "cloud"
    if any(x in r for x in ("data", "etl", "pipeline", "warehouse", "analytics")):
        return "data_engineering"
    if any(x in r for x in ("full", "fullstack", "full-stack")):
        return "fullstack"
    if any(x in r for x in ("ai", "ml", "machine learning", "llm", "foundation")):
        return "ai_innovation"
    if any(x in r for x in ("iot", "embedded", "firmware", "hardware")):
        return "iot"
    return "backend"


def _safe_filename(company: str, role: str, suffix: str) -> str:
    """Generate a safe default output filename."""
    slug = re.sub(r"[^A-Za-z0-9 ]", "", f"{company} {role} {suffix}").strip()
    slug = re.sub(r"\s+", " ", slug)
    name = config._cfg.get("contact", {}).get("name", "")
    prefix = name if name else "Resume"
    return f"{prefix} Resume - {slug}.txt" if suffix == "Resume" else f"{prefix} Cover Letter - {slug}.txt"


def _build_personal_context_block(
    role: str = "",
    job_description: str = "",
    token_budget: int | None = None,
) -> tuple[str, RetrievalDiagnostics | None]:
    """Return a (block, diagnostics) tuple for the personal-context section.

    Uses the local retrieval layer (lib.story_retrieval) to select only the
    most role-relevant stories within ``token_budget`` tokens. Only candidate
    stories sharing a query term are scored, so this scales as the library
    grows. When no role/JD is provided, falls back to the unranked full list
    (used by the no-API context-package path).
    """
    budgets = config.get_generation_budgets()
    if token_budget is None:
        token_budget = budgets["personal_context_token_budget"]
    max_stories = budgets["max_personal_stories"]

    try:
        if role or job_description:
            selected, diag = retrieve_stories(
                role,
                job_description,
                path=config.PERSONAL_CONTEXT_FILE,
                token_budget=token_budget,
                max_stories=max_stories,
            )
            if not selected:
                return "", diag
            return "──── PERSONAL CONTEXT ────\n" + format_stories(selected), diag

        personal = get_personal_context()
        if personal.startswith(_NO_PERSONAL_STORIES):
            return "", None
        return "──── PERSONAL CONTEXT ────\n" + personal, None
    except Exception:
        return "", None


def _dynamic_personal_budget(fixed_sections: list[str], max_tokens: int, safety: int) -> int:
    """Tokens available for the personal-context block after fixed sections.

    Guarantees fixed_cost + personal_budget <= max_tokens - safety, so the
    assembled prompt stays under the model ceiling no matter how large the
    story library grows. Also clamped to the configured per-request budget.
    """
    budgets = config.get_generation_budgets()
    configured = budgets["personal_context_token_budget"]
    fixed_cost = estimate_tokens("\n\n".join(s for s in fixed_sections if s))
    headroom = max_tokens - fixed_cost - safety
    return max(0, min(configured, headroom))


def _enforce_token_ceiling(message: str, max_tokens: int) -> str:
    """Absolute last-resort guard: hard-truncate if somehow over the ceiling.

    With dynamic budgeting this should never fire, but it guarantees the
    contract that the prompt can never exceed ``max_tokens``.
    """
    if estimate_tokens(message) <= max_tokens:
        return message
    # Truncate by characters using the ~4 chars/token heuristic, then trim a
    # little extra to absorb tokenizer variance.
    approx_chars = max(0, int(max_tokens * 4 * 0.95))
    truncated = message[:approx_chars]
    return truncated + "\n\n[context truncated to honor token ceiling]"


def _build_resume_user_message(company: str, role: str, job_description: str) -> str:
    budgets = config.get_generation_budgets()
    max_tokens = budgets["resume_max_tokens"]
    safety = budgets["safety_margin_tokens"]

    master = _load_master_context()
    tone = get_tone_profile()
    strategy = get_customization_strategy(_infer_role_type(role))
    interview_block = get_interview_context(company=company, role=role)

    fixed_sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        interview_block or "",
        f"TONE PROFILE (write in this voice):\n{tone}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only.",
    ]
    personal_budget = _dynamic_personal_budget(fixed_sections, max_tokens, safety)
    personal, _diag = _build_personal_context_block(role, job_description, personal_budget)

    sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        personal,
    ]
    if interview_block:
        sections.append(interview_block)
    sections.extend([
        f"TONE PROFILE (write in this voice):\n{tone}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only.",
    ])
    return _enforce_token_ceiling("\n\n".join(s for s in sections if s), max_tokens)


def _build_cover_letter_user_message(company: str, role: str, job_description: str) -> str:
    budgets = config.get_generation_budgets()
    max_tokens = budgets["cover_letter_max_tokens"]
    safety = budgets["safety_margin_tokens"]

    master = _load_master_context()
    tone = get_tone_profile()
    strategy = get_customization_strategy(_infer_role_type(role))

    contact = config._cfg.get("contact", {})
    name = contact.get("name", "")
    phone = contact.get("phone", "")
    email = contact.get("email", "")
    linkedin = contact.get("linkedin", "")
    github = contact.get("github", "")
    contact_block = f"{name.upper()}\n\nphone: +1.{phone}\nemail: {email}\nlinkedin: {linkedin}\ngithub: {github}"
    interview_block = get_interview_context(company=company, role=role)

    instructions = (
        f"Now write the cover letter for {company}. Output the raw .txt content only.\n"
        "Use the resume, customization strategy, interview context, the general personal_context, the tone profile, and the job description.\n"
        "STRUCTURE: exactly 4 paragraphs. Do not merge them.\n"
        "\n"
        "EXPANSION RULE: After stating any technical fact, write 1–2 follow-up sentences explaining\n"
        "(a) what made it hard or risky, and (b) why it is directly relevant to the target role.\n"
        "Never drop a fact in a single clause and move on — every metric needs context.\n"
        "\n"
        "PARA 1 (80–100 words): Hook. Lead with one high-signal accomplishment from the resume that maps to this role,\n"
        "  then add two concrete sentences on why this company/role specifically (based on JD details, not generic praise).\n"
        "\n"
        "PARA 2 (150–170 words): Primary ownership story. Use one major example with concrete metrics,\n"
        "  constraints, and tradeoffs. Make the end-to-end ownership chain explicit and tie each fact to the target role.\n"
        "\n"
        "PARA 3 (150–170 words): Side projects. Use metrics from the master resume projects section.\n"
        "  Cover each project with 2 sentences (what it does + a specific metric or constraint\n"
        "  solved). Close with one sentence on what the projects together demonstrate.\n"
        "\n"
        "PARA 4 (60–80 words): Closer. One forward-looking sentence referencing the company's\n"
        "  specific scale or challenges from the JD. End with the exact phrase:\n"
        "  'Happy to walk through any of this in more detail.'\n"
        "\n"
        "Do not use: 'strong fit', 'I am prepared', 'my comprehensive experience', 'makes me a strong'."
    )

    fixed_sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        interview_block or "",
        f"TONE PROFILE (write in this voice):\n{tone}",
        f"CONTACT BLOCK (use this exactly as the file header, no address fields):\n{contact_block}",
        _COVER_LETTER_FORMAT_SPEC,
        instructions,
    ]
    personal_budget = _dynamic_personal_budget(fixed_sections, max_tokens, safety)
    personal, _diag = _build_personal_context_block(role, job_description, personal_budget)

    sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        personal,
    ]
    if interview_block:
        sections.append(interview_block)
    sections.extend([
        f"TONE PROFILE (write in this voice):\n{tone}",
        f"CONTACT BLOCK (use this exactly as the file header, no address fields):\n{contact_block}",
        _COVER_LETTER_FORMAT_SPEC,
        instructions,
    ])
    return _enforce_token_ceiling("\n\n".join(s for s in sections if s), max_tokens)


def _context_fallback(system: str, user: str, tool_name: str) -> str:
    """Return a packaged context block for Copilot/Claude to handle when no API key."""
    return "\n".join([
        f"═══ {tool_name.upper()} — CONTEXT PACKAGE ═══",
        "No openai_api_key found in config.json.",
        "Use the context below to write the output, then call save_resume_txt / save_cover_letter_txt,"
        " then call export_resume_pdf / export_cover_letter_pdf.",
        "",
        "── SYSTEM INSTRUCTIONS ──",
        system,
        "",
        "── USER CONTEXT ──",
        user,
    ])


def _extract_cover_letter_body(content: str) -> str:
    """Extract only the prose body paragraphs for LaTeX pipeline export."""
    text = content.strip()
    if not text:
        return ""

    lines = [ln.rstrip() for ln in text.splitlines()]

    # Start at salutation when present.
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("dear hiring manager"):
            start = i + 1
            break

    body_lines = lines[start:]

    # Stop before sign-off block.
    end = len(body_lines)
    for i, ln in enumerate(body_lines):
        low = ln.strip().lower()
        if low in {"kindest regards,", "regards,", "sincerely,"}:
            end = i
            break

    body = "\n".join(body_lines[:end]).strip()
    return body


def _sanitize_cover_letter_output(content: str) -> str:
    """Remove wrapper chatter so the saved file contains only the letter."""
    text = (content or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    while lines:
        first = lines[0].strip().lower()
        if not first:
            lines.pop(0)
            continue
        if first.startswith(("here is the cover letter", "cover letter in .txt format")):
            lines.pop(0)
            continue
        break

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(
        r"^Here is the cover letter in \.txt format, following the specified rules:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


# ── PUBLIC TOOLS ───────────────────────────────────────────────────────────────

def generate_resume(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
) -> str:
    """
    Generate a tailored resume for a specific company and role.

    If openai_api_key is configured in config.json, calls the OpenAI API directly
    (model: openai_model, default gpt-4o-mini), saves the .txt, exports a PDF, and
    returns the finished PDF path.

    If no API key is configured, returns a fully-structured context package with
    master resume, tone profile, customization strategy, and exact .txt format
    instructions so Copilot / Claude can write the content and call save_resume_txt
    + export_resume_pdf.

    Constraints the caller must respect:
    - All metrics and achievements must come verbatim from master resume (no invention).
    - Section headers must be ALL CAPS.
    - Bullets must use • (U+2022), not - or *.
    - Job header format: Title | Company, Location | Month YYYY - Month YYYY
    - Target length: 650–800 words (one tight page).
    """
    user_msg = _build_resume_user_message(company, role, job_description)
    client = _openai_client()

    if client is None:
        return _context_fallback(_RESUME_SYSTEM, user_msg, "generate_resume")

    # ── API call ──
    filename = output_filename or _safe_filename(company, role, "Resume")
    try:
        response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": _RESUME_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=2800,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}\n\nFalling back to context package:\n\n{_context_fallback(_RESUME_SYSTEM, user_msg, 'generate_resume')}"

    save_result = save_resume_txt(filename, content)

    try:
        from tools.export import export_resume_pdf
        pdf_result = export_resume_pdf(filename)
    except Exception as exc:
        pdf_result = f"⚠ PDF export failed: {exc}"

    usage = response.usage
    cost_note = ""
    if usage:
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output (as of 2025)
        est = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
        cost_note = f"\n  tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out / est ${est:.4f}"

    return "\n".join([
        f"✓ Resume generated for {role} @ {company}",
        f"  model:  {_model()}{cost_note}",
        f"  {save_result}",
        f"  {pdf_result}",
    ])


def generate_cover_letter(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
    export_pipeline: str = "html",
) -> str:
    """
    Generate a tailored cover letter for a specific company and role.

    If openai_api_key is configured in config.json, calls the OpenAI API directly,
    saves the .txt, exports a PDF, and returns the finished PDF path.

    If no API key is configured, returns a context package for Copilot / Claude to
    write the content.

    Hard constraints enforced in the prompt (the PDF template is fixed-size):
    - MAX 325 words in the letter body.
    - Exactly 4 paragraphs.
    - No date, no address block, no company name, no Re: line.
    - No bullets, no bold, no headers — prose only.
    - Salutation must be: Dear Hiring Manager,
    - Paragraph 4 is a short closer (1-2 sentences).
    """
    user_msg = _build_cover_letter_user_message(company, role, job_description)
    client = _openai_client()

    if client is None:
        return _context_fallback(_COVER_LETTER_SYSTEM, user_msg, "generate_cover_letter")

    # ── API call ──
    filename = output_filename or _safe_filename(company, role, "Cover Letter")
    try:
        response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": _COVER_LETTER_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=2000,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}\n\nFalling back to context package:\n\n{_context_fallback(_COVER_LETTER_SYSTEM, user_msg, 'generate_cover_letter')}"

    content = _sanitize_cover_letter_output(content)
    save_result = save_cover_letter_txt(filename, content)

    try:
        if export_pipeline == "latex":
            from tools.latex_export import generate_cover_letter_latex

            body = _extract_cover_letter_body(content)
            if not body:
                raise RuntimeError("Unable to extract cover letter body for LaTeX export")

            latex_pdf = generate_cover_letter_latex(body=body, company=company, role=role)
            pdf_result = f"✓ PDF exported (LaTeX): {latex_pdf}"
        else:
            from tools.export import export_cover_letter_pdf

            pdf_result = export_cover_letter_pdf(filename)
    except Exception as exc:
        pdf_result = f"⚠ PDF export failed: {exc}"

    usage = response.usage
    cost_note = ""
    if usage:
        est = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
        cost_note = f"\n  tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out / est ${est:.4f}"

    return "\n".join([
        f"✓ Cover letter generated for {role} @ {company}",
        f"  export pipeline: {export_pipeline}",
        f"  model:  {_model()}{cost_note}",
        f"  {save_result}",
        f"  {pdf_result}",
    ])


def preview_story_retrieval(role: str, job_description: str = "") -> str:
    """Preview which personal stories the retrieval layer would inject for a role.

    Runs the same local inverted-index retrieval used by resume/cover-letter
    generation and returns full diagnostics: library size, how many candidate
    stories were actually scored (vs the full library), relevance scores, token
    counts, the active token budget, and which stories were selected. Use this
    to tune relevance or verify the context stays within budget as the story
    library grows.

    Args:
        role:            Target role title.
        job_description: Optional JD text (improves relevance signal).

    Returns:
        Formatted diagnostics report.
    """
    budgets = config.get_generation_budgets()
    _selected, diag = retrieve_stories(
        role,
        job_description,
        path=config.PERSONAL_CONTEXT_FILE,
        token_budget=budgets["personal_context_token_budget"],
        max_stories=budgets["max_personal_stories"],
    )
    return diag.render()


def register(mcp) -> None:
    mcp.tool()(generate_resume)
    mcp.tool()(generate_cover_letter)
    mcp.tool()(preview_story_retrieval)
