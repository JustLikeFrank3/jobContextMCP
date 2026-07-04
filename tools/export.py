"""
PDF export tool — v5

export_resume_pdf(filename, footer_tag?, output_filename?, template?, style?)
    Reads a .txt resume from 01-Current-Optimized/, parses it,
    renders via the selected template, and writes a PDF to 03-Resume-PDFs/.

    template selects the visual layout (default: "" uses legacy resume.html):
        ""          — legacy Courier New monospaced layout (backward compat)
        "modern"    — clean single-column sans-serif, ATS-friendly
        "executive" — larger type, prominent summary, achievement-emphasis
        "sidebar"   — two-column; left sidebar for skills/contact/education
        "portfolio" — projects-first, GitHub-prominent, technical creator

    style selects the color theme (only applied when template is set):
        "navy"      — deep professional blue (default)
        "slate"     — cool gray-blue
        "forest"    — deep green
        "warm"      — amber / golden brown
        "classic"   — black & white, maximum ATS compatibility

export_cover_letter_pdf(filename, output_filename?)
    Reads a .txt cover letter from 02-Cover-Letters/, parses it,
    renders via cover_letter.html template, and writes a PDF to 09-Cover-Letter-PDFs/.
"""

import pathlib

from jinja2 import Environment, FileSystemLoader
import weasyprint

from lib import config
from lib.template_loader import render_resume_to_pdf as _render_resume_to_pdf, VALID_TEMPLATES, VALID_STYLES
from lib.resume_parser import (
    _derive_footer_tag,
    _parse_resume_txt,
    _parse_cover_letter_txt,
    _get_contact_defaults,
    _strip_txt_wrapper,
    _is_bullet,
    _is_section_header,
    _clean_bullet,
    _is_date_line,
    _is_group_label,
    _join_continuations,
    _strip_separator_lines,
    _extract_contact,
    _strip_metadata_blocks,
    _split_sections,
    _parse_header,
    _parse_skills_section,
    _is_date_part,
    _finalize_job,
    _parse_experience_section,
    _combine_date_ranges,
    _normalize_company,
    _merge_same_company_jobs,
    _parse_education_section,
    _parse_projects_section,
    _parse_leadership_section,
    _parse_achievements_section,
    _classify_section,
    _parse_name_parts,
)

# ── PATHS ────────────────────────────────────────────────────────────────

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"


# ── PDF RENDERING ─────────────────────────────────────────────────────────

def _render_pdf(template_name: str, data: dict, output_path: pathlib.Path) -> None:
    # Normalize footer_tag: spaces → underscores
    if "footer_tag" in data:
        data["footer_tag"] = data["footer_tag"].replace(" ", "_")
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    tmpl = env.get_template(template_name)
    html_str = tmpl.render(**data)
    weasyprint.HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(str(output_path))


def _resolve_output_path(
    output_filename: str,
    default_stem: str,
    folder_name: str = "03-Resume-PDFs",
) -> pathlib.Path:
    pdf_dir = config.get_active_workspace_folder() / folder_name
    pdf_dir.mkdir(parents=True, exist_ok=True)
    fname = output_filename or (default_stem + ".pdf")
    if not fname.endswith(".pdf"):
        fname += ".pdf"
    return pdf_dir / fname


def _cover_letter_pdf_folder_name() -> str:
    return config.get_active_cover_letter_pdfs_dir().name


# ── MCP TOOLS ─────────────────────────────────────────────────────────────

def export_resume_pdf(
    filename: str,
    footer_tag: str = "",
    output_filename: str = "",
    template: str = "",
    style: str = "navy",
) -> str:
    """
    Export a .txt resume to PDF.

    Args:
        filename:        Filename inside 01-Current-Optimized/ (with or without .txt).
        footer_tag:      Text for the </TAG> footer (auto-detected from filename if omitted).
        output_filename: Output PDF filename (defaults to same stem + .pdf).
        template:        Visual layout. One of: modern, executive, sidebar, portfolio.
                         Leave empty ("") to use the default legacy layout.
        style:           Color theme (only used when template is set).
                         One of: navy, slate, forest, warm, classic. Default: navy.

    Returns:
        Path to the generated PDF, or an error string.
    """
    if template and template not in VALID_TEMPLATES:
        return (
            f"Error: unknown template {template!r}. "
            f"Valid options: {sorted(VALID_TEMPLATES)} or leave empty for default."
        )
    if style and style not in VALID_STYLES:
        return (
            f"Error: unknown style {style!r}. "
            f"Valid options: {sorted(VALID_STYLES)}."
        )

    opt_dir = config.get_active_optimized_resumes_dir()

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

    if template:
        _render_resume_to_pdf(data, out, template=template, style=style or "navy")
    else:
        _render_pdf("resume.html", data, out)

    return f"✓ PDF exported: {out}"


