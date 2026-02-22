"""
PDF export tool — v4

export_resume_pdf(filename, footer_tag?, output_filename?)
    Reads a .txt resume from 01-Current-Optimized/, parses it,
    renders via resume.html template, and writes a PDF to 03-Resume-PDFs/.

export_cover_letter_pdf(filename, output_filename?)
    Reads a .txt cover letter from 02-Cover-Letters/, parses it,
    renders via cover_letter.html template, and writes a PDF to 03-Resume-PDFs/.
"""

import re
import pathlib

from jinja2 import Environment, FileSystemLoader
import weasyprint

from lib import config

# ── PATHS ────────────────────────────────────────────────────────────────

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"

_CONTACT_DEFAULTS = {
    "phone": "305-490-1262",
    "email": "frankvmacbride@gmail.com",
    "linkedin": "www.linkedin.com/in/frankvmacbride",
    "location": "Atlanta, GA",
    "address": "4784 Jamerson Forest Cir",
    "city_state": "Marietta, GA 30066",
}

# ── HELPERS ──────────────────────────────────────────────────────────────

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_WORD_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
    re.I,
)
_PHONE_RE = re.compile(r"[\+]?[\d][\d\s\-\.\(\)]{8,}")
_EMAIL_RE = re.compile(r"[\w\.\+\-]+@[\w\.\-]+\.\w+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+", re.I)

_SECTION_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 &/\(\)\-]{3,}$")


