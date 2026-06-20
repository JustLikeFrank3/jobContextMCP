from types import SimpleNamespace

from tools import latex_export


def test_latex_cover_letter_template_owns_date_and_signature():
    template = latex_export._TEX_TEMPLATE

    assert "{date}" in template
    assert "\\noindent Regards," not in template
    assert "Kindest Regards," in template
    assert "\\name" in template.split("Kindest Regards,")[-1]


def test_latex_user_identity_default_name_uses_exact_spelling(monkeypatch):
    monkeypatch.setattr(latex_export.cfg, "get_contact_info", lambda: {})

    identity = latex_export._user_identity()

    assert identity["name"] == "Frank Vladmir MacBride III"


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