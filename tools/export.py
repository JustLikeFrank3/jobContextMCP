"""
PDF export tool — v4

export_resume_pdf(filename, footer_tag?, output_filename?)
    Reads a .txt resume from 01-Current-Optimized/, parses it,
    renders via resume.html template, and writes a PDF to 03-Resume-PDFs/.

export_cover_letter_pdf(filename, output_filename?)
    Reads a .txt cover letter from 02-Cover-Letters/, parses it,
    renders via cover_letter.html template, and writes a PDF to 09-Cover-Letter-PDFs/.
"""

import pathlib

from jinja2 import Environment, FileSystemLoader
import weasyprint

from lib import config
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
    _render_pdf("resume.html", data, out)
    return f"✓ PDF exported: {out}"


def export_cover_letter_pdf(
    filename: str,
    output_filename: str = "",
    footer_tag: str = "SOFTWARE ENGINEER",
) -> str:
    """Pipeline B — HTML/weasyprint cover letter export.

    Renders a .txt cover letter to PDF using the Frank MacBride two-column
    HTML template via weasyprint.  This is the *fallback* pipeline for
    environments where tectonic is unavailable.

    For the primary LaTeX-based pipeline (identical visual output to the
    manually-compiled frank-resume-latex versions) use
    tools.latex_export.generate_cover_letter_latex() instead.

    Export a .txt cover letter to PDF using the Frank MacBride two-column template.

    Args:
        filename:        Filename inside 02-Cover-Letters/ (with or without .txt).
        output_filename: Output PDF filename (defaults to same stem + .pdf).

    Returns:
        Path to the generated PDF.
    """
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
    _render_pdf("cover_letter.html", data, out)
    return f"✓ PDF exported: {out}"


def register(mcp) -> None:
    mcp.tool()(export_resume_pdf)
    mcp.tool()(export_cover_letter_pdf)
