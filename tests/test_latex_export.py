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
        return Path("cover_letter_Equifax.pdf")

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
        return Path("resume_Equifax.pdf")

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
# role_title injection into \def\role (resume header)
# ---------------------------------------------------------------------------

def test_inject_role_title_replaces_macro():
    src = r"\def\role{Full-Stack Software Engineer}" + "\n\\input{_header}"
    out = latex_export._inject_role_title(src, "Full-Stack AI Engineer")
    assert r"\def\role{Full-Stack AI Engineer}" in out
    assert "Full-Stack Software Engineer" not in out
    # Surrounding content is preserved.
    assert "\\input{_header}" in out


def test_inject_role_title_blank_is_noop():
    src = r"\def\role{Full-Stack Software Engineer}"
    assert latex_export._inject_role_title(src, "") == src
    assert latex_export._inject_role_title(src, "   ") == src


def test_inject_role_title_no_macro_returns_unchanged():
    src = r"\documentclass{article}\begin{document}hi\end{document}"
    assert latex_export._inject_role_title(src, "Staff Engineer") == src


def test_inject_role_title_escapes_latex_specials():
    src = r"\def\role{Full-Stack Software Engineer}"
    out = latex_export._inject_role_title(src, "R&D Engineer")
    assert r"\def\role{R\&D Engineer}" in out


def test_inject_role_title_replaces_only_first_macro():
    src = r"\def\role{One}" + "\n" + r"\def\role{Two}"
    out = latex_export._inject_role_title(src, "Injected")
    assert out.count(r"\def\role{Injected}") == 1
    # The second macro is left untouched (only the header occurrence is set).
    assert r"\def\role{Two}" in out


def test_inject_role_title_strips_surrounding_whitespace():
    src = r"\def\role{Old}"
    out = latex_export._inject_role_title(src, "  Platform Engineer  ")
    assert r"\def\role{Platform Engineer}" in out


def test_export_resume_latex_tool_forwards_role_title(monkeypatch):
    """The MCP wrapper must pass role_title through to the generator so the
    header role becomes a first-class option."""
    captured = {}

    def fake_generate(*, resume_text, company, role, role_title, output_filename):
        captured["role_title"] = role_title
        return Path("resume_Acme.pdf")

    monkeypatch.setattr(latex_export, "generate_resume_latex", fake_generate)

    result = export.export_resume_latex(
        company="Acme", role="Staff Engineer", role_title="Full-Stack AI Engineer",
    )
    assert "PDF exported (LaTeX)" in result
    assert captured["role_title"] == "Full-Stack AI Engineer"


def test_export_resume_latex_tool_role_title_defaults_blank(monkeypatch):
    """Default role_title is blank so the template's own \\def\\role is used
    (backward-compatible 'compile what's there' behavior)."""
    captured = {}

    def fake_generate(*, resume_text, company, role, role_title, output_filename):
        captured["role_title"] = role_title
        return Path("resume_Acme.pdf")

    monkeypatch.setattr(latex_export, "generate_resume_latex", fake_generate)

    export.export_resume_latex(company="Acme", role="SWE")
    assert captured["role_title"] == ""


# ---------------------------------------------------------------------------
# _inject_def / _inject_identity — generalized header macro injection
# ---------------------------------------------------------------------------

def test_inject_def_replaces_named_macro():
    src = r"\def\name{Old Name}" + "\n" + r"\def\city{Old City}"
    out = latex_export._inject_def(src, "name", "New Name")
    assert r"\def\name{New Name}" in out
    # A different macro is untouched.
    assert r"\def\city{Old City}" in out


def test_inject_def_blank_value_is_noop():
    src = r"\def\name{Old Name}"
    assert latex_export._inject_def(src, "name", "") == src
    assert latex_export._inject_def(src, "name", "   ") == src


def test_inject_def_absent_macro_returns_unchanged():
    src = r"\def\name{Old Name}"
    assert latex_export._inject_def(src, "phone", "555-1234") == src


def test_inject_def_escapes_latex_specials():
    src = r"\def\city{Old}"
    out = latex_export._inject_def(src, "city", "Tampa & Bay")
    assert r"\def\city{Tampa \& Bay}" in out


def test_inject_def_replaces_only_first_occurrence():
    src = r"\def\name{One}" + "\n" + r"\def\name{Two}"
    out = latex_export._inject_def(src, "name", "Injected")
    assert out.count(r"\def\name{Injected}") == 1
    assert r"\def\name{Two}" in out


