"""
Resume + Cover Letter template loader — multi-template / multi-style rendering system.

Provides render_resume / render_cover_letter (and their _to_pdf variants)
to render any supported visual layout from the same normalized data dicts
produced by lib.resume_parser.

Supported templates (layout formats — same names for both document types)
--------------------------------------------------------------------------
modern    — clean single-column, ATS-friendly, professional sans-serif
executive — larger typography, prominent summary, achievement-emphasis layout
sidebar   — two-column layout; left sidebar holds skills/contact/education
portfolio — projects-first ordering, GitHub-prominent, technical creator style

Supported styles (color themes — shared across resume and cover letter)
------------------------------------------------------------------------
navy    — deep professional blue (default)
slate   — cool gray-blue
forest  — deep green
warm    — amber / golden brown
classic — black & white, no accent color (maximum ATS compatibility)

Usage
-----
from lib.template_loader import render_resume, render_cover_letter

html = render_resume(resume_data, template="modern", style="navy")
html = render_cover_letter(cl_data, template="sidebar", style="slate")
"""

import pathlib

import weasyprint
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_ROOT = pathlib.Path(__file__).parent.parent / "templates"
_RESUME_TEMPLATES_DIR = _TEMPLATES_ROOT / "resume_templates"
_CL_TEMPLATES_DIR = _TEMPLATES_ROOT / "cover_letter_templates"
_THEMES_DIR = _RESUME_TEMPLATES_DIR / "themes"

VALID_TEMPLATES = frozenset({"modern", "executive", "sidebar", "portfolio"})
VALID_CL_TEMPLATES = frozenset({"modern", "executive", "sidebar", "portfolio"})
VALID_STYLES = frozenset({"navy", "slate", "forest", "warm", "classic"})

DEFAULT_TEMPLATE = "modern"
DEFAULT_STYLE = "navy"


def _load_theme_css(style: str) -> str:
    """Load and return the CSS custom property overrides for the given style."""
    theme_path = _THEMES_DIR / f"{style}.css"
    if not theme_path.exists():
        return ""
    return theme_path.read_text(encoding="utf-8")


def _inject_theme(html: str, theme_css: str) -> str:
    """Inject theme CSS overrides into a rendered HTML string before </head>."""
    if not theme_css:
        return html
    injection = f"\n<style>\n/* injected theme */\n{theme_css}\n</style>\n"
    return html.replace("</head>", injection + "</head>", 1)


def render_resume(
    resume_data: dict,
    template: str = DEFAULT_TEMPLATE,
    style: str = DEFAULT_STYLE,
) -> str:
    """Render resume data to an HTML string using the specified template and style.

    Args:
        resume_data: Normalized dict from lib.resume_parser._parse_resume_txt.
                     Expected keys: name, contact, tagline, synopsis, sections,
                     footer_tag (optional).
        template:    Layout format. One of: modern, executive, sidebar, portfolio.
        style:       Color theme. One of: navy, slate, forest, warm, classic.

    Returns:
        Rendered HTML string suitable for browser preview or PDF conversion.

    Raises:
        ValueError: If template or style is not in their respective valid sets.
    """
    template = template or DEFAULT_TEMPLATE
    style = style or DEFAULT_STYLE

    if template not in VALID_TEMPLATES:
        raise ValueError(
            f"Unknown template {template!r}. Valid options: {sorted(VALID_TEMPLATES)}"
        )
    if style not in VALID_STYLES:
        raise ValueError(
            f"Unknown style {style!r}. Valid options: {sorted(VALID_STYLES)}"
        )

    template_dir = _RESUME_TEMPLATES_DIR / template
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    html = env.get_template("resume.html").render(**resume_data)
    theme_css = _load_theme_css(style)
    return _inject_theme(html, theme_css)


def render_resume_to_pdf(
    resume_data: dict,
    output_path: pathlib.Path,
    template: str = DEFAULT_TEMPLATE,
    style: str = DEFAULT_STYLE,
) -> None:
    """Render resume data to a PDF file using the specified template and style.

    Args:
        resume_data: Normalized dict from lib.resume_parser._parse_resume_txt.
        output_path: Destination .pdf path (created/overwritten).
        template:    Layout format. One of: modern, executive, sidebar, portfolio.
        style:       Color theme. One of: navy, slate, forest, warm, classic.
    """
    data = dict(resume_data)
    if "footer_tag" in data:
        data["footer_tag"] = data["footer_tag"].replace(" ", "_")

    html_str = render_resume(data, template, style)
    template_dir = _RESUME_TEMPLATES_DIR / template
    weasyprint.HTML(
        string=html_str,
        base_url=str(template_dir),
    ).write_pdf(str(output_path))


def list_templates() -> list[str]:
    """Return sorted list of available template names."""
    return sorted(VALID_TEMPLATES)


def list_styles() -> list[str]:
    """Return sorted list of available style theme names."""
    return sorted(VALID_STYLES)


# ── COVER LETTER RENDERING ─────────────────────────────────────────────────


def render_cover_letter(
    cl_data: dict,
    template: str = DEFAULT_TEMPLATE,
    style: str = DEFAULT_STYLE,
) -> str:
    """Render cover letter data to an HTML string.

    Args:
        cl_data:  Normalized dict from lib.resume_parser._parse_cover_letter_txt.
                  Expected keys: name_line1, name_line2, name_last, name_suffix,
                  contact (dict), paragraphs (list[str]), footer_tag (optional).
        template: Layout format. One of: modern, executive, sidebar, portfolio.
        style:    Color theme. One of: navy, slate, forest, warm, classic.

    Returns:
        Rendered HTML string suitable for browser preview or PDF conversion.
    """
    template = template or DEFAULT_TEMPLATE
    style = style or DEFAULT_STYLE

    if template not in VALID_CL_TEMPLATES:
        raise ValueError(
            f"Unknown CL template {template!r}. Valid options: {sorted(VALID_CL_TEMPLATES)}"
        )
    if style not in VALID_STYLES:
        raise ValueError(
            f"Unknown style {style!r}. Valid options: {sorted(VALID_STYLES)}"
        )

    template_dir = _CL_TEMPLATES_DIR / template
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    html = env.get_template("cover_letter.html").render(**cl_data)
    theme_css = _load_theme_css(style)
    return _inject_theme(html, theme_css)


def render_cover_letter_to_pdf(
    cl_data: dict,
    output_path: pathlib.Path,
    template: str = DEFAULT_TEMPLATE,
    style: str = DEFAULT_STYLE,
) -> None:
    """Render cover letter data to a PDF file.

    Args:
        cl_data:     Normalized dict from lib.resume_parser._parse_cover_letter_txt.
        output_path: Destination .pdf path (created/overwritten).
        template:    Layout format. One of: modern, executive, sidebar, portfolio.
        style:       Color theme. One of: navy, slate, forest, warm, classic.
    """
    data = dict(cl_data)
    if "footer_tag" in data:
        data["footer_tag"] = data["footer_tag"].replace(" ", "_")

    html_str = render_cover_letter(data, template, style)
    template_dir = _CL_TEMPLATES_DIR / template
    weasyprint.HTML(
        string=html_str,
        base_url=str(template_dir),
    ).write_pdf(str(output_path))


def list_cl_templates() -> list[str]:
    """Return sorted list of available cover letter template names."""
    return sorted(VALID_CL_TEMPLATES)
