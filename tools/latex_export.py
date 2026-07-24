"""
Pipeline A — LaTeX cover letter export (tectonic)
==================================================
Writes generated prose into a templated cover_letter.tex, compiles it with
tectonic, and copies the resulting PDF to the configured output directory.

This is the *primary* cover letter export pipeline — it produces output
visually identical to the manually-compiled versions in frank-resume-latex/.

Pipeline B (weasyprint/HTML) lives in tools/export.py and is kept as a
fallback for environments where tectonic is unavailable.

Public entry points
-------------------
generate_cover_letter_latex(body, company, role, *, output_dir=None) -> Path
    Full pipeline: template → compile → copy.  Returns the final PDF path.

list_latex_output_pdfs() -> list[Path]
    Returns existing PDFs from the latex output/ folder, sorted newest-first.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib import config as cfg

# ---------------------------------------------------------------------------
# LaTeX cover-letter template
# Mirrors cover_letter.tex exactly, but the body between the marker comments
# is replaced at runtime.  The \def values come from the static source so
# they stay in sync with the real template automatically.
# ---------------------------------------------------------------------------

_TEX_TEMPLATE = r"""\documentclass[letter,11pt]{{article}}
\usepackage[utf8]{{inputenc}}

\usepackage{{TLCresume}}
\usepackage{{parskip}}
\setlength{{\parskip}}{{1.4em plus 0.2em}}
\geometry{{margin=.3in, top=.3in, bottom=.5in}}
\raggedright

\def\name{{{name}}}
\def\phone{{{phone}}}
\def\city{{{city}}}
\def\email{{{email}}}
\def\linkedin{{{linkedin}}}
\def\github{{{github}}}
\def\website{{{website}}}
\def\role{{{role_title}}}

\input{{_header}}
\begin{{document}}
\pagestyle{{empty}}
\printheader

\vspace{{24pt}}

\begin{{flushright}}
{date}
\end{{flushright}}

\vspace{{8pt}}

Dear Hiring Manager,

{body}

\vspace{{8pt}}

\noindent Kindest Regards, \\[10pt]
\name