def _strip_txt_wrapper(text: str) -> str:
    """Remove the ```plaintext ... ``` wrapper if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first line (```plaintext or similar) and last (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner)
    return text


def _is_bullet(line: str) -> bool:
    return bool(line) and line[0] in "•-*"


def _is_section_header(line: str) -> bool:
    s = line.strip()
    if not s or _is_bullet(s):
        return False
    # Strip a trailing parenthetical note, e.g. "PERSONAL PROJECTS (Post-GM, 2026)" → "PERSONAL PROJECTS"
    test_s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    if not _SECTION_HEADER_RE.match(test_s):
        return False
    # Only treat as a section header if it maps to a known section type.
    # This prevents names ("FRANK VLADMIR MACBRIDE III"), job titles
    # ("SOFTWARE ENGINEER", "TECHNICAL SPECIALIST"), and other all-caps
    # lines from being misidentified as section breaks.
    return _classify_section(test_s) != "text"


def _clean_bullet(line: str) -> str:
    return re.sub(r"^[•\-\*]\s*", "", line.strip())


def _is_date_line(line: str) -> bool:
    return bool(_YEAR_RE.search(line)) and len(line) < 85


def _is_group_label(line: str) -> bool:
    s = line.strip()
    return (
        not _is_bullet(s)
        and s.endswith(":")
        and 3 < len(s) < 55
        and not _YEAR_RE.search(s)
    )


def _join_continuations(lines: list[str]) -> list[str]:
    """Join word-wrapped continuation lines (starting with whitespace) to their parent."""
    result: list[str] = []
    for line in lines:
        if line and line[0] == " " and result:
            # Append to the last non-blank line in result
            for i in range(len(result) - 1, -1, -1):
                if result[i].strip():
                    result[i] = result[i].rstrip() + " " + line.strip()
                    break
            else:
                result.append(line)
        else:
            result.append(line)
    return result


def _strip_separator_lines(lines: list[str]) -> list[str]:
    """Remove visual separator lines (─────── or --- or ***)."""
    return [l for l in lines if not re.match(r"^[-─*=]{3,}\s*$", l.strip())]


# ── CONTACT EXTRACTION ───────────────────────────────────────────────────

def _extract_contact(lines: list[str]) -> dict:
    contact = dict(_CONTACT_DEFAULTS)
    for line in lines:
        m = _PHONE_RE.search(line)
        if m and not contact.get("_phone_found"):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) >= 10:
                contact["phone"] = m.group(0).strip().lstrip("+").strip()
                contact["_phone_found"] = True
        m = _EMAIL_RE.search(line)
        if m:
            contact["email"] = m.group(0).strip()
        m = _LINKEDIN_RE.search(line)
        if m:
            val = m.group(0)
            val = re.sub(r"^https?://", "", val)
            contact["linkedin"] = val
    contact.pop("_phone_found", None)
    return contact


# ── SKIP APPLICATION MATERIALS BLOCK ─────────────────────────────────────

def _strip_metadata_blocks(lines: list[str]) -> list[str]:
    """Remove ---- ... ---- blocks that contain 'APPLICATION MATERIALS'."""
    result = []
    in_block = False
    dash_re = re.compile(r"^-{5,}")
    pending: list[str] = []

    for line in lines:
        if dash_re.match(line.strip()):
            if in_block:
                in_block = False
                pending = []
            else:
                pending = []
                in_block = True
        elif in_block:
            if "APPLICATION MATERIALS" in line.upper():
                # confirmed metadata block — discard until closing dashes
                pending = []
                continue
            pending.append(line)
        else:
            result.append(line)

    return result


# ── SECTION SPLITTER ──────────────────────────────────────────────────────

def _split_sections(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """
    Returns (pre_section_lines, [(section_title, content_lines), ...]).
    pre_section_lines = everything before the first section header.
    """
    pre: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_section_header(stripped):
            if current_title is not None:
                sections.append((current_title, current_lines))
            elif current_lines or (not stripped):
                pre.extend(current_lines)
            else:
                pre.extend(current_lines)
            current_title = stripped
            current_lines = []
        else:
            if current_title is None:
                pre.append(line)
            else:
                current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, current_lines))

    return pre, sections


# ── HEADER PARSING ─────────────────────────────────────────────────────────

def _parse_header(pre_lines: list[str], contact: dict) -> tuple[str, str, str]:
    """Returns (name, tagline, synopsis)."""
    name_lines: list[str] = []
    tagline: str = ""
    synopsis_lines: list[str] = []
    in_synopsis = False

    for line in pre_lines:
        s = line.strip()
        if not s:
            if name_lines and not in_synopsis:
                in_synopsis = True
            continue
        # Skip lines that look like contact info or separators
        if (
            _EMAIL_RE.search(s)
            or _PHONE_RE.search(s)
            or _LINKEDIN_RE.search(s)
            or s.startswith("---")
            or re.match(r"^[A-Z][a-z]+:", s)  # "Phone:", "Email:", etc.
        ):
            continue
        if in_synopsis:
            # Detect tagline: pipe-separated keyword line (role | skill • skill)
            if not tagline and "|" in s and ("•" in s or s.count("|") >= 1) and len(s.split()) <= 20:
                tagline = s
            else:
                synopsis_lines.append(s)
        elif not name_lines or (len(s) > 6 and s.isupper() and "," not in s and "@" not in s):
            # FRANK V. MACBRIDE III — is it a name or title?
            if name_lines and re.match(r"^[A-Z ]+$", s) and len(s) > 10:
                # could be subtitle like "SOFTWARE ENGINEER" — stop here
                pass
            else:
                name_lines.append(s)
        else:
            synopsis_lines.append(s)

    name = " ".join(name_lines).strip().upper()
    synopsis = " ".join(synopsis_lines).strip()
    return name, tagline, synopsis


# ── SKILLS ────────────────────────────────────────────────────────────────

def _parse_skills_section(lines: list[str]) -> dict:
    items: list[dict] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        s = _clean_bullet(s) if _is_bullet(s) else s
        # "Label: value" or "Label (extra): value"
        m = re.match(r"^([A-Za-z][A-Za-z0-9 &/\(\)_\-]+?):\s+(.+)$", s)
        if m:
            items.append({"label": m.group(1).strip(), "value": m.group(2).strip()})
        else:
            # plain line — treat as unlabeled item
            items.append({"label": "", "value": s})
    return {"type": "skills", "items": items}


# ── EXPERIENCE ────────────────────────────────────────────────────────────

def _is_date_part(s: str) -> bool:
    """True if s looks like a date range — no length limit."""
    return bool(_YEAR_RE.search(s)) and bool(_DATE_WORD_RE.search(s) or "\u2013" in s or "\u2014" in s or "-" in s)


def _finalize_job(job: dict) -> None:
    """Resolve accumulated header_lines into title/company/dates."""
    if job.get("_done"):
        return
    job["_done"] = True
    hlines = job.pop("_hlines", [])
    if not hlines:
        return

    # Single pipe-separated line
    if len(hlines) == 1 and " | " in hlines[0]:
        parts = [p.strip() for p in hlines[0].split(" | ")]
        last_is_date = _is_date_part(parts[-1])
        if len(parts) >= 3 and last_is_date:
            job["title"] = parts[0]
            job["company"] = parts[1]
            job["dates"] = parts[-1]
            return
        if len(parts) == 2 and last_is_date:
            # "Company | Dates" — title already set by new_job()
            if not job["company"]:
                job["company"] = parts[0]
            if not job["dates"]:
                job["dates"] = parts[-1]
            return
        if len(parts) == 2:
            # "Title | Level" — treat as extended title if title not yet set
            if not job["title"]:
                job["title"] = hlines[0]
            else:
                job["company"] = parts[1]
            return

    # Multi-line format
    for h in hlines:
        h = h.strip()
        if not h:
            continue
        # Handle "Company, Location | Date Range" on a single line
        if " | " in h and not job["company"]:
            pipe_parts = [p.strip() for p in h.split(" | ", 1)]
            if len(pipe_parts) == 2 and _is_date_line(pipe_parts[1]):
                job["company"] = pipe_parts[0]
                if not job["dates"]:
                    job["dates"] = pipe_parts[1]
                continue
        if (_is_date_line(h) and (_DATE_WORD_RE.search(h) or "–" in h or "-" in h)) and not job["dates"]:
            job["dates"] = h
        elif not job["title"]:
            job["title"] = h
        elif not job["company"]:
            job["company"] = h
        else:
            # Extra header line — append to company
            job["company"] += " " + h


def _parse_experience_section(lines: list[str]) -> dict:
    jobs: list[dict] = []
    cur: dict | None = None
    cur_group: dict | None = None
    had_bullets = False
    after_blank = False   # set True after a blank line; clears on next non-blank

    def flush_group() -> None:
        nonlocal cur_group
        if cur_group is not None and cur is not None:
            if cur_group["label"]:
                cur["groups"].append(cur_group)
            else:
                cur["bullets"].extend(cur_group["bullets"])
        cur_group = None

    def new_job(first_line: str) -> None:
        nonlocal cur, had_bullets, after_blank
        flush_group()
        if cur is not None:
            _finalize_job(cur)
        c = {
            "title": "", "company": "", "dates": "",
            "groups": [], "bullets": [],
            "_hlines": [first_line], "_done": False,
        }
        if " | " in first_line:
            parts = [p.strip() for p in first_line.split(" | ")]
            last = parts[-1]
            if len(parts) >= 3 and _is_date_part(last):
                c["title"] = parts[0]
                c["company"] = " | ".join(parts[1:-1])
                c["dates"] = last
                c["_hlines"] = []
                c["_done"] = True
            elif len(parts) == 2 and _is_date_part(last):
                c["company"] = parts[0]
                c["dates"] = last
                c["_hlines"] = []
                c["_done"] = True
            else:
                # "Title | Level" — company/dates come on the next line(s)
                c["title"] = first_line
                c["_hlines"] = []
        cur = c
        had_bullets = False
        after_blank = False
        jobs.append(cur)

    for raw in lines:
        line = raw.strip()

        # ── blank line ────────────────────────────────────────────────────
        if not line:
            if cur is not None:
                after_blank = True
            continue

        # ── explicit bullet (•, -, *) ─────────────────────────────────────
        if _is_bullet(line):
            after_blank = False
            bullet = _clean_bullet(line)
            if cur is None:
                continue
            if not cur.get("_done"):
                _finalize_job(cur)
            if cur_group is None:
                cur_group = {"label": "", "bullets": []}
            cur_group["bullets"].append(bullet)
            had_bullets = True

        # ── group label ("Cloud & Infrastructure:") ───────────────────────
        elif _is_group_label(line):
            after_blank = False
            if cur is None:
                continue
            if not cur.get("_done"):
                _finalize_job(cur)
            flush_group()
            cur_group = {"label": line.rstrip(":"), "bullets": []}
            had_bullets = False

        # ── start a new job? ──────────────────────────────────────────────
        # No current job yet, OR we just crossed a blank line after content.
        elif cur is None or after_blank:
            new_job(line)

        # ── accumulate header lines or implicit plain-text bullet ─────────
        else:
            after_blank = False
            if not cur.get("_done"):
                cur["_hlines"].append(line)
                # Finalize when last pipe-segment looks like a date range
                check = line.rsplit(" | ", 1)[-1].strip()
                if _is_date_part(check):
                    _finalize_job(cur)
            else:
                # Header is done; plain-text lines without bullet chars are
                # implicit bullets (common in MCP-saved .txt resumes).
                if cur_group is None:
                    cur_group = {"label": "", "bullets": []}
                cur_group["bullets"].append(line)
                had_bullets = True

    flush_group()
    if cur is not None:
        _finalize_job(cur)

    return {"type": "experience", "jobs": jobs}


# ── EDUCATION ─────────────────────────────────────────────────────────────

def _parse_education_section(lines: list[str]) -> dict:
    degree = school = year = ""
    detail_lines: list[str] = []
    clean_lines = [l.strip() for l in lines if l.strip()]
    for line in clean_lines:
        # Handle compact pipe format: "Degree | School | Year" or "Degree | School, City | Year"
        if " | " in line and not degree:
            parts = [p.strip() for p in line.split(" | ")]
            degree = parts[0]
            if len(parts) >= 3:
                school = parts[1]
                year   = parts[2]
            elif len(parts) == 2:
                if _YEAR_RE.search(parts[1]):
                    year = parts[1]
                else:
                    school = parts[1]
            continue
        if not degree:
            degree = line
        elif not school:
            school = line
        elif not year and _YEAR_RE.search(line) and len(line) < 60:
            year = line
        else:
            detail_lines.append(line)
    # Combine year into school display if we have it separately
    if year and school and year not in school:
        school = f"{school} | {year}"
    elif year and not school:
        school = year
    return {"type": "education", "degree": degree, "school": school, "details": detail_lines}


# ── PROJECTS ──────────────────────────────────────────────────────────────

def _parse_projects_section(lines: list[str]) -> dict:
    projects: list[dict] = []
    cur_proj: dict | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _is_bullet(line):
            if cur_proj is None:
                cur_proj = {"name": "Project", "bullets": []}
                projects.append(cur_proj)
            cur_proj["bullets"].append(_clean_bullet(line))
        else:
            # Non-bullet line → new project heading
            # If previous project has no bullets yet, just update its name
            if cur_proj is not None and not cur_proj["bullets"]:
                cur_proj["name"] += " " + line
            else:
                cur_proj = {"name": line, "bullets": []}
                projects.append(cur_proj)

    return {"type": "projects", "projects": projects}


# ── LEADERSHIP ────────────────────────────────────────────────────────────

def _parse_leadership_section(lines: list[str]) -> dict:
    items: list[dict] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        line = _clean_bullet(line) if _is_bullet(line) else line
        # "Bold Label: rest of text"
        m = re.match(r"^([A-Z][A-Za-z0-9 \(\)&]+?):\s+(.+)$", line)
        if m:
            items.append({"label": m.group(1).strip(), "value": m.group(2).strip()})
        else:
            items.append({"label": "", "value": line})
    return {"type": "leadership", "items": items}


# ── SECTION TYPE ROUTER ────────────────────────────────────────────────────

def _classify_section(title: str) -> str:
    t = title.upper()
    # Note: do NOT include "TECHNICAL" alone — "TECHNICAL SPECIALIST" is a job
    # title inside an experience section, not a skills section header.
    if any(k in t for k in ("SKILL", "PROFICIEN", "TECH STACK")):
        return "skills"
    if "EXPERIENCE" in t or "EMPLOYMENT" in t:
        return "experience"
    if "EDUCATION" in t:
        return "education"
    if "PROJECT" in t:
        return "projects"
    if "LEADERSHIP" in t or "ADDITIONAL" in t or "ACHIEVEMENT" in t or "CERTIFICATION" in t:
        return "leadership"
    if "SYNOPSIS" in t or "SUMMARY" in t or "OBJECTIVE" in t:
        return "synopsis_section"
    return "text"


# ── FOOTER TAG EXTRACTION ─────────────────────────────────────────────────

def _derive_footer_tag(filename: str) -> str:
    """Best-effort: extract the role type from filename for the </ROLE> footer."""
    name = pathlib.Path(filename).stem
    lower = name.lower()
    if "software engineer" in lower or "swe" in lower:
        return "SOFTWARE ENGINEER"
    if "full stack" in lower or "full-stack" in lower:
        return "FULL STACK ENGINEER"
    if "backend" in lower:
        return "BACKEND ENGINEER"
    if "frontend" in lower or "front-end" in lower:
        return "FRONTEND ENGINEER"
    if "data engineer" in lower:
        return "DATA ENGINEER"
    if "devops" in lower or "sre" in lower:
        return "DEVOPS ENGINEER"
    return "SOFTWARE ENGINEER"


# ── NAME PARSE FOR COVER LETTER ───────────────────────────────────────────

def _parse_name_parts(name: str) -> dict:
    """
    Split "FRANK V. MACBRIDE III" into sidebar name components.
    Returns: {name_line1, name_line2, name_last, name_suffix}
    """
    # Remove surrounding < > if present
    name = re.sub(r"[<>]", "", name).strip().upper()
    parts = name.split()

    suffix = ""
    if parts and parts[-1] in ("III", "II", "IV", "JR", "JR.", "SR", "SR."):
        suffix = parts.pop()

    if len(parts) == 1:
        return {"name_line1": parts[0], "name_line2": "", "name_last": "", "name_suffix": suffix}
    if len(parts) == 2:
        return {"name_line1": parts[0], "name_line2": "", "name_last": parts[1], "name_suffix": suffix}
    # 3+ parts: first, middle, last
    return {
        "name_line1": parts[0],
        "name_line2": " ".join(parts[1:-1]),
        "name_last": parts[-1],
        "name_suffix": suffix,
    }


# ── MAIN RESUME PARSER ─────────────────────────────────────────────────────

def _parse_resume_txt(text: str) -> dict:
    text = _strip_txt_wrapper(text)
    all_lines = text.splitlines()
    all_lines = _strip_metadata_blocks(all_lines)
    # Fix fixed-width line wrapping: rejoin continuation lines, then drop separators.
    all_lines = _join_continuations(all_lines)
    all_lines = _strip_separator_lines(all_lines)

    contact = _extract_contact(all_lines)
    pre_lines, raw_sections = _split_sections(all_lines)
    name, tagline, synopsis = _parse_header(pre_lines, contact)

    sections: list[dict] = []
    for title, content_lines in raw_sections:
        kind = _classify_section(title)

        if kind == "synopsis_section":
            # Append to synopsis if we didn't find one in the header
            extra = " ".join(l.strip() for l in content_lines if l.strip())
            if not synopsis:
                synopsis = extra
            continue

        if kind == "skills":
            s = _parse_skills_section(content_lines)
        elif kind == "experience":
            s = _parse_experience_section(content_lines)
        elif kind == "education":
            s = _parse_education_section(content_lines)
        elif kind == "projects":
            s = _parse_projects_section(content_lines)
        elif kind == "leadership":
            s = _parse_leadership_section(content_lines)
        else:
            clean = [l.strip() for l in content_lines if l.strip()]
            s = {"type": "text", "lines": clean}

        s["title"] = title
        sections.append(s)

    return {
        "name": name or "FRANK VLADMIR MACBRIDE III",
        "contact": contact,
        "tagline": tagline,
        "synopsis": synopsis,
        "sections": sections,
    }


# ── COVER LETTER PARSER ─────────────────────────────────────────────────────

def _parse_cover_letter_txt(text: str) -> dict:
    text = _strip_txt_wrapper(text)
    lines = text.splitlines()
    lines = _strip_metadata_blocks(lines)
    # Fix fixed-width line wrapping, then drop visual separator lines.
    lines = _join_continuations(lines)
    lines = _strip_separator_lines(lines)

    contact = _extract_contact(lines)

    # Name is the very first non-blank, non-contact line.
    derived_name = "FRANK VLADMIR MACBRIDE III"
    for line in lines:
        s = line.strip()
        if s and "@" not in s and not _PHONE_RE.search(s) and not _LINKEDIN_RE.search(s):
            derived_name = s
            break

    # Body starts at the first long line that is not part of the header block.
    # After joining continuations, header lines (name, contact, company, job title)
    # are short; genuine body paragraphs are fully-joined and > 60 chars.
    body_lines: list[str] = []
    in_body = False
    header_re = re.compile(r"^(Frank|FRANK|\+1|\d{3}|www\.|linkedin)", re.I)
    for line in lines:
        s = line.strip()
        if not in_body:
            if (
                not s
                or _EMAIL_RE.search(s)
                or _PHONE_RE.search(s)
                or _LINKEDIN_RE.search(s)
                or header_re.match(s)
                or re.match(r"^(Phone|Email|LinkedIn|Address|Location):", s, re.I)
            ):
                continue
            # "Dear ..." salutation = definitive body start even if short
            if re.match(r"^Dear\b", s, re.I):
                in_body = True
                body_lines.append(line)
                continue
            # First long line = start of letter body
            if len(s) > 60:
                in_body = True
                body_lines.append(line)
            # Short non-contact lines before that = company name / job title → skip
        else:
            body_lines.append(line)

    # Split body into paragraphs on blank lines.
    paragraphs: list[str] = []
    current: list[str] = []
    for line in body_lines:
        s = line.strip()
        if s:
            current.append(s)
        else:
            if current:
                paragraphs.append(" ".join(current))
                current = []
    if current:
        paragraphs.append(" ".join(current))

    # Fix closing signature: last few paragraphs — if one is just a short name, replace it.
    sign_re = re.compile(r"^Frank\s+(MacBride|Vladmir|V\.)", re.I)
    for i in range(len(paragraphs) - 1, max(len(paragraphs) - 5, -1), -1):
        if sign_re.match(paragraphs[i].strip()):
            paragraphs[i] = "Frank Vladmir MacBride III"
            break

    # Name for sidebar
    name_parts = _parse_name_parts(derived_name)

    return {
        **name_parts,
        "contact": contact,
        "paragraphs": paragraphs,
    }


# ── PDF RENDERING ─────────────────────────────────────────────────────────

def _render_pdf(template_name: str, data: dict, output_path: pathlib.Path) -> None:
    # Normalize footer_tag: spaces → underscores
    if "footer_tag" in data:
        data["footer_tag"] = data["footer_tag"].replace(" ", "_")
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    tmpl = env.get_template(template_name)
    html_str = tmpl.render(**data)
    weasyprint.HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(str(output_path))


def _resolve_output_path(output_filename: str, default_stem: str) -> pathlib.Path:
    resume_folder = pathlib.Path(config.RESUME_FOLDER)
    pdf_dir = resume_folder / "03-Resume-PDFs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    fname = output_filename or (default_stem + ".pdf")
    if not fname.endswith(".pdf"):
        fname += ".pdf"
    return pdf_dir / fname


# ── MCP TOOLS ─────────────────────────────────────────────────────────────

def export_resume_pdf(
    filename: str,
    footer_tag: str = "",
    output_filename: str = "",
) -> str:
    """
    Export a .txt resume to PDF using the Frank MacBride Canva-style template.

    Args:
        filename:        Filename inside 01-Current-Optimized/ (with or without .txt).
        footer_tag:      Text for the </TAG> footer (auto-detected from filename if omitted).
        output_filename: Output PDF filename (defaults to same stem + .pdf).

    Returns:
        Path to the generated PDF.
    """
    resume_folder = pathlib.Path(config.RESUME_FOLDER)
    opt_dir = resume_folder / "01-Current-Optimized"

    # Resolve filename
    if not filename.endswith(".txt"):
        filename += ".txt"
    source = opt_dir / filename
    if not source.exists():
        # fuzzy match
        matches = list(opt_dir.glob(f"*{pathlib.Path(filename).stem}*"))
        if not matches:
            return f"Error: file not found — {filename}"
        source = matches[0]

    # Try UTF-8 first; fall back to latin-1 for files saved with other encodings
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source.read_text(encoding="latin-1")
    data = _parse_resume_txt(text)
    data["footer_tag"] = footer_tag.upper() if footer_tag else _derive_footer_tag(source.name)

    stem = source.stem
    out = _resolve_output_path(output_filename, stem)
    _render_pdf("resume.html", data, out)
    return f"✓ PDF exported: {out}"


def export_cover_letter_pdf(
    filename: str,
    output_filename: str = "",
) -> str:
    """
    Export a .txt cover letter to PDF using the Frank MacBride two-column template.

    Args:
        filename:        Filename inside 02-Cover-Letters/ (with or without .txt).
        output_filename: Output PDF filename (defaults to same stem + .pdf).

    Returns:
        Path to the generated PDF.
    """
    resume_folder = pathlib.Path(config.RESUME_FOLDER)
    cl_dir = resume_folder / "02-Cover-Letters"

    if not filename.endswith(".txt"):
        filename += ".txt"
    source = cl_dir / filename
    if not source.exists():
        matches = list(cl_dir.glob(f"*{pathlib.Path(filename).stem}*"))
        if not matches:
            return f"Error: file not found — {filename}"
        source = matches[0]

    # Try UTF-8 first; fall back to latin-1 for files saved with other encodings
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source.read_text(encoding="latin-1")
    data = _parse_cover_letter_txt(text)
    data["footer_tag"] = "SOFTWARE ENGINEER"

    stem = source.stem
    out = _resolve_output_path(output_filename, stem)
    _render_pdf("cover_letter.html", data, out)
    return f"✓ PDF exported: {out}"


def register(mcp) -> None:
    mcp.tool()(export_resume_pdf)
    mcp.tool()(export_cover_letter_pdf)
