from types import SimpleNamespace

from tools import latex_export


def test_latex_cover_letter_template_owns_date_and_signature():
    template = latex_export._TEX_TEMPLATE

    assert "{date}" in template
    assert "\\noindent Regards," not in template
    assert "Kindest Regards," in template
    assert "\\name" in template.split("Kindest Regards,")[-1]


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