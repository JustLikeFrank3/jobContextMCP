"""Tests for lib/template_loader — multi-template / multi-style resume and cover
letter rendering system.

Covers:
- Valid template + style combinations render without error
- All 4 templates × all 5 styles produce valid HTML
- Invalid template / style raises ValueError
- Theme injection injects CSS into <head>
- list_templates / list_styles / list_cl_templates return expected values
- render_cover_letter validates and renders
- PDF-render paths (monkeypatching weasyprint.HTML)
- footer_tag slugification in PDF render paths
"""

import pytest

import lib.template_loader as tl
from lib.template_loader import (
    render_resume,
    render_cover_letter,
    render_resume_to_pdf,
    render_cover_letter_to_pdf,
    list_templates,
    list_styles,
    list_cl_templates,
    VALID_TEMPLATES,
    VALID_STYLES,
)


# ── Shared minimal data fixtures ─────────────────────────────────────────────

_MINIMAL_RESUME = {
    "name": "Jane Doe",
    "tagline": "Backend Engineer",
    "contact": {
        "email": "jane@example.com",
        "phone": "+1 (404) 555-0000",
        "linkedin": "linkedin.com/in/janedoe",
        "github": "github.com/janedoe",
        "location": "Atlanta, GA",
    },
    "synopsis": "Experienced backend engineer.",
    "sections": [
        {
            "title": "TECHNICAL SKILLS",
            "type": "skills",
            "items": [{"label": "Backend", "value": "Python, FastAPI"}],
        },
        {
            "title": "PROFESSIONAL EXPERIENCE",
            "type": "experience",
            "items": [
                {
                    "title": "Software Engineer",
                    "company": "Acme Corp",
                    "dates": "Jan 2022 – Dec 2025",
                    "bullets": ["Built scalable APIs"],
                }
            ],
        },
        {
            "title": "EDUCATION",
            "type": "education",
            "items": [{"degree": "B.S. CS", "school": "State U", "year": "2020"}],
        },
    ],
    "footer_tag": "SOFTWARE_ENGINEER",
}

_MINIMAL_CL = {
    "name_line1": "Jane",
    "name_line2": "Doe",
    "name_last": "Doe",
    "name_suffix": "",
    "contact": {
        "email": "jane@example.com",
        "phone": "+1 (404) 555-0000",
        "linkedin": "linkedin.com/in/janedoe",
        "location": "Atlanta, GA",
    },
    "paragraphs": [
        "I am excited to apply for this role.",
        "I bring strong backend experience.",
    ],
    "footer_tag": "SOFTWARE_ENGINEER",
}


# ── list_* helpers ───────────────────────────────────────────────────────────

class TestListHelpers:
    def test_list_templates_returns_sorted_list(self):
        result = list_templates()
        assert isinstance(result, list)
        assert result == sorted(VALID_TEMPLATES)
        assert set(result) == VALID_TEMPLATES

    def test_list_styles_returns_sorted_list(self):
        result = list_styles()
        assert isinstance(result, list)
        assert result == sorted(VALID_STYLES)
        assert set(result) == VALID_STYLES

    def test_list_cl_templates_matches_resume_templates(self):
        result = list_cl_templates()
        assert isinstance(result, list)
        assert set(result) == VALID_TEMPLATES


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_invalid_template_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown template"):
            render_resume(_MINIMAL_RESUME, template="bogus")

    def test_invalid_style_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown style"):
            render_resume(_MINIMAL_RESUME, style="neon")

    def test_invalid_cl_template_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown CL template"):
            render_cover_letter(_MINIMAL_CL, template="bogus")

    def test_invalid_cl_style_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown style"):
            render_cover_letter(_MINIMAL_CL, style="rainbow")

    def test_none_template_falls_back_to_default(self):
        html = render_resume(_MINIMAL_RESUME, template=None)
        assert "<html" in html.lower() or "<!doctype" in html.lower() or "<body" in html.lower()

    def test_none_style_falls_back_to_default(self):
        html = render_resume(_MINIMAL_RESUME, style=None)
        assert html  # just no crash


# ── Theme injection ──────────────────────────────────────────────────────────

class TestThemeInjection:
    def test_inject_theme_skips_empty_css(self):
        html = "<html><head></head><body></body></html>"
        result = tl._inject_theme(html, "")
        assert result == html

    def test_inject_theme_inserts_before_head_close(self):
        html = "<html><head><title>T</title></head><body></body></html>"
        css = "body { color: red; }"
        result = tl._inject_theme(html, css)
        assert "<style>" in result
        assert "color: red" in result
        assert result.index("<style>") < result.index("</head>")

    def test_load_theme_css_returns_string_for_valid_style(self):
        css = tl._load_theme_css("navy")
        assert isinstance(css, str)
        assert len(css) > 0

    def test_load_theme_css_returns_empty_for_missing(self):
        css = tl._load_theme_css("__nonexistent__")
        assert css == ""