def test_inject_def_unknown_macro_is_noop():
    """Only the fixed set of known header macros may be overridden; any other
    name is ignored (no dynamic pattern is ever built from the argument)."""
    src = r"\def\name{Old}"
    assert latex_export._inject_def(src, "evilmacro", "x") == src
    assert latex_export._inject_def(src, "write18", "rm -rf /") == src


# ---------------------------------------------------------------------------
# _sanitize_macro_value — taint boundary for caller-supplied header values
# ---------------------------------------------------------------------------

def test_sanitize_macro_value_blank_returns_empty():
    assert latex_export._sanitize_macro_value("") == ""
    assert latex_export._sanitize_macro_value("   ") == ""


def test_sanitize_macro_value_strips_control_chars_and_newlines():
    out = latex_export._sanitize_macro_value("Sen\nior\tEngi\x00neer\r")
    # Control characters (newline, tab, NUL, CR) are removed entirely.
    assert out == "SeniorEngineer"


def test_sanitize_macro_value_caps_length():
    long_value = "A" * 500
    out = latex_export._sanitize_macro_value(long_value)
    assert len(out) == latex_export._MACRO_VALUE_MAX_LEN


def test_sanitize_macro_value_escapes_latex_after_cleaning():
    # A LaTeX command payload is neutralized: the leading backslash is escaped
    # so \write18 can no longer start a control sequence.
    out = latex_export._sanitize_macro_value(r"\write18{touch pwned}")
    assert "\\write18" not in out          # no live command survives
    assert r"\textbackslash" in out         # the backslash was neutralized


def test_inject_role_title_neutralizes_latex_injection():
    """A role_title carrying a LaTeX command must be defused at injection: no
    live control sequence survives into the header macro."""
    src = r"\def\role{Full-Stack Software Engineer}"
    out = latex_export._inject_role_title(src, r"Engineer}\input{/etc/passwd}")
    # The injected close-brace + \input never becomes live LaTeX: the backslash
    # is neutralized and the breakout brace is escaped.
    assert r"\input{/etc/passwd}" not in out
    assert r"\textbackslash" in out


def test_inject_role_title_strips_newlines():
    src = r"\def\role{Old}"
    out = latex_export._inject_role_title(src, "Staff\nEngineer")
    assert r"\def\role{StaffEngineer}" in out


def test_inject_identity_overrides_all_contact_macros():
    src = "\n".join([
        r"\def\name{PLACEHOLDER}",
        r"\def\phone{000}",
        r"\def\city{Nowhere}",
        r"\def\email{x@y.z}",
        r"\def\linkedin{ph}",
        r"\def\github{ph}",
        r"\def\role{Keep Me}",
    ])
    identity = {
        "name": "Ada Lovelace", "phone": "555-000-1111", "city": "London, UK",
        "email": "ada@example.org", "linkedin": "adalovelace", "github": "adaGH",
    }
    out = latex_export._inject_identity(src, identity)
    assert r"\def\name{Ada Lovelace}" in out
    assert r"\def\phone{555-000-1111}" in out
    assert r"\def\city{London, UK}" in out
    assert r"\def\email{ada@example.org}" in out
    assert r"\def\linkedin{adalovelace}" in out
    assert r"\def\github{adaGH}" in out
    # Non-identity macros (role) are never touched by identity injection.
    assert r"\def\role{Keep Me}" in out
    assert "PLACEHOLDER" not in out


def test_inject_identity_skips_absent_macros():
    """A template missing some contact macros still injects the ones present."""
    src = r"\def\name{PLACEHOLDER}"  # no phone/email/etc macros
    out = latex_export._inject_identity(src, {"name": "Ada", "phone": "555"})
    assert r"\def\name{Ada}" in out
    # No phone macro existed, so nothing spurious was added.
    assert r"\def\phone" not in out


# ---------------------------------------------------------------------------
# Per-user identity injection in the resume pipeline (multi-tenant PII safety)
# ---------------------------------------------------------------------------

def _make_identity_resume(latex_dir: Path) -> None:
    """Write a resume.tex with placeholder contact macros into latex_dir."""
    (latex_dir / "resume.tex").write_text(
        "\n".join([
            r"\def\name{YOUR FULL NAME}",
            r"\def\phone{555-867-5309}",
            r"\def\city{Your City, ST}",
            r"\def\email{you@example.com}",
            r"\def\linkedin{yourhandle}",
            r"\def\github{YourGitHub}",
            r"\def\role{Full-Stack Software Engineer}",
            r"\begin{document}\end{document}",
        ]),
        encoding="utf-8",
    )


