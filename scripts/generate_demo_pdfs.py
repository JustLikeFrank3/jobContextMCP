#!/usr/bin/env python3
"""
generate_demo_pdfs.py

Generates demo resume and cover letter PDFs for Nobody MacFakename using
every available template (legacy + 4 new), then converts each to PNG for
README incorporation.

Output: docs/demo/
"""

import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.export import export_resume_pdf, export_cover_letter_pdf
import fitz  # PyMuPDF

RESUME_FILE    = "Nobody-MacFakename-Demo-Resume"
CL_FILE        = "Nobody-MacFakename-Demo-Cover-Letter"
OUT_DIR        = ROOT / "docs" / "demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES = ["", "modern", "executive", "sidebar", "portfolio"]
STYLE     = "navy"

# ── Generate PDFs ──────────────────────────────────────────────────────────

def run_all():
    generated = []

    for tmpl in TEMPLATES:
        label = tmpl or "legacy"

        # Resume
        res_out = f"demo_resume_{label}.pdf"
        result = export_resume_pdf(
            filename=RESUME_FILE,
            footer_tag="SOFTWARE ENGINEER",
            output_filename=res_out,
            template=tmpl,
            style=STYLE if tmpl else "",
        )
        print(result)
        # export writes to workspace/03-Resume-PDFs/ — find it
        pdf_path = _find_pdf(res_out, "03-Resume-PDFs")
        if pdf_path:
            dest = OUT_DIR / res_out
            dest.write_bytes(pdf_path.read_bytes())
            generated.append(dest)

        # Cover letter
        cl_out = f"demo_coverletter_{label}.pdf"
        result = export_cover_letter_pdf(
            filename=CL_FILE,
            output_filename=cl_out,
            footer_tag="SOFTWARE ENGINEER",
            template=tmpl,
            style=STYLE if tmpl else "",
        )
        print(result)
        pdf_path = _find_pdf(cl_out, "09-Cover-Letter-PDFs")
        if pdf_path:
            dest = OUT_DIR / cl_out
            dest.write_bytes(pdf_path.read_bytes())
            generated.append(dest)

    return generated


def _find_pdf(filename: str, subfolder: str) -> Path | None:
    candidate = ROOT / "workspace" / subfolder / filename
    if candidate.exists():
        return candidate
    # fallback glob
    matches = list((ROOT / "workspace" / subfolder).glob(f"*{Path(filename).stem}*"))
    return matches[0] if matches else None


# ── PDF → PNG ──────────────────────────────────────────────────────────────

def pdf_to_png(pdf_path: Path, dpi: int = 150) -> list[Path]:
    """Render each page of a PDF to a PNG. Returns list of PNG paths."""
    doc = fitz.open(str(pdf_path))
    pngs = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out_path = pdf_path.with_name(pdf_path.stem + (f"_p{i+1}" if len(doc) > 1 else "") + ".png")
        pix.save(str(out_path))
        pngs.append(out_path)
        print(f"  → {out_path.name}")
    return pngs


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Generating PDFs ===")
    pdfs = run_all()

    print(f"\n=== Converting {len(pdfs)} PDFs to PNG ===")
    all_pngs = []
    for pdf in pdfs:
        if pdf.exists():
            all_pngs.extend(pdf_to_png(pdf))

    print(f"\nDone. {len(pdfs)} PDFs and {len(all_pngs)} PNGs written to {OUT_DIR}")
