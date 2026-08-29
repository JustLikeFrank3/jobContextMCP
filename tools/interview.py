from lib import config
from lib.helpers import normalize_for_match, sanitize_filename
from lib.io import _read, _load_master_context
from tools.interviews import get_company_signal_context, get_interview_context


def get_interview_quick_reference() -> str:
    """Return the full interview day quick reference: algorithm pattern cheat sheets, system design 5-step framework, testing talking points, and pre-interview checklist."""
    return _read(config.get_active_quick_reference_path())


def get_leetcode_cheatsheet(section: str = "") -> str:
    """Return the LeetCode algorithm cheatsheet. Pass a section name (e.g. 'trees', 'graphs', 'dynamic programming') to get just that section, or leave blank for the full 1400-line reference."""
    content = _read(config.get_active_leetcode_cheatsheet_path())
    if not section:
        return content

    lines = content.split("\n")
    result = []
    inside = False
    target = section.lower()

    for line in lines:
        stripped = line.lstrip("#").strip().lower()
        is_header = line.startswith("#")

        if is_header and target in stripped:
            inside = True
        elif is_header and inside and target not in stripped:
            if line.startswith("# ") or (line.startswith("## ") and target not in stripped):
                break

        if inside:
            result.append(line)

    if result:
        return "\n".join(result)
    return f"Section '{section}' not found. Returning full cheatsheet.\n\n{content}"


def generate_interview_prep_context(
    company: str,
    role: str,
    stage: str = "phone_screen",
    job_description: str = "",
) -> str:
    """Bundle the candidate's master resume, quick reference, and live workspace signal (known interviewers, scheduled interviews, application events, prior in-room notes) into a structured context prompt for interview prep. Specify company, role, stage (phone_screen, technical, behavioral, system_design), and optional job description. Returns a prompt instructing the AI to generate top talking points, STAR responses, technical topics, smart questions, and confidence anchors."""
    master = _load_master_context()
    quick_ref = _read(config.get_active_quick_reference_path())

    desc_block = f"\n──── JOB DESCRIPTION ────\n{job_description}" if job_description else ""

    # Server-side, not left to the client: a foreign agent picks tools from
    # descriptions alone and never queried the people domain, so the prep it
    # generated named no interviewer despite one being on the calendar.
    signal = get_company_signal_context(company, role)
    signal_block = f"{signal}\n\n" if signal else ""
    prior = get_interview_context(company=company, role=role)
    prior_block = f"{prior}\n\n" if prior else ""
    interviewer_line = (
        "  0. Open with who the candidate is meeting — name, role, background —\n"
        "     and tailor everything below to them. Generic 'hiring manager'\n"
        "     phrasing when the workspace signal names the interviewer is a\n"
        "     failure.\n"
        if signal
        else ""
    )

    return (
        f"═══ INTERVIEW PREP CONTEXT ═══\n"
        f"Company: {company}\n"
        f"Role:    {role}\n"
        f"Stage:   {stage}\n"
        f"{desc_block}\n\n"
        f"{signal_block}"
        f"{prior_block}"
        f"──── CANDIDATE'S MASTER RESUME ────\n{master}\n\n"
        f"──── QUICK REFERENCE / STAR STORIES ────\n{quick_ref}\n\n"
        f"Use the above to produce:\n"
        f"{interviewer_line}"
        f"  1. Top 5 things the candidate must communicate for THIS role/stage\n"
        f"  2. Anticipated questions + suggested STAR responses\n"
        f"  3. Technical topics to review (if applicable)\n"
        f"  4. Smart questions for the candidate to ask the interviewer\n"
        f"  5. Any gaps to proactively address\n"
        f"  6. Confidence anchors — the candidate's strongest achievements relevant here\n"
    )


def get_existing_prep_file(company: str) -> str:
    """Find and return all existing interview prep files for a given company — searches across both the Resume 2025 and LeetCode folders for files containing the company name and prep/interview/call/assessment keywords."""
    _ws = config.get_active_workspace_folder()
    search_roots = [_ws, config.get_active_leetcode_folder(), config.get_active_interview_prep_dir()]
    # Punctuation-insensitive company match: save_interview_prep slugs the
    # company ('Mercedes-Benz USA' → MERCEDES_BENZ_USA_…), so a raw substring
    # test never found the files the sibling write path just confirmed saving.
    company_key = normalize_for_match(company)
    seen: set = set()
    matches = []
    for root in search_roots:
        for f in sorted(root.rglob("*")):
            if (
                f not in seen
                and f.suffix in (".txt", ".md")
                and company_key
                and company_key in normalize_for_match(f.name)
                and any(kw in f.name.lower() for kw in ("prep", "interview", "call", "assessment"))
            ):
                matches.append(f)
                seen.add(f)

    if not matches:
        return f"No existing prep files found for '{company}'."

    lines = [f"Found {len(matches)} prep file(s) for '{company}':\n"]
    for m in matches:
        lines.append(f"──── {m.name} ────")
        lines.append(_read(m))
        lines.append("")
    return "\n".join(lines)


def save_interview_prep(company: str, content: str, filename: str = "") -> str:
    """Save a generated interview prep document to the 08-Interview-Prep-Docs folder as a .md file. Filename defaults to {COMPANY}_INTERVIEW_PREP.md; a custom filename gets the company slug prefixed unless it already names the company, so get_prep for the same company always finds it. Always use this tool instead of creating files directly."""
    slug = company.upper().replace(" ", "_").replace("-", "_")
    if not filename:
        filename = f"{slug}_INTERVIEW_PREP.md"
    elif normalize_for_match(company) not in normalize_for_match(filename):
        # Round-trip guarantee: get_existing_prep_file matches on the company
        # name. A client-chosen name like 'MBUSA_…' saved fine but was
        # unretrievable — a success confirmation on an invisible write.
        filename = f"{slug}_{filename}"
    filename = sanitize_filename(filename)
    if not filename.endswith(".md"):
        filename += ".md"

    # Strip trailing whitespace per line; preserve intentional blank lines
    cleaned = "\n".join(line.rstrip() for line in content.splitlines())

    target = config.get_active_interview_prep_dir()
    target.mkdir(parents=True, exist_ok=True)
    dest = target / filename
    dest.write_text(cleaned, encoding="utf-8")
    return f"✓ Saved interview prep: {dest.name}"


def register(mcp) -> None:
    mcp.tool()(get_interview_quick_reference)
    mcp.tool()(get_leetcode_cheatsheet)
    mcp.tool()(generate_interview_prep_context)
    mcp.tool()(get_existing_prep_file)
    mcp.tool()(save_interview_prep)