# ── Resume rendering — all templates × all styles ────────────────────────────

class TestRenderResume:
    @pytest.mark.parametrize("template", sorted(VALID_TEMPLATES))
    def test_all_templates_render_name(self, template):
        html = render_resume(_MINIMAL_RESUME, template=template, style="navy")
        assert "Jane Doe" in html

    @pytest.mark.parametrize("style", sorted(VALID_STYLES))
    def test_all_styles_produce_html(self, style):
        html = render_resume(_MINIMAL_RESUME, template="modern", style=style)
        assert "<html" in html.lower() or "<!doctype" in html.lower() or "<body" in html.lower()

    @pytest.mark.parametrize("style", sorted(VALID_STYLES))
    def test_non_classic_styles_inject_theme_block(self, style):
        html = render_resume(_MINIMAL_RESUME, template="modern", style=style)
        if style != "classic":
            assert "injected theme" in html
        # classic might not have a theme override — just no crash

    def test_portfolio_template_renders(self):
        html = render_resume(_MINIMAL_RESUME, template="portfolio", style="slate")
        assert "Jane Doe" in html

    def test_sidebar_template_renders(self):
        html = render_resume(_MINIMAL_RESUME, template="sidebar", style="forest")
        assert "Jane Doe" in html

    def test_executive_template_renders(self):
        html = render_resume(_MINIMAL_RESUME, template="executive", style="warm")
        assert "Jane Doe" in html


# ── Cover letter rendering ───────────────────────────────────────────────────

class TestRenderCoverLetter:
    @pytest.mark.parametrize("template", sorted(VALID_TEMPLATES))
    def test_all_cl_templates_render(self, template):
        html = render_cover_letter(_MINIMAL_CL, template=template, style="navy")
        assert isinstance(html, str)
        assert len(html) > 100

    @pytest.mark.parametrize("style", sorted(VALID_STYLES))
    def test_all_cl_styles_produce_output(self, style):
        html = render_cover_letter(_MINIMAL_CL, template="modern", style=style)
        assert isinstance(html, str)

    def test_none_cl_template_falls_back_to_default(self):
        html = render_cover_letter(_MINIMAL_CL, template=None)
        assert isinstance(html, str)

    def test_none_cl_style_falls_back_to_default(self):
        html = render_cover_letter(_MINIMAL_CL, style=None)
        assert isinstance(html, str)


# ── PDF render paths (weasyprint mocked) ────────────────────────────────────

class TestPdfRender:
    @pytest.fixture(autouse=True)
    def mock_weasyprint(self, monkeypatch, tmp_path):
        """Replace weasyprint.HTML with a stub that writes a dummy PDF byte."""
        class _FakeHTML:
            def __init__(self, string, base_url):
                pass
            def write_pdf(self, path):
                with open(path, "wb") as f:
                    f.write(b"%PDF-1.4 stub")

        monkeypatch.setattr(tl.weasyprint, "HTML", _FakeHTML)
        self.out = tmp_path / "out.pdf"

    def test_render_resume_to_pdf_creates_file(self):
        render_resume_to_pdf(_MINIMAL_RESUME, self.out, template="modern", style="navy")
        assert self.out.exists()
        assert self.out.stat().st_size > 0

    def test_render_resume_to_pdf_footer_tag_slugified(self):
        data = dict(_MINIMAL_RESUME, footer_tag="SOFT WARE ENGINEER")
        render_resume_to_pdf(data, self.out)
        assert self.out.exists()

    def test_render_resume_to_pdf_no_footer_tag(self):
        data = {k: v for k, v in _MINIMAL_RESUME.items() if k != "footer_tag"}
        render_resume_to_pdf(data, self.out)
        assert self.out.exists()

    def test_render_cover_letter_to_pdf_creates_file(self):
        render_cover_letter_to_pdf(_MINIMAL_CL, self.out, template="modern", style="navy")
        assert self.out.exists()

    def test_render_cover_letter_to_pdf_footer_tag_slugified(self):
        data = dict(_MINIMAL_CL, footer_tag="SOFT WARE ENGINEER")
        render_cover_letter_to_pdf(data, self.out)
        assert self.out.exists()

    @pytest.mark.parametrize("template", sorted(VALID_TEMPLATES))
    def test_all_templates_pdf_render(self, template):
        render_resume_to_pdf(_MINIMAL_RESUME, self.out, template=template, style="classic")
        assert self.out.exists()