def test_generate_resume_injects_active_user_identity(monkeypatch, tmp_path):
    """The compiled temp copy must carry the CALLING user's identity, never the
    template's placeholder contact macros. This is the multi-tenant PII guard:
    a shared bundled template must never emit another user's details."""
    latex_dir = tmp_path / "latex_assets"
    latex_dir.mkdir()
    _make_identity_resume(latex_dir)

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export, "_user_identity", lambda: {
        "name": "Ada Lovelace", "phone": "555-000-1111", "city": "London, UK",
        "email": "ada@example.org", "linkedin": "adalovelace", "github": "adaGH",
    })
    monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir",
                        lambda: tmp_path / "out")

    captured = {}

    def fake_run(cmd, cwd, **kwargs):
        captured["tex"] = (Path(cwd) / "resume.tex").read_text(encoding="utf-8")
        (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

    latex_export.generate_resume_latex(resume_text="", company="Acme", role="SWE")

    tex = captured["tex"]
    assert r"\def\name{Ada Lovelace}" in tex
    assert r"\def\email{ada@example.org}" in tex
    assert r"\def\github{adaGH}" in tex
    # The template placeholders must be gone from the compiled copy.
    assert "YOUR FULL NAME" not in tex
    assert "you@example.com" not in tex
    # The source .tex on disk is never mutated.
    assert "YOUR FULL NAME" in (latex_dir / "resume.tex").read_text(encoding="utf-8")


def test_generate_resume_identity_param_overrides_user_identity(monkeypatch, tmp_path):
    """An explicit identity= override beats the active user's config identity."""
    latex_dir = tmp_path / "latex_assets"
    latex_dir.mkdir()
    _make_identity_resume(latex_dir)

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export, "_user_identity", lambda: {
        "name": "Ada Lovelace", "phone": "555-000-1111", "city": "London, UK",
        "email": "ada@example.org", "linkedin": "adalovelace", "github": "adaGH",
    })
    monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir",
                        lambda: tmp_path / "out")

    captured = {}

    def fake_run(cmd, cwd, **kwargs):
        captured["tex"] = (Path(cwd) / "resume.tex").read_text(encoding="utf-8")
        (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

    latex_export.generate_resume_latex(
        resume_text="", company="Acme", role="SWE",
        identity={"name": "Grace Hopper"},
    )

    tex = captured["tex"]
    assert r"\def\name{Grace Hopper}" in tex
    # Unspecified override fields fall back to the active user's identity.
    assert r"\def\email{ada@example.org}" in tex


def test_generate_resume_injects_role_alongside_identity(monkeypatch, tmp_path):
    """role_title still injects even with identity injection now always running."""
    latex_dir = tmp_path / "latex_assets"
    latex_dir.mkdir()
    _make_identity_resume(latex_dir)

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export, "_user_identity", lambda: {
        "name": "Ada Lovelace", "phone": "5", "city": "L", "email": "a@b.c",
        "linkedin": "a", "github": "a",
    })
    monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir",
                        lambda: tmp_path / "out")

    captured = {}

    def fake_run(cmd, cwd, **kwargs):
        captured["tex"] = (Path(cwd) / "resume.tex").read_text(encoding="utf-8")
        (Path(cwd) / "resume.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export.subprocess, "run", fake_run)

    latex_export.generate_resume_latex(
        resume_text="", company="Acme", role="SWE", role_title="Senior AI Engineer",
    )

    assert r"\def\role{Senior AI Engineer}" in captured["tex"]
    assert r"\def\name{Ada Lovelace}" in captured["tex"]


def test_bundled_resume_template_carries_no_owner_pii():
    """Regression guard: the shipped sample template AND every bundled section
    file must contain only generic placeholder content — never the owner's real
    identity, employers, schools, or side projects."""
    assets = latex_export._BUNDLED_LATEX_ASSETS_DIR
    files = [assets / "resume.tex", *sorted((assets / "sections").glob("*.tex"))]
    forbidden = [
        "frank", "macbride", "frankvmacbride", "305.490", "jobcontext",
        "general motors", "retrospicam", "livevox", "florida international",
        "eagle scout", "magna cum laude",
    ]
    for f in files:
        lowered = f.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in lowered, f"{token!r} leaked in {f.name}"
    # Generic placeholders are present in the header.
    header = (assets / "resume.tex").read_text(encoding="utf-8")
    assert r"\def\name{YOUR FULL NAME}" in header
    assert r"\def\email{you@example.com}" in header
    assert r"\def\website{}" in header


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

    def test_output_filename_traversal_is_stripped_to_basename(self, monkeypatch, tmp_path):
        """A caller-supplied output_filename with path components must not escape
        the tenant output dir: only the basename is honored (path-traversal guard)."""
        out_dir = tmp_path / "users" / "oid-t" / "workspace" / "03-Resume-PDFs"
        latex_dir = tmp_path / "latex_assets"
        latex_dir.mkdir()
        (latex_dir / "resume.tex").write_text("", encoding="utf-8")

        monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
        monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
        monkeypatch.setattr(latex_export.subprocess, "run",
                            self._fake_tectonic_run("resume.pdf"))
        monkeypatch.setattr(latex_export.cfg, "get_active_resume_pdfs_dir", lambda: out_dir)

        pdf = latex_export.generate_resume_latex(
            resume_text="", company="Acme", role="SWE",
            output_filename="../../../../etc/passwd",
        )

        # The written PDF stays inside the tenant dir, named by basename only.
        assert pdf.parent == out_dir
        assert pdf.name == "passwd.pdf"
        assert ".." not in str(pdf.relative_to(out_dir))


# ---------------------------------------------------------------------------
# read_latex_asset tests
# ---------------------------------------------------------------------------

def test_read_latex_asset_returns_file_contents(monkeypatch, tmp_path):
    """read_latex_asset returns bundled default content when no tenant overlay exists."""
    bundled = tmp_path / "latex_assets"
    bundled.mkdir()
    (bundled / "TLCresume.sty").write_text("\\ProvidesPackage{TLCresume}", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)
    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tmp_path / "tenant")

    result = latex_export.read_latex_asset("TLCresume.sty")
    assert "ProvidesPackage" in result


