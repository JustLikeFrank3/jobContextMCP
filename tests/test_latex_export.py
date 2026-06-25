from pathlib import Path
from types import SimpleNamespace

from tools import latex_export
from tools import export


def test_latex_cover_letter_template_owns_date_and_signature():
    template = latex_export._TEX_TEMPLATE

    assert "{date}" in template
    assert "\\noindent Regards," not in template
    assert "Kindest Regards," in template
    assert "\\name" in template.split("Kindest Regards,")[-1]


def test_latex_user_identity_default_is_generic_placeholder(monkeypatch):
    """When no contact is configured, _user_identity() must return generic
    placeholder values — never a real person's data."""
    monkeypatch.setattr(latex_export.cfg, "get_contact_info", lambda: {})

    identity = latex_export._user_identity()

    # Must not contain any real personal data as the fallback
    assert "Frank" not in identity["name"]
    assert "MacBride" not in identity["name"]
    # Must be a neutral placeholder string
    assert identity["name"] == "YOUR FULL NAME"
    assert "@" in identity["email"]
    assert "example" in identity["email"]


def test_latex_user_identity_blank_strings_fall_back_to_placeholder(monkeypatch):
    """A contact block with all blank strings (e.g. a freshly seeded config.json)
    must still produce placeholder values — blank strings would crash tectonic."""
    blank_contact = {"name": "", "phone": "", "city": "", "email": "", "linkedin": "", "github": ""}
    monkeypatch.setattr(latex_export.cfg, "get_contact_info", lambda: blank_contact)

    identity = latex_export._user_identity()

    assert identity["name"] == "YOUR FULL NAME"
    assert "@" in identity["email"]
    assert "example" in identity["email"]
    assert identity["linkedin"] == "yourhandle"
    assert identity["github"] == "YourGitHub"


def test_latex_cover_letter_defaults_to_cover_letter_pdf_folder(monkeypatch, tmp_path):
    latex_dir = tmp_path / "latex"
    resume_dir = tmp_path / "resumes"
    latex_dir.mkdir()
    resume_dir.mkdir()
    (latex_dir / "_header.tex").write_text("", encoding="utf-8")
    (latex_dir / "TLCresume.sty").write_text("", encoding="utf-8")

    def fake_run(*args, **kwargs):
        cwd = kwargs["cwd"]
        (latex_export.Path(cwd) / "cover_letter.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export.cfg, "RESUME_FOLDER", resume_dir)
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

    out = latex_export.generate_cover_letter_latex(
        body="I build useful software.\n\nI keep the systems boring in production.",
        company="Stripe",
        role="Staff Engineer",
    )

    assert out.parent.name == "09-Cover-Letter-PDFs"
    assert out.exists()


def test_latex_cover_letter_uses_bundled_support_files_when_workspace_missing(monkeypatch, tmp_path):
    latex_dir = tmp_path / "latex"
    bundled_dir = tmp_path / "bundled"
    resume_dir = tmp_path / "resumes"
    latex_dir.mkdir()
    bundled_dir.mkdir()
    resume_dir.mkdir()
    (bundled_dir / "_header.tex").write_text("", encoding="utf-8")
    (bundled_dir / "TLCresume.sty").write_text("", encoding="utf-8")

    def fake_run(*args, **kwargs):
        cwd = kwargs["cwd"]
        (latex_export.Path(cwd) / "cover_letter.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled_dir)
    monkeypatch.setattr(latex_export.cfg, "RESUME_FOLDER", resume_dir)
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

    out = latex_export.generate_cover_letter_latex(
        body="I build useful software.\n\nI keep the systems boring in production.",
        company="Stripe",
        role="Staff Engineer",
    )

    assert out.parent.name == "09-Cover-Letter-PDFs"
    assert out.exists()

def test_export_cover_letter_latex_tool_extracts_body_from_full_letter(monkeypatch):
    """The MCP tool accepts a pasted full letter and passes only the prose body
    to the LaTeX pipeline (salutation, leading header, and sign-off stripped)."""
    captured = {}

    def fake_generate(*, body, company, role, role_title, letter_date):
        captured.update(body=body, company=company, role=role, role_title=role_title)
        return Path("/tmp/09-Cover-Letter-PDFs/cover_letter_Equifax.pdf")

    monkeypatch.setattr(latex_export, "generate_cover_letter_latex", fake_generate)

    full_letter = (
        "FRANK VLADMIR MACBRIDE III\n"
        "Email: frankvmacbride@gmail.com\n\n"
        "Dear Hiring Manager,\n\n"
        "I keep the systems boring in production.\n\n"
        "I own the whole stack end to end.\n\n"
        "Kindest Regards,\nFrank Vladmir MacBride III"
    )

    result = export.export_cover_letter_latex(
        company="Equifax", role="Senior Applied AI Engineer",
        body=full_letter, role_title="Senior Applied AI Engineer",
    )

    assert "PDF exported (LaTeX)" in result
    assert captured["role_title"] == "Senior Applied AI Engineer"
    # Body must be the prose only — no salutation, header email, or sign-off.
    assert "boring in production" in captured["body"]
    assert "Dear Hiring Manager" not in captured["body"]
    assert "frankvmacbride@gmail.com" not in captured["body"]
    assert "Kindest Regards" not in captured["body"]


def test_export_cover_letter_latex_tool_requires_body_or_filename():
    msg = export.export_cover_letter_latex(company="Acme", role="SWE")
    assert msg.startswith("Error:")


def test_export_resume_latex_tool_success(monkeypatch):
    """The resume MCP tool returns the compiled PDF path on success."""
    def fake_generate(*, resume_text, company, role, role_title, output_filename):
        assert company == "Equifax" and role == "Senior Applied AI Engineer"
        return Path("/tmp/03-Resume-PDFs/resume_Equifax.pdf")

    monkeypatch.setattr(latex_export, "generate_resume_latex", fake_generate)

    result = export.export_resume_latex(
        company="Equifax", role="Senior Applied AI Engineer",
    )
    assert "PDF exported (LaTeX)" in result
    assert "resume_Equifax.pdf" in result


def test_export_resume_latex_tool_surfaces_unconfigured_dir(monkeypatch):
    """When latex_resume_dir / resume.tex is missing, the tool returns a clear
    error string rather than raising."""
    def fake_generate(**kwargs):
        raise FileNotFoundError("latex_resume_dir is not set or does not exist in config.json.")

    monkeypatch.setattr(latex_export, "generate_resume_latex", fake_generate)

    msg = export.export_resume_latex(company="Acme", role="SWE")
    assert msg.startswith("Error:")
    assert "latex_resume_dir" in msg