\end{{document}}
"""

# Generic fallback identity values used when no contact block is present in
# config.json.  These are intentionally neutral placeholders — they must never
# contain any real person's data so that an unconfigured workspace does not
# expose someone else's information.
_AUTHOR_DEFAULTS = {
    "name":       r"YOUR FULL NAME",
    "phone":      r"555-867-5309",
    "city":       r"Your City, ST",
    "email":      r"you@example.com",
    "linkedin":   r"yourhandle",
    "github":     r"YourGitHub",
}

_BUNDLED_LATEX_ASSETS_DIR = Path(__file__).resolve().parent.parent / "templates" / "latex_assets"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latex_dir() -> Path | None:
    """Return the frank-resume-latex directory from config, or None if unset/missing.

    Returns None instead of raising so callers can fall back to bundled assets
    (the AKS container case where latex_resume_dir is not configured).
    """
    d = cfg.LATEX_RESUME_DIR
    if d is None or not str(d).strip():
        return None
    if not d.exists():
        return None
    return d


def _tenant_latex_assets_dir() -> Path:
    """Return the per-request writable LaTeX assets overlay directory.

    Resolves through the tenant-aware workspace resolver
    (``cfg.get_active_workspace_folder``), so an authenticated guest gets
    ``data/users/{oid}/workspace/latex_assets`` and the owner / local dev gets
    their own workspace copy. The bundled ``templates/latex_assets`` dir is a
    shared, READ-ONLY source of defaults only: user-supplied section content
    must never be written there or it would leak across tenants (every tenant
    compiles from the same bundled path).
    """
    return cfg.get_active_workspace_folder() / "latex_assets"


def _user_identity() -> dict[str, str]:
    """Read contact info from the active user's config.json at call time.

    Falls back to _AUTHOR_DEFAULTS so local dev / Frank's own partition
    still works without any extra setup.  Per-user callers (beta testers)
    get their own name/email on the generated document.

    Per-field fallback: any blank value in the contact block is replaced
    with the corresponding placeholder so the LaTeX template never receives
    an empty string (which causes compilation errors on fields like \\name
    that are rendered directly into the document).
    """
    contact = cfg.get_contact_info()

    linkedin = str(contact.get("linkedin", "") or "")
    linkedin = linkedin.replace("https://www.linkedin.com/in/", "").replace("www.linkedin.com/in/", "").strip("/")
    github = str(contact.get("github", "") or "")
    github = github.replace("https://www.github.com/", "").replace("www.github.com/", "").replace("https://github.com/", "").strip("/")
    # Personal site: _header.tex renders \href{https://\website}{\website},
    # so the value must be scheme-less (a scheme would double-prefix). Unlike
    # the other fields there is deliberately NO placeholder fallback — the
    # header's \ifx\website\empty guard hides the third link entirely when
    # unconfigured, and a fake placeholder URL would render as a real link.
    website = str(contact.get("website", "") or "")
    website = re.sub(r"^https?://", "", website.strip()).strip("/")
    return {
        "name":     str(contact.get("name", "") or "") or _AUTHOR_DEFAULTS["name"],
        "phone":    str(contact.get("phone", "") or "") or _AUTHOR_DEFAULTS["phone"],
        "city":     str(contact.get("city", "") or "") or _AUTHOR_DEFAULTS["city"],
        "email":    str(contact.get("email", "") or "") or _AUTHOR_DEFAULTS["email"],
        "linkedin": linkedin or _AUTHOR_DEFAULTS["linkedin"],
        "github":   github or _AUTHOR_DEFAULTS["github"],
        "website":  website,
    }


def _escape_latex(text: str) -> str:
    """Basic LaTeX special-character escaping for prose paragraphs.

    Leaves ellipses (``...'') and common punctuation intact; only escapes
    characters that would break compilation.
    """
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    return text


def _prose_to_tex(prose: str) -> str:
    """Convert plain prose (4 paragraphs, separated by blank lines) to LaTeX.

    Each blank-line-separated block becomes a paragraph.  Smart-quote
    conversion is left to LaTeX's default inputenc handling.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", prose.strip()) if p.strip()]
    return "\n\n".join(_escape_latex(p) for p in paragraphs)


def _tectonic_bin() -> str:
    """Locate the tectonic binary, preferring the system PATH."""
    found = shutil.which("tectonic")
    if found:
        return found
    # Common Homebrew / Cargo install locations
    for candidate in [
        "/opt/homebrew/bin/tectonic",
        "/usr/local/bin/tectonic",
        str(Path.home() / ".cargo/bin/tectonic"),
    ]:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "tectonic not found.  Install via: brew install tectonic"
    )


def _pdflatex_bin() -> str | None:
    """Locate a ``pdflatex`` binary (TeX Live / MiKTeX), or None if unavailable.

    Used as a fallback compiler when tectonic is not installed, or when it is
    installed but cannot download its support bundle (offline or
    network-restricted environments such as locked-down CI/cloud sandboxes).
    Unlike ``_tectonic_bin`` this returns None rather than raising, so the
    caller can decide whether a fallback is possible.
    """
    found = shutil.which("pdflatex")
    if found:
        return found
    for candidate in [
        "/usr/bin/pdflatex",
        "/usr/local/bin/pdflatex",
        "/Library/TeX/texbin/pdflatex",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def _resolve_support_file(latex_src: Path | None, name: str) -> Path:
    """Resolve a required LaTeX support file from workspace or bundled assets."""
    if latex_src is not None:
        candidate = latex_src / name
        if candidate.exists():
            return candidate
    bundled = _BUNDLED_LATEX_ASSETS_DIR / name
    if bundled.exists():
        return bundled
    raise FileNotFoundError(
        f"Required LaTeX support file not found: {name}. "
        f"Checked {'workspace and ' if latex_src else ''}bundled assets at {_BUNDLED_LATEX_ASSETS_DIR}."
    )


def _compile_tex(tex_file: Path, tmp_path: Path, expected_pdf: Path) -> Path:
    """Compile ``tex_file`` to PDF inside ``tmp_path``, returning ``expected_pdf``.

    Tries tectonic first (the primary engine, which produces output identical
    to the manually-compiled letters).  If tectonic is unavailable, or it runs
    but fails — most commonly because it cannot reach its support-bundle host
    in an offline/firewalled environment — it falls back to a local TeX Live
    ``pdflatex`` install.  Two pdflatex passes are run so ``hyperref`` links
    resolve.  Raises RuntimeError aggregating both engines' errors only when
    neither can produce the PDF.
    """
    errors: list[str] = []

    try:
        tectonic = _tectonic_bin()
    except FileNotFoundError as exc:
        tectonic = None
        errors.append(str(exc))

    if tectonic is not None:
        result = subprocess.run(
            [tectonic, str(tex_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and expected_pdf.exists():
            return expected_pdf
        errors.append(f"tectonic compilation failed:\n{result.stderr}\n{result.stdout}")

    pdflatex = _pdflatex_bin()
    if pdflatex is not None:
        result = None
        # nonstopmode (without -halt-on-error) lets pdflatex recover from
        # non-fatal issues and still emit a PDF, mirroring tectonic's leniency;
        # success is judged by whether the PDF was actually produced.
        for _ in range(2):  # second pass resolves hyperref references
            result = subprocess.run(
                [pdflatex, "-interaction=nonstopmode", str(tex_file)],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
        if expected_pdf.exists():
            return expected_pdf
        tail = (result.stdout[-2000:] if result else "")
        errors.append(f"pdflatex compilation failed:\n{tail}")
    else:
        errors.append("pdflatex not found (install a TeX Live distribution to enable the fallback).")

    raise RuntimeError(
        "LaTeX compilation failed; tried tectonic then pdflatex.\n\n" + "\n\n".join(errors)
    )


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def generate_cover_letter_latex(
    body: str,
    company: str,
    role: str,
    *,
    role_title: str = "Full Stack Software Engineer",
    letter_date: str = "",
    output_dir: Path | None = None,
    identity: dict[str, str] | None = None,
) -> Path:
    """Pipeline A — render a cover letter via LaTeX/tectonic.

    Args:
        body:        Plain-prose cover letter body (4 paragraphs, ~325 words).
                     May contain basic punctuation; special LaTeX chars are
                     escaped automatically.
        company:     Target company name (used only in the output filename).
        role:        Target role / job title (used only in the output filename).
        role_title:  Value for the \\role macro in the LaTeX header.
                     Defaults to Frank's standard title.
        letter_date: Right-aligned date printed under the letterhead. Defaults
                 to today in 'Month D, YYYY' format when blank.
        output_dir:  Where to write the final PDF.  Defaults to the workspace
             cover-letter PDF folder so dashboard previews can find it.
        identity:    Optional contact/identity overrides for demo output.
                 Supported keys match _AUTHOR_DEFAULTS: name, phone, city,
                 email, linkedin, github. Defaults preserve Frank's data.

    Returns:
        Path to the compiled PDF.
    """
    latex_src = _latex_dir()  # None when not configured (AKS) — bundled assets used

    if output_dir is None:
        final_output_dir = cfg.get_active_cover_letter_pdfs_dir()
    else:
        final_output_dir = Path(output_dir)
    final_output_dir.mkdir(parents=True, exist_ok=True)

    # Build a safe filename slug
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")
    from datetime import date
    today = date.today()
    dated = today.strftime("%Y%m%d")
    pdf_name = f"cover_letter_{slug}_{dated}.pdf"
    final_pdf = final_output_dir / pdf_name

    # Default the printed letter date to today (e.g. 'June 7, 2026'). Use
    # today.day directly instead of '%-d' which is Linux-only and fails on Windows.
    if not letter_date:
        letter_date = f"{today.strftime('%B')} {today.day}, {today.year}"

    author = {**_user_identity(), **(identity or {})}
    author = {key: _escape_latex(value) for key, value in author.items()}

    tex_body = _prose_to_tex(body)
    tex_src = _TEX_TEMPLATE.format(
        **author,
        role_title=_escape_latex(role_title),
        date=_escape_latex(letter_date),
        body=tex_body,
    )

    # Compile in a temp directory that shares the latex project's working
    # directory so that \input{_header} and \usepackage{TLCresume} resolve.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / "cover_letter.tex"
        tex_file.write_text(tex_src, encoding="utf-8")

        # Symlink required support files into the temp dir.
        # Prefer workspace assets, fall back to bundled copies shipped with app.
        for name in ["_header.tex", "TLCresume.sty"]:
            src_file = _resolve_support_file(latex_src, name)
            (tmp_path / name).symlink_to(src_file)

        compiled_pdf = _compile_tex(tex_file, tmp_path, tmp_path / "cover_letter.pdf")
        shutil.copy2(compiled_pdf, final_pdf)

    return final_pdf


# ---------------------------------------------------------------------------
# Resume pipeline
# ---------------------------------------------------------------------------

_RESUME_TEX = "resume.tex"

#: Header macros the resume pipeline may override on a compile-time copy. A
#: *fixed* set of literal names — never built from caller input — so the
#: matchers below are fully static (no request-influenced regex construction).
_MACRO_NAMES: tuple[str, ...] = (
    "role", "name", "phone", "city", "email", "linkedin", "github", "website",
)

#: Precompiled ``\def\<macro>{...}`` matchers, one per known macro. Built from
#: the literal tuple above (not from a parameter), so an injected header value
#: can never influence the pattern that gets compiled.
_MACRO_DEF_PATTERNS: dict[str, "re.Pattern[str]"] = {
    name: re.compile(r"\\def\\" + name + r"\{[^}]*\}") for name in _MACRO_NAMES
}

#: Back-compat alias for the role matcher (referenced by callers/tests).
_ROLE_DEF_RE = _MACRO_DEF_PATTERNS["role"]

#: Header identity macros populated from the active user's contact info so a
#: compiled resume never carries another user's name/contact. Mirrors the
#: cover-letter pipeline's _user_identity() field set.
#: \website has no placeholder default: blank means "no third header link"
#: (resume.tex ships \def\website{} and _header.tex guards on \ifx\website\empty),
#: and _inject_def's blank-is-no-op behavior preserves exactly that.
_IDENTITY_MACROS = ("name", "phone", "city", "email", "linkedin", "github", "website")

#: Defensive ceiling on an injected header value (name/role are short by nature).
_MACRO_VALUE_MAX_LEN = 200

#: Control characters (incl. CR/LF/TAB) are never valid in a single-line header
#: macro; stripping them is the sanitizer boundary applied to every
#: caller-supplied identity/role string before it enters the compiled .tex.
_MACRO_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_macro_value(value: str) -> str:
    """Validate and neutralize a caller-supplied header macro value.

    Injected values (``role_title`` from the export tool, or per-user identity
    fields) are written into the ``resume.tex`` that tectonic subsequently
    compiles, so an unsanitized string could otherwise smuggle LaTeX control
    sequences into the document. Every value is therefore, in order:

      1. stripped of control characters / newlines (allowlist boundary),
      2. capped to _MACRO_VALUE_MAX_LEN characters, then
      3. LaTeX-escaped so ``\\``, ``{}``, ``$`` … become literal text and no
         character can begin a control sequence.

    Returns "" for blank/whitespace input so callers treat it as "leave the
    template's own macro untouched".
    """
    if not value or not value.strip():
        return ""
    cleaned = _MACRO_CONTROL_CHARS.sub("", value).strip()
    return _escape_latex(cleaned[:_MACRO_VALUE_MAX_LEN])


def _inject_def(tex_src: str, macro: str, value: str) -> str:
    """Return *tex_src* with its first ``\\def\\<macro>{...}`` set to *value*.

    Overrides a single header macro on a compile-time copy so the source .tex
    on disk is never mutated. *macro* must be one of the known header macros
    (_MACRO_NAMES); any other name — and a blank/absent value or macro — is a
    no-op. *value* is sanitized + LaTeX-escaped via _sanitize_macro_value
    before substitution; only the first occurrence is set.
    """
    pattern = _MACRO_DEF_PATTERNS.get(macro)
    if pattern is None:
        return tex_src
    safe = _sanitize_macro_value(value)
    if not safe:
        return tex_src
    replacement = "\\def\\" + macro + "{" + safe + "}"
    # Function replacement avoids backslash/group interpretation in the repl.
    new_src, n = pattern.subn(lambda _m: replacement, tex_src, count=1)
    return new_src if n else tex_src


def _inject_role_title(tex_src: str, role_title: str) -> str:
    """Set the resume header ``\\def\\role`` macro (see _inject_def).

    Powers the ``role_title`` first-class option: the header role is otherwise
    hard-coded in resume.tex (which callers cannot edit through the hosted MCP
    tools). Blank leaves the template's own role intact.
    """
    return _inject_def(tex_src, "role", role_title)


def _inject_identity(tex_src: str, identity: dict[str, str]) -> str:
    """Override the header contact macros (\\name, \\phone, ...) on a temp copy.

    Ensures a resume compiled from a shared template renders the *calling*
    user's identity, never whatever contact data is hard-coded in the source
    .tex. Fields absent/blank in *identity* leave that macro untouched. Values
    are passed raw (unescaped); _inject_def handles LaTeX escaping.
    """
    for macro in _IDENTITY_MACROS:
        tex_src = _inject_def(tex_src, macro, identity.get(macro, ""))
    return tex_src


def generate_resume_latex(
    resume_text: str,  # NOSONAR — reserved for future template injection
    company: str,
    role: str,
    *,
    role_title: str = "",
    output_filename: str = "",
    output_dir: Path | None = None,
    identity: dict[str, str] | None = None,
) -> Path:
    """Pipeline A — compile a custom LaTeX resume via tectonic.

    Looks for a ``resume.tex`` source file in ``latex_resume_dir`` and compiles
    it as-is with tectonic.  This is intentionally a "compile what's there"
    model so one-off custom resumes (e.g. a bespoke layout for a specific
    company) can be generated by dropping the right ``.tex`` into the project
    and calling this function without any template parsing.

    Args:
        resume_text:     Plain-text resume content.  Not used by this pipeline
                         directly (the .tex source governs layout), but kept
                         as a parameter for API symmetry with cover-letter
                         generation and for potential future template injection.
        company:         Target company (used in the output filename).
        role:            Target role (used in the output filename).
        role_title:      Injected into the resume's ``\\def\\role{...}`` header
                         macro at compile time (on a temp copy — the source
                         .tex is never modified). Blank leaves the template's
                         own role intact. LaTeX-escaped automatically.
        output_filename: Override the output PDF filename.  Defaults to
                         ``resume_{company}_{role}_{YYYYMMDD}.pdf``.
        output_dir:      Where to write the final PDF.  Defaults to the
                         configured workspace resume folder.
        identity:        Optional contact overrides (name, phone, city, email,
                         linkedin, github). Defaults to the active user's
                         config contact, so a shared template never emits
                         another user's details.

    Returns:
        Path to the compiled PDF.

    Raises:
        FileNotFoundError: If ``resume.tex`` is not found in ``latex_resume_dir``.
        RuntimeError: If tectonic compilation fails.
    """
    latex_src = _latex_dir()
    if latex_src is None:
        raise FileNotFoundError(
            "latex_resume_dir is not set or does not exist in config.json. "
            "Add the absolute path to your frank-resume-latex folder to use LaTeX resume export."
        )
    resume_tex = latex_src / _RESUME_TEX

    if not resume_tex.exists():
        raise FileNotFoundError(
            f"No resume.tex found in {latex_src}. "
            "To use LaTeX resume export, add a resume.tex source file to your "
            "latex_resume_dir. See the frank-resume-latex project for a starting template."
        )

    # Determine output directory — must use the tenant-scoped resolver so
    # multi-user deployments never write to the global workspace path.
    if output_dir is None:
        final_output_dir = cfg.get_active_resume_pdfs_dir()
    else:
        final_output_dir = Path(output_dir)
    final_output_dir.mkdir(parents=True, exist_ok=True)

    # Build filename. Strip any directory components from a caller-supplied
    # name (path-traversal guard) so output_filename can never redirect the
    # write outside the tenant-scoped output dir.
    if output_filename:
        output_filename = Path(output_filename).name
        pdf_name = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
    else:
        from datetime import date as _date
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")
        dated = _date.today().strftime("%Y%m%d")
        pdf_name = f"resume_{slug}_{dated}.pdf"
    final_pdf = final_output_dir / pdf_name

    tectonic = _tectonic_bin()

    # Compile in a temp dir that has all support files from latex_src available
    # so \usepackage{TLCresume} and \input{_header} resolve correctly.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Copy entire latex source dir tree (including sections/ subdirs) into
        # the temp workspace so \input{sections/skills} and friends resolve.
        shutil.copytree(str(latex_src), str(tmp_path), dirs_exist_ok=True)

        # Overlay the caller's per-tenant LaTeX assets (sections they tailored
        # via write_latex_section) on top of the shared source so their edits
        # win at compile time — and so no other tenant's sections can ever bleed
        # into this compile. Tenant assets live under the request-scoped
        # workspace, resolved by _tenant_latex_assets_dir().
        tenant_assets = _tenant_latex_assets_dir()
        if tenant_assets.exists():
            shutil.copytree(str(tenant_assets), str(tmp_path), dirs_exist_ok=True)

        # Override the header identity + role on the temp copy only, so the
        # source resume.tex on disk is never mutated AND a shared template
        # (e.g. the bundled assets used on AKS) can never emit another user's
        # contact details. _user_identity() falls back to generic placeholders
        # for users without their own configured contact block.
        author = {**_user_identity(), **(identity or {})}
        tmp_resume = tmp_path / _RESUME_TEX
        # tmp_resume is a fixed name inside our own TemporaryDirectory (never
        # caller-influenced), and every injected value is neutralized by
        # _sanitize_macro_value before it enters the document. A blank
        # role_title leaves the template's own role untouched.
        header_src = tmp_resume.read_text(encoding="utf-8")
        header_src = _inject_identity(header_src, author)
        header_src = _inject_role_title(header_src, role_title)
        with open(tmp_resume, "w", encoding="utf-8") as resume_fh:
            resume_fh.write(header_src)

        result = subprocess.run(
            [tectonic, str(tmp_path / _RESUME_TEX)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tectonic compilation failed:\n{result.stderr}\n{result.stdout}"
            )

        compiled_pdf = tmp_path / "resume.pdf"
        if not compiled_pdf.exists():
            raise FileNotFoundError(
                "tectonic reported success but resume.pdf was not produced."
            )

        shutil.copy2(compiled_pdf, final_pdf)

    return final_pdf


# ---------------------------------------------------------------------------
# LaTeX asset read / write helpers (server-side Claude content injection)
# ---------------------------------------------------------------------------

#: Allowlist of filenames Claude is permitted to read from the bundled assets.
_READABLE_LATEX_ASSETS: set[str] = {
    "TLCresume.sty",
    _RESUME_TEX,
    "_header.tex",
    "_warmup.tex",
    "sections/synopsis.tex",
    "sections/skills.tex",
    "sections/experience.tex",
    "sections/personalprojects.tex",
    "sections/education.tex",
    "sections/leadership.tex",
}

#: Allowlist of section files Claude is permitted to overwrite (no sty/tex root).
_WRITABLE_LATEX_SECTIONS: set[str] = {
    "synopsis.tex",
    "skills.tex",
    "experience.tex",
    "personalprojects.tex",
    "education.tex",
    "leadership.tex",
}


def read_latex_asset(filename: str) -> str:
    """Read a LaTeX resume asset, tenant overlay first, bundled default second.

    Allows the AI to inspect TLCresume.sty, resume.tex, _header.tex, and any
    section file so it understands the available macros before writing content.

    Resolution order (tenant isolation): the requesting user's own overlay copy
    under ``_tenant_latex_assets_dir()`` is preferred; if they have not written
    that file yet, the shared read-only bundled default is returned. A user
    therefore only ever sees their own edits or the pristine template — never
    another tenant's content.

    Args:
        filename: Relative path within the assets tree, e.g.
                  ``"TLCresume.sty"`` or ``"sections/experience.tex"``.

    Returns:
        The file content as a string.

    Raises:
        PermissionError: If the filename is not in the readable allowlist.
        FileNotFoundError: If neither the tenant overlay nor a bundled default
            exists for the file.
    """
    if filename not in _READABLE_LATEX_ASSETS:
        raise PermissionError(
            f"'{filename}' is not in the readable LaTeX asset allowlist. "
            f"Allowed files: {sorted(_READABLE_LATEX_ASSETS)}"
        )
    tenant_target = _tenant_latex_assets_dir() / filename
    if tenant_target.exists():
        return tenant_target.read_text(encoding="utf-8")
    bundled = _BUNDLED_LATEX_ASSETS_DIR / filename
    if bundled.exists():
        return bundled.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"LaTeX asset not found: {filename} "
        "(checked the tenant overlay and the bundled defaults)."
    )


def write_latex_section(section_filename: str, content: str) -> str:
    """Write a tailored resume section into the caller's per-tenant overlay.

    Use this to inject tailored content (summary, experience, skills) into the
    resume before calling ``export_resume_latex``.  Only the section files in
    the writable allowlist may be written; the base template files
    (``TLCresume.sty``, ``resume.tex``, ``_header.tex``) are read-only.

    Tenant isolation: content is written under ``_tenant_latex_assets_dir()``
    (the request-scoped workspace, e.g. ``data/users/{oid}/workspace/
    latex_assets/sections/``), NEVER the shared bundled template dir. One
    tenant's section content can therefore never be read back or compiled by
    another tenant.  ``read_latex_asset`` and ``export_resume_latex`` both
    prefer this overlay over the bundled defaults.

    Workflow::

        1. read_latex_asset("TLCresume.sty")        # understand macros
        2. read_latex_asset("sections/experience.tex")  # see current content
        3. write_latex_section("synopsis.tex", "...")   # inject tailored summary
        4. write_latex_section("experience.tex", "...")  # inject tailored bullets
        5. export_resume_latex(company="Acme", role="Staff Engineer")

    Args:
        section_filename: Bare filename within ``sections/``, e.g.
                          ``"synopsis.tex"`` or ``"experience.tex"``.
                          Do NOT include the ``sections/`` prefix.
        content:          Full LaTeX content to write.  Must be valid LaTeX
                          compatible with TLCresume.sty (zitemize, subsection,
                          skills macros, etc.).

    Returns:
        Confirmation string with the file path written.

    Raises:
        PermissionError: If the filename is not in the writable allowlist.
    """
    if section_filename not in _WRITABLE_LATEX_SECTIONS:
        raise PermissionError(
            f"'{section_filename}' is not in the writable sections allowlist. "
            f"Writable: {sorted(_WRITABLE_LATEX_SECTIONS)}"
        )
    # Write into the per-tenant overlay, NEVER the shared bundled template dir.
    # _tenant_latex_assets_dir() resolves through the request-scoped ContextVar
    # (get_active_workspace_folder), so each user's sections stay in their own
    # data partition and can never leak into another tenant's read or compile.
    target = _tenant_latex_assets_dir() / "sections" / section_filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"✓ Written: {target} ({len(content)} chars)"


# ---------------------------------------------------------------------------
# Listing helper (used by the pipeline dashboard)
# ---------------------------------------------------------------------------

def list_latex_output_pdfs() -> list[Path]:
    """Return PDFs in the latex output/ folder, newest modification time first."""
    try:
        latex_dir = _latex_dir()
        if latex_dir is None:
            return []
        output_dir = latex_dir / "output"
    except (RuntimeError, FileNotFoundError):
        return []
    if not output_dir.exists():
        return []
    pdfs = sorted(output_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs
