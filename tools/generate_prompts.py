"""Format specifications, system prompts, and tag constants for resume/cover-letter generation.

Extracted from tools/generate.py to keep that module focused on generation logic.
All symbols here are imported back into generate.py so external callers are unaffected.
"""

import textwrap

# ---------------------------------------------------------------------------
# Hook tag sets used by story retrieval / filtering
# ---------------------------------------------------------------------------

COVER_LETTER_HOOK_TAGS = {
    "identity", "personal", "personal_connection",
    "brand-connection", "brand_connection",
    "cover-letter-anchor", "cover_letter_anchor", "cover_letter_hook",
    "why-this-company", "non_linear_path", "character", "storytelling",
    "music", "film", "creativity", "entrepreneurship", "writing", "journalism",
    "family", "childhood", "travel", "hospitality", "bar_management",
    "bar-management", "performing_arts", "fanboy", "loyalty",
}

COMPANY_HOOK_TAGS = {
    "brand-connection", "brand_connection", "personal_connection",
    "personal-connection", "cover-letter-anchor", "cover_letter_anchor",
    "cover_letter_hook", "cover-letter-hook", "why-this-company",
    "why_this_company", "childhood", "fanboy", "loyalty",
}

# ---------------------------------------------------------------------------
# Format specifications (fed verbatim into generation prompts)
# ---------------------------------------------------------------------------

RESUME_FORMAT_SPEC = """
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

COVER_LETTER_FORMAT_SPEC = """
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
1. TARGET 380–430 WORDS in the letter body (everything from "Dear..." through the sign-off name).
   The page is fixed-size and runs short below this; aim for a full page. Reach the count with
   substance (a second project, a real constraint, a verbatim metric), never with filler or
   restated claims. Over 460 is overflow; cut.
2. Exactly 4 body paragraphs, no more, no less. The word ranges below are guidance, not quotas:
   • Para 1: Hook + role name + why this specific company. Be specific; name something real
     about the company, not generic praise. IMPORTANT: If the job description contains a
     "CRITICAL FRAMING CONTEXT" or "KEY STORIES TO SURFACE" section, Para 1 MUST use the framing
     angle specified there as the hook (personal background, fan identity, industry connection),
     not a generic technical achievement opening. This paragraph does not need a metric.
   • Para 2: Primary professional ownership story. CRITICAL: If the job description contains
     explicit framing instructions ("CRITICAL FRAMING CONTEXT", "KEY STORIES TO SURFACE", or
     similar), those take absolute priority over the defaults below.
     DEFAULT (when no framing override is present): Cover end-to-end system ownership
     (data layer through presentation layer) with specific metrics from the master resume,
     infrastructure migrations, and any verbatim manager quotes from the STAR stories. Make the
     ownership chain explicit; no layer delegated. Do NOT list version numbers (Java 21,
     Spring Boot 3.5.4, Angular 6→18); they are implementation details, not achievements.
   • Para 3: Cover THREE distinct artifacts from the master resume to show range and fill the
     page. Lead with whatever is the STRONGEST match to this specific job description (the AI/RAG
     tooling, a side project, or performance work) and give it two sentences with verbatim
     metrics. Then add two more concrete artifacts, one sentence each, each carrying a real metric
     verbatim from the master resume (for example the LiveVox latency work: 2.8ms web / 12.7ms
     iOS round-trip audio latency measured from microphone input to speaker output, 98% SLA). Close with one sentence on what they demonstrate together. Do not pad;
     every sentence carries a distinct fact.
   • Para 4: Closer. State the fit directly in the candidate's own words, then invite a conversation.
     Short but not dismissive. Write the invite in the candidate's voice; do not paste a stock closing line.
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
       - "thank you for considering"
       - "thank you for your time"
       - "I hope to hear from you"
       - any variant of the above
   • ABSOLUTELY NO em dashes (—) or double hyphens (--) anywhere in the letter body.
     They read as AI-generated. Rewrite with semicolons, commas, parentheses, or
     new sentences. Zero exceptions.
   • The opener is declarative and specific. It may lead with a human throughline (a story, a
     belief, a personal thread) drawn from the framing context or tone samples; it does not have
     to open with an accomplishment and does not need a metric.
   • Para 4 (the closer): make a direct statement about fit, then invite a conversation, in
     the candidate's own voice. Do NOT reuse a fixed closing sentence; write a fresh invite that
     matches the tone samples. Never end with "I look forward to hearing from you" or similar boilerplate.
   • No sycophantic language anywhere. Confidence, not deference.
   • The ownership paragraphs (2 and 3) must be metric-anchored. The opener and closer may carry
     the human throughline without a metric; do not stuff numbers into every sentence.
8. CLOSING: Use "Kindest Regards," (not "Sincerely"). Sign the name in Title Case — NOT all
   caps. Example: "Jane Smith" not "JANE SMITH".
"""

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

RESUME_SYSTEM = textwrap.dedent("""\
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
    from the master resume, except GitHub clone/view traffic which must come from
    the GITHUB PORTFOLIO METRICS block when present.

    Volatile portfolio metrics rule: if the prompt includes a GITHUB PORTFOLIO
    METRICS block, use those clone/view numbers instead of any stale clone counts
    embedded in the master resume. If the block is absent, omit clone/view counts
    rather than guessing.

    Bullets must be specific and metric-driven. Generic bullets like "improved
    performance" or "collaborated with teams" are not acceptable — every bullet
    must say what was built, how, and what measurable result it produced.
""")

COVER_LETTER_SYSTEM = textwrap.dedent("""\
    You are an expert cover letter writer. Produce a tailored one-page cover letter
    for the candidate described below.

    Output ONLY the raw cover letter text in the exact format specified — no
    preamble, no markdown fences, no commentary. The output will be saved directly
    to a .txt file and fed to a strict PDF parser.

    Write in the candidate's voice as defined by their tone profile. The tone
    samples are your ground truth. Study them and match their rhythm, register,
    and sentence shapes above any structural rule below. If a formatting rule
    fights the voice in the samples, keep the voice.

    Voice characteristics to enforce:
    - Direct, declarative, confident without being boastful.
    - The opener may lead with a human throughline (a story, a stated belief, a
      personal thread) rather than an accomplishment, if that is how the samples
      read. The opener does not need a metric.
    - Metrics live in the ownership paragraphs; every claim there is specific and
      uses numbers verbatim from the master resume. Do not stuff a metric into
      every sentence, and do not pad to hit a length.
    - Conversational but not casual; no filler phrases, no corporate speak.
    - A side project earns a place only when it is the strongest match to the job
      description, not as a mandatory section. Use metrics verbatim from the
            master resume when it does, except GitHub clone/view traffic which must
            come from the GITHUB PORTFOLIO METRICS block when present.

        Volatile portfolio metrics rule: if the prompt includes a GITHUB PORTFOLIO
        METRICS block, use those clone/view numbers instead of any stale clone counts
        embedded in the master resume. If the block is absent, omit clone/view counts
        rather than guessing.

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
