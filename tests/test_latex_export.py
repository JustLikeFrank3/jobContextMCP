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


# ---------------------------------------------------------------------------
# Tenant isolation regression tests
# Regression: generate_resume_latex previously used cfg.RESUME_FOLDER (the
# global owner path) instead of get_active_resume_pdfs_dir() (per-request
# ContextVar-scoped resolver).  Two tenants exporting simultaneously would
# write to the same /app/data/workspace/ directory.
# ---------------------------------------------------------------------------

class TestLatexExportTenantIsolation:
    """Assert both pipelines write to per-tenant paths, never to the global root."""

    def _fake_tectonic_run(self, pdf_name: str):
        """Return a subprocess.run replacement that creates pdf_name in cwd."""
        def fake_run(cmd, cwd, **kwargs):
            (Path(cwd) / pdf_name).write_bytes(b"%PDF-1.4")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        return fake_run

    def test_cover_letter_pdf_lands_in_tenant_folder(self, monkeypatch, tmp_path):
        """generate_cover_letter_latex must write to the caller's tenant workspace,
        not to the global /app/data/workspace/ root."""
        tenant_a = tmp_path / "users" / "oid-tenant-a" / "data"
        tenant_a.mkdir(parents=True)
        latex_dir = tmp_path / "latex_assets"
        latex_dir.mkdir()
        (latex_dir / "_header.tex").write_text("", encoding="utf-8")
        (latex_dir / "TLCresume.sty").write_text("", encoding="utf-8")
        global_root = tmp_path / "app_data_workspace"
        global_root.mkdir()

        monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
        monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
        monkeypatch.setattr(latex_export.subprocess, "run",
                            self._fake_tectonic_run("cover_letter.pdf"))
        # Simulate tenant-A's ContextVar data-folder override
        monkeypatch.setattr(latex_export.cfg, "get_active_cover_letter_pdfs_dir",
                            lambda: tenant_a / "workspace" / "09-Cover-Letter-PDFs")
        # Global root should NOT be touched
        monkeypatch.setattr(latex_export.cfg, "RESUME_FOLDER", global_root)

        pdf = latex_export.generate_cover_letter_latex(
            body="Para one.\n\nPara two.", company="Boeing", role="Senior Java Developer"
        )

        assert "oid-tenant-a" in str(pdf), f"PDF not in tenant folder: {pdf}"
        assert str(global_root) not in str(pdf), f"PDF leaked to global root: {pdf}"
        assert pdf.exists()

    def test_resume_pdf_lands_in_tenant_folder(self, monkeypatch, tmp_path):
        """generate_resume_latex must write to the caller's tenant workspace,
        not to the global /app/data/workspace/ root."""
        tenant_b = tmp_path / "users" / "oid-tenant-b" / "data"
        tenant_b.mkdir(parents=True)
        latex_dir = tmp_path / "latex_assets"
        latex_dir.mkdir()
        (latex_dir / "resume.tex").write_text("\\documentclass{article}\\begin{document}\\end{document}", encoding="utf-8")
        global_root = tmp_path / "app_data_workspace"
        global_root.mkdir()

        monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
        monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
        monkeypatch.setattr(latex_export.subprocess, "run",
                            self._fake_tectonic_run("resume.pdf"))
        # Simulate tenant-B's ContextVar data-folder override
        monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir",
                            lambda: tenant_b / "workspace" / "03-Resume-PDFs")
        # Global root must NOT be used
        monkeypatch.setattr(latex_export.cfg, "RESUME_FOLDER", global_root)

        pdf = latex_export.generate_resume_latex(
            resume_text="", company="Boeing", role="Senior Java Developer"
        )

        assert "oid-tenant-b" in str(pdf), f"PDF not in tenant folder: {pdf}"
        assert str(global_root) not in str(pdf), f"PDF leaked to global root: {pdf}"
        assert pdf.exists()

    def test_two_tenants_pdf_paths_are_disjoint(self, monkeypatch, tmp_path):
        """Two simultaneous callers must produce PDFs in completely separate
        directories — no shared path segment between the two output locations."""
        tenant_a_dir = tmp_path / "users" / "oid-aaa" / "data" / "workspace" / "03-Resume-PDFs"
        tenant_b_dir = tmp_path / "users" / "oid-bbb" / "data" / "workspace" / "03-Resume-PDFs"
        latex_dir = tmp_path / "latex_assets"
        latex_dir.mkdir()
        (latex_dir / "resume.tex").write_text("", encoding="utf-8")

        monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
        monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")

        call_count = {"n": 0}
        def fake_run(cmd, cwd, **kwargs):
            call_count["n"] += 1
            (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

        dirs = iter([tenant_a_dir, tenant_b_dir])
        monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir", lambda: next(dirs))

        pdf_a = latex_export.generate_resume_latex(resume_text="", company="Boeing", role="SWE")
        pdf_b = latex_export.generate_resume_latex(resume_text="", company="Boeing", role="SWE")

        assert "oid-aaa" in str(pdf_a)
        assert "oid-bbb" in str(pdf_b)
        # Paths share nothing below tmp — they are in completely separate tenant trees
        assert pdf_a.parent != pdf_b.parent
        # Neither path is a parent of the other (no shared workspace root)
        assert not str(pdf_a).startswith(str(pdf_b.parent))
        assert not str(pdf_b).startswith(str(pdf_a.parent))