def export_cover_letter_pdf(
    filename: str,
    output_filename: str = "",
    footer_tag: str = "SOFTWARE ENGINEER",
    template: str = "",
    style: str = "navy",
) -> str:
    """Pipeline B — HTML/weasyprint cover letter export.

    Renders a .txt cover letter to PDF using the Frank MacBride two-column
    HTML template via weasyprint.  This is the *fallback* pipeline for
    environments where tectonic is unavailable.

    For the primary LaTeX-based pipeline (identical visual output to the
    manually-compiled frank-resume-latex versions) use
    tools.latex_export.generate_cover_letter_latex() instead.

    Args:
        filename:        Filename inside 02-Cover-Letters/ (with or without .txt).
        output_filename: Output PDF filename (defaults to same stem + .pdf).
        footer_tag:      Text for the </TAG> footer.
        template:        Visual layout. One of: modern, executive, sidebar, portfolio.
                         Leave empty ("") to use the default legacy layout.
        style:           Color theme. One of: navy, slate, forest, warm, classic.

    Returns:
        Path to the generated PDF.
    """
    from lib.template_loader import (
        render_cover_letter_to_pdf as _render_cl_to_pdf,
        VALID_CL_TEMPLATES,
        VALID_STYLES,
    )

    if template and template not in VALID_CL_TEMPLATES:
        return (
            f"Error: unknown CL template {template!r}. "
            f"Valid options: {sorted(VALID_CL_TEMPLATES)} or leave empty for default."
        )
    if style and style not in VALID_STYLES:
        return f"Error: unknown style {style!r}. Valid options: {sorted(VALID_STYLES)}."

    cl_dir = config.get_active_cover_letters_dir()

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
    data["footer_tag"] = footer_tag

    stem = source.stem
    out = _resolve_output_path(output_filename, stem, _cover_letter_pdf_folder_name())

    if template:
        _render_cl_to_pdf(data, out, template=template, style=style or "navy")
    else:
        _render_pdf("cover_letter.html", data, out)
    return f"✓ PDF exported: {out}"