def test_read_latex_asset_reads_section_file(monkeypatch, tmp_path):
    """read_latex_asset resolves files in sections/ subdirectory."""
    bundled = tmp_path / "latex_assets"
    sections = bundled / "sections"
    sections.mkdir(parents=True)
    (sections / "synopsis.tex").write_text("\\noindent My summary.", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)
    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tmp_path / "tenant")

    result = latex_export.read_latex_asset("sections/synopsis.tex")
    assert "My summary" in result


def test_read_latex_asset_rejects_unlisted_file(monkeypatch, tmp_path):
    """read_latex_asset raises PermissionError for files not in the allowlist."""
    bundled = tmp_path / "latex_assets"
    bundled.mkdir()
    (bundled / "secret.tex").write_text("secret", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    import pytest
    with pytest.raises(PermissionError, match="allowlist"):
        latex_export.read_latex_asset("secret.tex")


def test_read_latex_asset_raises_if_file_missing(monkeypatch, tmp_path):
    """read_latex_asset raises FileNotFoundError when an allowlisted file doesn't exist."""
    bundled = tmp_path / "latex_assets"
    bundled.mkdir()
    # Don't create TLCresume.sty

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)
    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tmp_path / "tenant")

    import pytest
    with pytest.raises(FileNotFoundError):
        latex_export.read_latex_asset("TLCresume.sty")


# ---------------------------------------------------------------------------
# write_latex_section tests
# ---------------------------------------------------------------------------

def test_write_latex_section_creates_file(monkeypatch, tmp_path):
    """write_latex_section writes content to the tenant sections/ dir and returns confirmation."""
    tenant = tmp_path / "tenant"
    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)

    result = latex_export.write_latex_section("synopsis.tex", "\\noindent Tailored summary.")

    target = tenant / "sections" / "synopsis.tex"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "\\noindent Tailored summary."
    assert "✓" in result
    assert "synopsis.tex" in result


def test_write_latex_section_overwrites_existing_content(monkeypatch, tmp_path):
    """write_latex_section replaces existing file content."""
    tenant = tmp_path / "tenant"
    (tenant / "sections").mkdir(parents=True)
    (tenant / "sections" / "synopsis.tex").write_text("old content", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)

    latex_export.write_latex_section("synopsis.tex", "new content")

    assert (tenant / "sections" / "synopsis.tex").read_text(encoding="utf-8") == "new content"


def test_write_latex_section_rejects_unlisted_file(monkeypatch, tmp_path):
    """write_latex_section raises PermissionError for files not in the writable allowlist."""
    bundled = tmp_path / "latex_assets"
    sections = bundled / "sections"
    sections.mkdir(parents=True)

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    import pytest
    with pytest.raises(PermissionError, match="allowlist"):
        latex_export.write_latex_section("TLCresume.sty", "malicious override")


def test_write_latex_section_rejects_path_traversal(monkeypatch, tmp_path):
    """write_latex_section rejects filenames not in the allowlist (blocks path traversal)."""
    bundled = tmp_path / "latex_assets"
    bundled.mkdir()

    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    import pytest
    with pytest.raises(PermissionError):
        latex_export.write_latex_section("../../server.py", "pwned")


