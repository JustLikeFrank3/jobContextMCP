"""
Resume template loader — multi-template rendering system.

Provides render_resume(resume_data, template) and render_resume_to_pdf() to
render any of the supported visual layouts from the same normalized resume data
dict produced by lib.resume_parser._parse_resume_txt.

Supported templates
-------------------
modern    — clean single-column, ATS-friendly, professional sans-serif
executive — larger typography, prominent summary, achievement-emphasis layout
sidebar   — two-column layout; left sidebar holds skills/contact/education
portfolio — projects-first ordering, GitHub-prominent, technical creator style

Usage
-----
from lib.template_loader import render_resume, render_resume_to_pdf

html = render_resume(resume_data, template="modern")
render_resume_to_pdf(resume_data, pathlib.Path("out.pdf"), template="sidebar")
"""

import pathlib

import weasyprint
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_ROOT = pathlib.Path(__file__).parent.parent / "templates"
_RESUME_TEMPLATES_DIR = _TEMPLATES_ROOT / "resume_templates"

VALID_TEMPLATES = frozenset({"modern", "executive", "sidebar", "portfolio"})


def render_resume(resume_data: dict, template: str = "modern") -> str:
    """Render resume data to an HTML string using the specified template.

    Args:
        resume_data: Normalized dict from lib.resume_parser._parse_resume_txt.
                     Expected keys: name, contact, tagline, synopsis, sections,
                     footer_tag (optional).
        template:    Template name. One of: modern, executive, sidebar, portfolio.

    Returns:
        Rendered HTML string suitable for browser preview or PDF conversion.

    Raises:
        ValueError: If template is not in VALID_TEMPLATES.
    """
    if template not in VALID_TEMPLATES:
        raise ValueError(
            f"Unknown template {template!r}. Valid options: {sorted(VALID_TEMPLATES)}"
        )
    template_dir = _RESUME_TEMPLATES_DIR / template
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    return env.get_template("resume.html").render(**resume_data)


def render_resume_to_pdf(
    resume_data: dict,
    output_path: pathlib.Path,
    template: str = "modern",
) -> None:
    """Render resume data to a PDF file using the specified template.

    Args:
        resume_data: Normalized dict from lib.resume_parser._parse_resume_txt.
        output_path: Destination .pdf path (created/overwritten).
        template:    Template name. One of: modern, executive, sidebar, portfolio.
    """
    data = dict(resume_data)
    if "footer_tag" in data:
        data["footer_tag"] = data["footer_tag"].replace(" ", "_")

    html_str = render_resume(data, template)
    template_dir = _RESUME_TEMPLATES_DIR / template
    weasyprint.HTML(
        string=html_str,
        base_url=str(template_dir),
    ).write_pdf(str(output_path))


def list_templates() -> list[str]:
    """Return sorted list of available template names."""
    return sorted(VALID_TEMPLATES)