def export_cover_letter_latex(
    company: str,
    role: str,
    body: str = "",
    filename: str = "",
    role_title: str = "Full Stack Software Engineer",
    letter_date: str = "",
) -> str:
    """Pipeline A — LaTeX cover letter export (tectonic, with pdflatex fallback).

    Compiles a cover letter to PDF using the TLCresume LaTeX template, producing
    output identical to the manually-compiled frank-resume-latex versions. This
    is the PRIMARY cover-letter pipeline; export_cover_letter_pdf is the
    HTML/weasyprint fallback for environments without a LaTeX engine.

    Provide the letter text one of two ways:
      - body:     Paste the cover-letter text directly. The template supplies its
                  own salutation ("Dear Hiring Manager,") and sign-off, so a full
                  letter is fine — the prose body is extracted automatically (any
                  leading contact header, "Dear ..." line, and closing block are
                  stripped). Takes precedence over filename.
      - filename: Name of a saved .txt in the active cover-letters folder (with
                  or without .txt). Used when body is empty.

    Args:
        company:     Target company (used in the letter and output filename).
        role:        Target role (used in the output filename).
        body:        Cover-letter text. Takes precedence over filename.
        filename:    Saved .txt to read when body is empty.
        role_title:  Title printed under the name in the letterhead
                     (e.g. "Senior Applied AI Engineer"). Default: Full Stack
                     Software Engineer.
        letter_date: Right-aligned date under the letterhead. Defaults to today.

    Returns:
        Path to the generated PDF, or an error string.
    """
    from tools.latex_export import generate_cover_letter_latex
    from tools.generate import _extract_cover_letter_body

    raw = body
    if not raw.strip():
        if not filename:
            return "Error: provide either body text or a filename from the cover-letters folder."
        cl_dir = config.get_active_cover_letters_dir()
        if not filename.endswith(".txt"):
            filename += ".txt"
        source = cl_dir / filename
        if not source.exists():
            matches = list(cl_dir.glob(f"*{pathlib.Path(filename).stem}*"))
            if not matches:
                return f"Error: file not found — {filename}"
            source = matches[0]
        try:
            raw = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = source.read_text(encoding="latin-1")

    # Strip salutation/header/sign-off so they aren't duplicated by the template.
    # Fall back to the raw text if the draft is already just the body paragraphs.
    letter_body = _extract_cover_letter_body(raw) or raw.strip()
    if not letter_body.strip():
        return "Error: could not extract a cover-letter body from the provided text."

    try:
        pdf = generate_cover_letter_latex(
            body=letter_body,
            company=company,
            role=role,
            role_title=role_title,
            letter_date=letter_date,
        )
    except Exception as exc:  # noqa: BLE001 — surface the compile error to the caller
        return f"⚠ LaTeX export failed: {exc}"
    return f"✓ PDF exported (LaTeX): {pdf}"


def export_resume_latex(
    company: str,
    role: str,
    resume_text: str = "",
    output_filename: str = "",
    role_title: str = "",
) -> str:
    """Pipeline A — LaTeX resume export (tectonic).

    Compiles a ``resume.tex`` from the configured ``latex_resume_dir`` as-is
    ("compile what's there") and copies the PDF to the workspace resume folder.

    NOTE: unlike export_cover_letter_latex, this pipeline does NOT inject the
    resume body (the .tex source governs layout) and has NO bundled-asset
    fallback. It requires ``latex_resume_dir`` to be set in config and to
    contain a ``resume.tex`` source file; otherwise it returns an error string.
    The legacy/portable path is export_resume_pdf (HTML/weasyprint), which
    works without a LaTeX engine or .tex source.

    Args:
        company:         Target company (used in the output filename).
        role:            Target role (used in the output filename).
        resume_text:     Reserved — not injected by this pipeline (the .tex
                         source governs layout). Accepted for API symmetry.
        output_filename: Override the output PDF filename. Defaults to
                         resume_{company}_{role}_{YYYYMMDD}.pdf.
        role_title:      Sets the resume header role via ``\\def\\role``
                         injection (e.g. "Full-Stack AI Engineer"). Blank uses
                         the role defined in the resume.tex template.

    Returns:
        Path to the generated PDF, or an error string.
    """
    from tools.latex_export import generate_resume_latex

    try:
        pdf = generate_resume_latex(
            resume_text=resume_text,
            company=company,
            role=role,
            role_title=role_title,
            output_filename=output_filename,
        )
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 — surface the compile error to the caller
        return f"⚠ LaTeX resume export failed: {exc}"
    return f"✓ PDF exported (LaTeX): {pdf}"


# ---------------------------------------------------------------------------
# LaTeX asset read / write (server-side content injection)
# ---------------------------------------------------------------------------

from tools.latex_export import (  # noqa: E402 — local import after heavy deps
    _BUNDLED_LATEX_ASSETS_DIR,
    _READABLE_LATEX_ASSETS,
    _WRITABLE_LATEX_SECTIONS,
    read_latex_asset,
    write_latex_section,
)

__all__ = [
    "export_resume_pdf",
    "export_cover_letter_pdf",
    "export_cover_letter_latex",
    "export_resume_latex",
    "read_latex_asset",
    "write_latex_section",
]


def register(mcp) -> None:
    mcp.tool()(export_resume_pdf)
    mcp.tool()(export_cover_letter_pdf)
    mcp.tool()(export_cover_letter_latex)
    mcp.tool()(export_resume_latex)
    mcp.tool()(read_latex_asset)
    mcp.tool()(write_latex_section)