def test_read_write_roundtrip(monkeypatch, tmp_path):
    """Write a section then read it back — content must survive the roundtrip."""
    tenant = tmp_path / "tenant"
    bundled = tmp_path / "latex_assets"
    (bundled / "sections").mkdir(parents=True)

    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    content = "\\begin{zitemize}\n\\item Led migration.\n\\end{zitemize}"
    latex_export.write_latex_section("experience.tex", content)

    result = latex_export.read_latex_asset("sections/experience.tex")
    assert "Led migration" in result


# ---------------------------------------------------------------------------
# Tenant isolation regression tests (cross-tenant leak guard)
# ---------------------------------------------------------------------------

def test_write_latex_section_writes_to_tenant_not_bundled(monkeypatch, tmp_path):
    """Section writes must land in the per-tenant overlay, never the shared
    bundled template dir that every tenant compiles from."""
    tenant = tmp_path / "tenant"
    bundled = tmp_path / "latex_assets"
    (bundled / "sections").mkdir(parents=True)

    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    latex_export.write_latex_section("experience.tex", "TENANT PRIVATE CONTENT")

    assert (tenant / "sections" / "experience.tex").read_text(encoding="utf-8") == "TENANT PRIVATE CONTENT"
    # The shared bundled template must be left untouched.
    assert not (bundled / "sections" / "experience.tex").exists()


def test_read_latex_asset_prefers_tenant_overlay(monkeypatch, tmp_path):
    """A tenant's own overlay copy wins over the bundled default."""
    tenant = tmp_path / "tenant"
    bundled = tmp_path / "latex_assets"
    (tenant / "sections").mkdir(parents=True)
    (bundled / "sections").mkdir(parents=True)
    (tenant / "sections" / "synopsis.tex").write_text("TENANT VERSION", encoding="utf-8")
    (bundled / "sections" / "synopsis.tex").write_text("BUNDLED DEFAULT", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    assert latex_export.read_latex_asset("sections/synopsis.tex") == "TENANT VERSION"


def test_read_latex_asset_falls_back_to_bundled_default(monkeypatch, tmp_path):
    """With no tenant overlay, read returns the bundled read-only default."""
    tenant = tmp_path / "tenant"  # never created
    bundled = tmp_path / "latex_assets"
    (bundled / "sections").mkdir(parents=True)
    (bundled / "sections" / "synopsis.tex").write_text("BUNDLED DEFAULT", encoding="utf-8")

    monkeypatch.setattr(latex_export, "_tenant_latex_assets_dir", lambda: tenant)
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    assert latex_export.read_latex_asset("sections/synopsis.tex") == "BUNDLED DEFAULT"


def test_latex_section_writes_are_tenant_isolated(monkeypatch, tmp_path):
    """End-to-end isolation: content written under tenant A's data-folder context
    must be invisible to tenant B (who sees the bundled default instead).
    Exercises the real ContextVar resolver via set_data_folder."""
    from lib import user_context

    bundled = tmp_path / "latex_assets"
    (bundled / "sections").mkdir(parents=True)
    (bundled / "sections" / "experience.tex").write_text(
        "BUNDLED DEFAULT EXPERIENCE", encoding="utf-8"
    )
    monkeypatch.setattr(latex_export, "_BUNDLED_LATEX_ASSETS_DIR", bundled)

    tenant_a = tmp_path / "users" / "oid-a"
    tenant_b = tmp_path / "users" / "oid-b"

    # Tenant A writes private content.
    tok_a = user_context.set_data_folder(tenant_a)
    try:
        latex_export.write_latex_section("experience.tex", "TENANT A PRIVATE RESUME")
    finally:
        user_context.reset_data_folder(tok_a)

    # Tenant B reads the same logical asset — must NOT see A's content.
    tok_b = user_context.set_data_folder(tenant_b)
    try:
        b_view = latex_export.read_latex_asset("sections/experience.tex")
    finally:
        user_context.reset_data_folder(tok_b)
    assert "TENANT A PRIVATE RESUME" not in b_view
    assert "BUNDLED DEFAULT EXPERIENCE" in b_view

    # And A can still read back their own content.
    tok_a2 = user_context.set_data_folder(tenant_a)
    try:
        a_view = latex_export.read_latex_asset("sections/experience.tex")
    finally:
        user_context.reset_data_folder(tok_a2)
    assert "TENANT A PRIVATE RESUME" in a_view

