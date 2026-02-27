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
from tools.tone import get_tone_profile
from tools.fitment import get_customization_strategy
from tools.resume import save_resume_txt, save_cover_letter_txt


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
   `EDUCATION`, `LEADERSHIP & COMMUNITY`.
3. Job header: `Title | Company, Location | Month YYYY - Month YYYY` (3 pipe-delimited parts).
4. Bullets MUST start with `•` (Unicode U+2022). Do NOT use `-` or `*`.
5. Contact block: labeled fields with lowercase label and colon — `phone:`, `email:`, `linkedin:`.
6. Separator lines: `──────────────────────────────────────────────────────────` (Unicode box-
   drawing em-dashes, same length every time).
7. Skills format: `Label: value, value, value` — colon after label, comma-separated values.
8. No hard line wrapping — let lines be as long as they need to be; the renderer wraps text.

### Target length
- Aim for 650–800 words total (one tight page in Courier New 9.2pt).
- 4–6 bullets per job, each 1–2 rendered lines.
- Skills section: 6–8 labeled rows.
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
address: 123 Street Name
city_state: City, ST 00000

Dear Hiring Manager,

[Paragraph 1]

[Paragraph 2]

[Paragraph 3]

[Paragraph 4]

Sincerely,
FULL NAME
```

### Critical rules — NON-NEGOTIABLE
1. MAX 400 WORDS in the letter body (everything from "Dear..." through the sign-off name).
   Count your words. If over, cut.
2. Exactly 4 body paragraphs — no more, no less:
   • Para 1 (60–80 words): Hook + role name + why this specific company.
   • Para 2 (100–130 words): Most relevant technical achievement with a real metric.
   • Para 3 (90–115 words): Second differentiator — leadership, AI innovation, or domain fit.
   • Para 4 (25–40 words): Short closer — reaffirm interest, invite next step.
3. NO date, NO company address, NO "Re:" line, NO address block in the body.
4. Start with the salutation: `Dear Hiring Manager,` (period, not comma, if you prefer formality).
5. NO bold, NO bullet points, NO headers inside the letter body — prose only.
6. No hard line wrapping — let lines be as long as needed.
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
""")

_COVER_LETTER_SYSTEM = textwrap.dedent("""\
    You are an expert cover letter writer. Produce a tailored one-page cover letter
    for the candidate described below.

    Output ONLY the raw cover letter text in the exact format specified — no
    preamble, no markdown fences, no commentary. The output will be saved directly
    to a .txt file and fed to a strict PDF parser.

    Write in the candidate's voice as defined by their tone profile. Be specific,
    metric-driven, and direct. Never be generic or sycophantic.
""")


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _openai_client():
    """Return an OpenAI client using the key from config, or None if not configured."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return None
    key = config._cfg.get("openai_api_key", "")
    if not key or key.startswith("sk-..."):
        return None
    return OpenAI(api_key=key)


def _model() -> str:
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
    prefix = name.title() if name else "Resume"
    return f"{prefix} Resume - {slug}.txt" if suffix == "Resume" else f"{prefix} Cover Letter - {slug}.txt"


def _build_resume_user_message(company: str, role: str, job_description: str) -> str:
    master = _load_master_context()
    tone = get_tone_profile()
    strategy = get_customization_strategy(_infer_role_type(role))
    return "\n\n".join([
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        f"TONE PROFILE (write in this voice):\n{tone}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only.",
    ])


def _build_cover_letter_user_message(company: str, role: str, job_description: str) -> str:
    master = _load_master_context()
    tone = get_tone_profile()
    return "\n\n".join([
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        f"TONE PROFILE (write in this voice):\n{tone}",
        _COVER_LETTER_FORMAT_SPEC,
        "Now write the cover letter. Output the raw .txt content only. Count words before finishing.",
    ])


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
            max_tokens=2000,
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
) -> str:
    """
    Generate a tailored cover letter for a specific company and role.

    If openai_api_key is configured in config.json, calls the OpenAI API directly,
    saves the .txt, exports a PDF, and returns the finished PDF path.

    If no API key is configured, returns a context package for Copilot / Claude to
    write the content.

    Hard constraints enforced in the prompt (the PDF template is fixed-size):
    - MAX 400 words in the letter body.
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
            temperature=0.4,
            max_tokens=800,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}\n\nFalling back to context package:\n\n{_context_fallback(_COVER_LETTER_SYSTEM, user_msg, 'generate_cover_letter')}"

    save_result = save_cover_letter_txt(filename, content)

    try:
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
        f"  model:  {_model()}{cost_note}",
        f"  {save_result}",
        f"  {pdf_result}",
    ])


def register(mcp) -> None:
    mcp.tool()(generate_resume)
    mcp.tool()(generate_cover_letter)
