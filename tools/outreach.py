"""
Outreach message drafting context tool — v4

draft_outreach_message(contact, company, context, message_type) packages:
  - Tone profile (Frank's voice)
  - Relevant personal context stories
  - Job hunt status for the company
  - Message-type-specific writing instructions

The AI uses this context to generate a ready-to-send message.
"""

from lib import config
from lib.io import _load_json
from tools.tone import get_tone_profile
from tools.context import get_personal_context
from tools.job_hunt import get_job_hunt_status
from tools.people import lookup_person_context


_MESSAGE_TYPE_INSTRUCTIONS = {
    "linkedin_followup": (
        "Write a short LinkedIn follow-up message (3–5 sentences max). "
        "The tone should be warm and direct — not sycophantic, not stiff. "
        "Reference what happened (screen, application, referral) without restating everything. "
        "End with a clear, low-pressure next step. "
        "Do NOT start with 'I hope this message finds you well' or any variation of that."
    ),
    "thank_you": (
        "Write a brief thank-you note (4–6 sentences). "
        "Be specific about one thing from the conversation that was genuinely interesting or useful. "
        "Do not be effusive — one genuine, specific observation beats three generic compliments. "
        "Reaffirm interest without desperation. "
        "If this is for a referral contact (not interviewer), acknowledge what they did for you specifically."
    ),
    "referral_ask": (
        "Write a referral request message. Be direct about what you're asking — "
        "don't bury the ask. Lead with the connection, then the ask, then give them "
        "a one-sentence reason why the role/company is a fit. "
        "Keep it short enough that they can respond in 30 seconds. "
        "Make it easy for them to say yes by being specific about what you need from them."
    ),
    "recruiter_nudge": (
        "Write a polite follow-up nudge to a recruiter or contact who hasn't responded. "
        "Keep it to 2–3 sentences. Don't apologize for following up. "
        "Restate your interest briefly and ask directly if there's an update. "
        "Tone: confident and easy, not anxious."
    ),
    "cold_outreach": (
        "Write a cold outreach message to a hiring manager or engineer at the company. "
        "Lead with the most relevant credential or project that's directly applicable to their work. "
        "Do not summarize your entire resume — pick one thing that earns the read. "
        "Be specific about why you're reaching out to them specifically, not just the company. "
        "End with a concrete but low-commitment ask (a 15-minute call, or just asking if they're hiring)."
    ),
}

_DEFAULT_INSTRUCTION = (
    "Write a professional, personable outreach message appropriate for the described context. "
    "Keep it concise. Avoid AI-sounding openers. Write in Frank's voice as defined by the tone profile."
)


def _detect_message_type(context_text: str) -> str:
    """Best-effort message type detection from context description."""
    cl = context_text.lower()
    if any(w in cl for w in ["thank", "grateful", "appreciate"]):
        return "thank_you"
    if any(w in cl for w in ["refer", "referral", "pass along", "put in a word"]):
        return "referral_ask"
    if any(w in cl for w in ["no response", "follow up", "following up", "nudge", "haven't heard"]):
        return "recruiter_nudge"
    if any(w in cl for w in ["cold", "don't know", "never met", "reached out to"]):
        return "cold_outreach"
    return "linkedin_followup"


def _get_company_status(company: str) -> str:
    """Pull the application status for a specific company from the tracker."""
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps = data.get("applications", [])
    match = next(
        (a for a in apps if a["company"].lower() == company.lower()), None
    )
    if not match:
        return f"No active application tracked for {company}."
    lines = [
        f"Company: {match['company']}",
        f"Role:    {match['role']}",
        f"Status:  {match['status']}",
    ]
    if match.get("contact"):
        lines.append(f"Contact: {match['contact']}")
    if match.get("next_steps"):
        lines.append(f"Next steps: {match['next_steps']}")
    if match.get("notes"):
        lines.append(f"Notes: {match['notes']}")
    return "\n".join(lines)


def draft_outreach_message(
    contact: str,
    company: str,
    context: str,
    message_type: str = "",
) -> str:
    """
    Package everything needed to draft an outreach message in Frank's voice.

    Args:
        contact:      Name of the person being messaged.
        company:      Company context (used to pull application status).
        context:      Free-text description of the situation
                      (e.g. "just completed phone screen with Maya, want to send thank-you").
        message_type: One of: linkedin_followup, thank_you, referral_ask,
                      recruiter_nudge, cold_outreach.
                      If omitted, auto-detected from context.

    Returns:
        Structured context string for the AI to use to write the message.
    """
    resolved_type = message_type.strip().lower() if message_type.strip() else _detect_message_type(context)
    writing_instructions = _MESSAGE_TYPE_INSTRUCTIONS.get(resolved_type, _DEFAULT_INSTRUCTION)

    tone_profile = get_tone_profile()
    personal_ctx = get_personal_context()
    company_status = _get_company_status(company)
    person_ctx = lookup_person_context(contact)

    sections = [
        "═══ OUTREACH MESSAGE CONTEXT ═══",
        f"To:           {contact}",
        f"Company:      {company}",
        f"Message type: {resolved_type}",
        f"Situation:    {context}",
    ]

    if person_ctx:
        sections += ["──── KNOWN CONTACT INFO ────", person_ctx]

    sections += [
        "──── WRITING INSTRUCTIONS ────",
        writing_instructions,
        "──── FORMATTING RULES ────",
        (
            "- Keep it short. If it can be 3 sentences, don't write 5.\n"
            "- No emoji.\n"
            "- No AI-sounding openers (no 'I hope this finds you well', 'I wanted to reach out', "
            "'I am excited to', 'I trust this email finds you', etc.)\n"
            "- Write like a person, not a cover letter generator.\n"
            "- If email format: provide Subject line + body. If LinkedIn/text: body only."
        ),
        "──── APPLICATION STATUS ────",
        company_status,
        "──── FRANK'S VOICE (tone profile) ────",
        tone_profile,
        "──── PERSONAL CONTEXT (for relevant stories if applicable) ────",
        personal_ctx,
        "──── TASK ────",
        (
            f"Using everything above, draft a {resolved_type.replace('_', ' ')} message "
            f"to {contact} at {company}. Write it ready to send — no placeholders, "
            "no [INSERT NAME], no notes to Frank about what to change. "
            "Just the message."
        ),
    ]

    return "\n\n".join(sections)


def register(mcp) -> None:
    mcp.tool()(draft_outreach_message)
