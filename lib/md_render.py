"""Render workspace markdown (assessments, prep docs) to print-ready PDFs.

The generation tools write .md because that's what LLMs produce well — but
.md is hostile to humans without a viewer. WeasyPrint is already bundled
(resume/cover-letter exports), so any markdown can become a styled PDF on
demand: the desktop's open-file path renders + caches by content hash and
opens the PDF instead, so the user always sees a current, printable
document and the workspace never accumulates stale .pdf siblings.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_STYLE = """
@page { size: letter; margin: 2.2cm 2.4cm; }
body { font: 10.5pt/1.55 -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
       color: #1c2733; }
h1, h2, h3 { color: #0a3d47; line-height: 1.25; page-break-after: avoid; }
h1 { font-size: 17pt; border-bottom: 2px solid #00b5c8; padding-bottom: 5px; }
h2 { font-size: 13pt; margin-top: 1.4em; border-bottom: 1px solid #d5e2e8; padding-bottom: 3px; }
h3 { font-size: 11pt; margin-top: 1.2em; }
strong { color: #0a3d47; }
code { font: 9pt "SF Mono", Menlo, Consolas, monospace; background: #f0f5f7;
       padding: 1px 4px; border-radius: 3px; }
pre { background: #f0f5f7; border: 1px solid #d5e2e8; border-radius: 6px;
      padding: 10px 12px; overflow-wrap: anywhere; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; font-size: 9.5pt; }
th, td { border: 1px solid #c9d8df; padding: 5px 8px; text-align: left; }
th { background: #eaf3f6; color: #0a3d47; }
blockquote { border-left: 3px solid #00b5c8; margin-left: 0; padding-left: 12px;
             color: #47606e; }
ul, ol { padding-left: 1.4em; }
li { margin: 0.15em 0; }
hr { border: none; border-top: 1px solid #d5e2e8; margin: 1.2em 0; }
a { color: #0b7285; }
"""


def md_to_pdf_bytes(md_text: str, title: str = "") -> bytes:
    """Markdown → styled, print-ready PDF bytes."""
    import markdown as md_lib
    import weasyprint
    # Extensions are loaded dynamically by name — static imports so
    # PyInstaller collects them into the frozen desktop build.
    from markdown.extensions import fenced_code, nl2br, sane_lists, tables  # noqa: F401

    body = md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html5",
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
    return weasyprint.HTML(string=html).write_pdf()


def rendered_pdf_for(md_path: Path, cache_dir: Path) -> Path:
    """Return a cached PDF for the markdown file, rendering if stale.

    Cache key is the content hash, so edits re-render and unchanged files
    reuse the existing PDF. The PDF keeps the source's stem so the viewer's
    title bar reads like the document, not a hash.
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    out = cache_dir / f"{md_path.stem} [{digest}].pdf"
    if not out.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Drop stale renders of the same document.
        for old in cache_dir.glob(f"{md_path.stem} [*].pdf"):
            old.unlink(missing_ok=True)
        out.write_bytes(md_to_pdf_bytes(text, title=md_path.stem))
    return out
