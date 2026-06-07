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

# Contact / identity values — kept centralised here; update if the master
# cover_letter.tex changes its \def block.
_AUTHOR_DEFAULTS = {
    "name":       r"Frank Vladmir MacBride III",
    "phone":      r"+1 (305) 490-1262",
    "city":       r"Atlanta, GA",
    "email":      r"frankvmacbride@gmail.com",
    "linkedin":   r"frankvmacbride",
    "github":     r"JustLikeFrank3",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latex_dir() -> Path:
    """Return the frank-resume-latex directory from config, or raise."""
    d = cfg.LATEX_RESUME_DIR
    if d is None:
        raise RuntimeError(
            "latex_resume_dir is not set in config.json. "
            "Add the absolute path to your frank-resume-latex folder."
        )
    if not d.exists():
        raise FileNotFoundError(f"latex_resume_dir does not exist: {d}")
    return d


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
                 03-Resume-PDFs folder so dashboard previews can find it.
        identity:    Optional contact/identity overrides for demo output.
                 Supported keys match _AUTHOR_DEFAULTS: name, phone, city,
                 email, linkedin, github. Defaults preserve Frank's data.

    Returns:
        Path to the compiled PDF.
    """
    latex_src = _latex_dir()

    if output_dir is None:
        output_dir = cfg.RESUME_FOLDER / "03-Resume-PDFs"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build a safe filename slug
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{company}_{role}").strip("_")
    from datetime import date
    today = date.today()
    dated = today.strftime("%Y%m%d")
    pdf_name = f"cover_letter_{slug}_{dated}.pdf"
    final_pdf = output_dir / pdf_name

    # Default the printed letter date to today (e.g. 'June 7, 2026'). Strip any
    # zero-padding on the day so it reads naturally.
    if not letter_date:
        letter_date = today.strftime("%B %-d, %Y")

    author = {**_AUTHOR_DEFAULTS, **(identity or {})}
    author = {key: _escape_latex(value) for key, value in author.items()}

    tex_body = _prose_to_tex(body)
    tex_src = _TEX_TEMPLATE.format(
        **author,
        role_title=_escape_latex(role_title),
        date=_escape_latex(letter_date),
        body=tex_body,
    )

    tectonic = _tectonic_bin()

    # Compile in a temp directory that shares the latex project's working
    # directory so that \input{_header} and \usepackage{TLCresume} resolve.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / "cover_letter.tex"
        tex_file.write_text(tex_src, encoding="utf-8")

        # Symlink required support files into the temp dir
        for name in ["_header.tex", "TLCresume.sty"]:
            src_file = latex_src / name
            if src_file.exists():
                (tmp_path / name).symlink_to(src_file)

        result = subprocess.run(
            [tectonic, str(tex_file)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tectonic compilation failed:\n{result.stderr}\n{result.stdout}"
            )

        compiled_pdf = tmp_path / "cover_letter.pdf"
        if not compiled_pdf.exists():
            raise FileNotFoundError(
                "tectonic reported success but cover_letter.pdf was not produced."
            )

        shutil.copy2(compiled_pdf, final_pdf)

    return final_pdf


# ---------------------------------------------------------------------------
# Listing helper (used by the pipeline dashboard)
# ---------------------------------------------------------------------------

def list_latex_output_pdfs() -> list[Path]:
    """Return PDFs in the latex output/ folder, newest modification time first."""
    try:
        output_dir = _latex_dir() / "output"
    except (RuntimeError, FileNotFoundError):
        return []
    if not output_dir.exists():
        return []
    pdfs = sorted(output_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs
