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
    "Keep it concise. Avoid AI-sounding openers. Write in the candidate's voice as defined by the tone profile."
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
    Package everything needed to draft an outreach message in the candidate's voice.

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
        "──── CANDIDATE'S VOICE (tone profile) ────",
        tone_profile,
        "──── PERSONAL CONTEXT (for relevant stories if applicable) ────",
        personal_ctx,
        "──── TASK ────",
        (
            f"Using everything above, draft a {resolved_type.replace('_', ' ')} message "
            f"to {contact} at {company}. Write it ready to send — no placeholders, "
            "no [INSERT NAME], no editorial notes to the sender about what to change. "
            "Just the message."
        ),
    ]

    return "\n\n".join(sections)


_CORPORATE_PHRASES = [
    "i hope this message finds you",
    "i wanted to reach out",
    "i am excited to",
    "i am passionate about",
    "i trust this email finds",
    "please do not hesitate",
    "as per my previous",
    "i am reaching out because",
    "synergy",
    "leverage",
    "circle back",
    "touch base",
    "moving forward",
    "at the end of the day",
    "going forward",
    "per our conversation",
]

_DESPERATION_SIGNALS = [
    "really need",
    "desperately",
    "any opportunity",
    "would love any",
    "even if it's",
    "willing to do anything",
    "i'll take whatever",
    "please consider",
    "i beg",
    "i just want a chance",
    "just give me",
]

_HEDGING_WORDS = [
    "sort of",
    "kind of",
    "maybe",
    "i think possibly",
    "i guess",
    "hopefully",
    "if that's okay",
    "i'm sorry to bother",
    "sorry for",
    "apologies for reaching",
]


def review_message(text: str) -> str:  # NOSONAR
    """
    Review an outreach message draft for tone, sentiment, and length issues.

    Checks for:
    - Corporate / AI-generated stiffness phrases
    - Desperation signals (red flags that undermine negotiating position)
    - Hedging language (undermines confidence)
    - Length (ideal: under 100 words for LinkedIn; under 200 for email)
    - Opener quality (first sentence is the make-or-break)

    Args:
        text: The message text to review.

    Returns:
        Structured review with flagged issues and recommendations.
    """
    lower = text.lower()
    word_count = len(text.split())
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    opener = sentences[0] if sentences else ""

    flags: list[str] = []
    warnings: list[str] = []

    # Corporate / stiff phrases
    found_corporate = [p for p in _CORPORATE_PHRASES if p in lower]
    if found_corporate:
        for p in found_corporate:
            flags.append(f"🔴  Corporate phrase: '{p}' — cut or rewrite naturally")

    # Desperation signals
    found_desperation = [p for p in _DESPERATION_SIGNALS if p in lower]
    if found_desperation:
        for p in found_desperation:
            flags.append(f"🔴  Desperation signal: '{p}' — this weakens your position")

    # Hedging
    found_hedging = [p for p in _HEDGING_WORDS if p in lower]
    if found_hedging:
        for p in found_hedging:
            flags.append(f"🟡  Hedging language: '{p}' — consider cutting")

    # Length
    if word_count > 200:
        warnings.append(f"🟡  Length: {word_count} words — email should be under 200; LinkedIn under 100")
    elif word_count > 100:
        warnings.append(f"ℹ   Length: {word_count} words — acceptable for email, long for LinkedIn")
    else:
        warnings.append(f"✓   Length: {word_count} words — good")

    # Opener check
    opener_lower = opener.lower()
    bad_openers = [
        "i hope", "my name is", "i am writing", "i wanted", "i am reaching",
        "i trust", "i'm excited", "i am excited",
    ]
    if any(opener_lower.startswith(b) for b in bad_openers):
        flags.append(f"🔴  Weak opener: '{opener[:80]}' — start with something specific or valuable")

    # Starts with 'I'
    if text.strip().startswith("I ") and not any(
        text.strip().startswith(f"I {w}") for w in ["built", "led", "shipped", "drove", "created", "launched", "spoke"]
    ):
        warnings.append("🟡  First word is 'I' — consider restructuring to lead with value or context")

    # Closing
    if not any(w in lower for w in ["?", "call", "chat", "connect", "open", "available", "thoughts"]):
        warnings.append("🟡  No clear call to action or question — add one")

    # Build output
    lines = [
        "═══ MESSAGE REVIEW ═══",
        f"Word count: {word_count}",
        "",
    ]

    if not flags and not [w for w in warnings if not w.startswith("✓")]:
        lines.append("✅  No major issues found. Message looks clean.")
    else:
        if flags:
            lines.append("ISSUES (fix before sending):")
            lines.extend(flags)
            lines.append("")
        if warnings:
            lines.append("NOTES:")
            lines.extend(warnings)
            lines.append("")

    lines += [
        "──── ORIGINAL TEXT ────",
        text,
    ]

    return "\n".join(lines)


def draft_reply(
    incoming_message: str,
    contact: str = "",
    company: str = "",
    intent: str = "",
) -> str:
    """Package context for replying to an incoming message (recruiter, HM, contact).

    Returns a context block bundling: the incoming text, the candidate's tone profile,
    relevant personal context, job-hunt status for the company (if any), known
    contact context, and tactical reply instructions. The AI uses this to draft
    a short, on-voice reply.

    Args:
        incoming_message: Verbatim text of the message received.
        contact:          Name of the sender (looked up via people DB if known).
        company:          Company they represent (for status pull).
        intent:           The candidate's intended response posture: 'accept',
                          'decline_polite', 'decline_compensation', 'request_info',
                          'delay', 'enthusiastic_yes', or free-form. Optional.

    Returns:
        A multi-section context package the AI fills in.
    """
    if not incoming_message or not incoming_message.strip():
        return "⚠ draft_reply: incoming_message is required"

    tone = get_tone_profile()
    pcontext = get_personal_context()
    status = get_job_hunt_status() if company else ""
    contact_ctx = lookup_person_context(contact) if contact else ""

    intent_instruction = {
        "accept": (
            "Posture: positive, decisive. Confirm the next step explicitly. "
            "If a time slot was offered, accept one or propose two alternatives. "
            "Do not over-explain enthusiasm."
        ),
        "decline_polite": (
            "Posture: warm decline. Be direct about not moving forward, leave the "
            "door open for future contact, do not invent a reason if you don't need one. "
            "Keep it under 4 sentences."
        ),
        "decline_compensation": (
            "Posture: decline citing compensation mismatch without disclosing target numbers. "
            "Phrase as 'the comp range we discussed is below where I need to be right now.' "
            "Offer to reconnect if the band changes."
        ),
        "request_info": (
            "Posture: ask one or two concrete questions before committing. "
            "Examples: total comp band, on-call expectations, remote policy, team scope. "
            "Pick what the incoming message left ambiguous."
        ),
        "delay": (
            "Posture: buy time without ghosting. Acknowledge receipt, name a specific "
            "follow-up window (e.g. 'I'll get back to you by end of week'), keep it short."
        ),
        "enthusiastic_yes": (
            "Posture: high-confidence yes. Mirror one specific thing they said back to them, "
            "confirm the next step, sign off."
        ),
    }.get(intent.strip().lower(), "") if intent else ""

    sections = [
        "──── INCOMING MESSAGE ────",
        incoming_message.strip(),
        "",
        "──── CANDIDATE'S TONE PROFILE ────",
        tone,
        "",
        "──── PERSONAL CONTEXT (use only if relevant) ────",
        pcontext,
    ]
    if status:
        sections += ["", "──── JOB HUNT STATUS FOR THIS COMPANY ────", status]
    if contact_ctx:
        sections += ["", "──── CONTACT CONTEXT ────", contact_ctx]
    sections += [
        "",
        "──── REPLY INSTRUCTIONS ────",
        "Match the incoming register. Keep the reply under 6 sentences unless the "
        "incoming message asks something substantive that needs more. "
        "Do not open with 'I hope this finds you well' or any variation. "
        "Do not use em dashes — use ellipses (...) for connective tissue. "
        "No emojis. Lead with the answer or the most important sentence, not framing.",
    ]
    if intent_instruction:
        sections += ["", "──── INTENT-SPECIFIC POSTURE ────", intent_instruction]
    return "\n".join(sections)


def register(mcp) -> None:
    mcp.tool()(draft_outreach_message)
    mcp.tool()(review_message)
    mcp.tool()(draft_reply)
