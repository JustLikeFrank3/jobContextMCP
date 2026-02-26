from pathlib import Path

from lib import config
from lib.io import _read, _load_master_context



# ── HELPERS ───────────────────────────────────────────────────────────────

def _unwrap(content: str) -> str:
    """
    Remove hard line-wrapping introduced by AI generation at ~80-100 chars.

    Rules:
      - A line that starts with whitespace (and isn't a bullet) is a
        continuation of the previous non-empty line — rejoin it.
      - Blank lines (paragraph breaks) are preserved.
      - Bullet lines (•, -, *) that start with whitespace are also
        continuations of the preceding bullet.
      - ─────────── separator lines are preserved as-is.
    """
    lines = content.splitlines()
    result: list[str] = []
    for line in lines:
        # Blank line — always a paragraph break, keep it
        if not line.strip():
            result.append("")
            continue
        # Continuation line: starts with whitespace, not a new bullet
        if line[0] in (" ", "\t") and result:
            stripped = line.strip()
            # Find last non-blank line in result and append to it
            for i in range(len(result) - 1, -1, -1):
                if result[i].strip():
                    result[i] = result[i].rstrip() + " " + stripped
                    break
            else:
                result.append(stripped)
        else:
            result.append(line)
    return "\n".join(result)


def read_master_resume() -> str:
    """Read Frank's master source resume — the single source of truth containing all metrics, achievements, projects, and context notes. Always read this before generating any resume or cover letter."""
    return _load_master_context()


def list_existing_materials(company: str = "") -> str:
    """List all existing resume and cover letter files. Optionally filter by company name to see materials for a specific target company."""
    optimized_dir = config.RESUME_FOLDER / config._cfg["optimized_resumes_dir"]
    cover_letter_dir = config.RESUME_FOLDER / config._cfg["cover_letters_dir"]

    def _list_dir(d: Path, label: str) -> list[str]:
        if not d.exists():
            return [f"  (folder not found: {d.name})"]
        files = sorted(
            f.name
            for f in d.iterdir()
            if f.suffix in (".txt", ".md")
            and "MASTER" not in f.name
            and (not company or company.lower() in f.name.lower())
        )
        out = [f"\n══ {label} ({len(files)}) ══"]
        out += [f"  {f}" for f in files] or ["  (none found)"]
        return out

    lines = []
    lines += _list_dir(optimized_dir, "RESUMES")
    lines += _list_dir(cover_letter_dir, "COVER LETTERS")
    return "\n".join(lines)


def read_existing_resume(filename: str) -> str:
    """Read the full text of an existing resume from 01-Current-Optimized/. Use list_existing_materials() to find available filenames."""
    path = config.RESUME_FOLDER / config._cfg["optimized_resumes_dir"] / filename
    if not path.exists():
        return f"Not found: {filename}\nUse list_existing_materials() to see available resumes."
    return _read(path)


def read_reference_file(filename: str) -> str:
    """Read a file from 06-Reference-Materials/ (e.g. template format, consolidated resume, skills variants, GM feedback). Pass the filename only — use list_existing_materials() to discover what's available."""
    ref_dir = config.RESUME_FOLDER / config._cfg["reference_materials_dir"]
    path = ref_dir / filename
    if not path.exists():
        available = sorted(f.name for f in ref_dir.iterdir()) if ref_dir.exists() else []
        return f"Not found: {filename}\nAvailable: {available}"
    return _read(path)


def save_resume_txt(filename: str, content: str) -> str:
    """
    Save a generated resume to 01-Current-Optimized/ as a clean .txt file.

    ALWAYS use this instead of creating the file directly — it strips
    hard line-wrapping introduced during generation so the PDF exporter
    can parse the file correctly.

    Args:
        filename: Filename with or without .txt extension.
        content:  Full resume text as generated.

    Returns:
        Confirmation with saved path.
    """
    if not filename.endswith(".txt"):
        filename += ".txt"
    out_dir = config.RESUME_FOLDER / config._cfg["optimized_resumes_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(_unwrap(content), encoding="utf-8")
    return f"✓ Resume saved: {path}"


def save_cover_letter_txt(filename: str, content: str) -> str:
    """
    Save a generated cover letter to 02-Cover-Letters/ as a clean .txt file.

    ALWAYS use this instead of creating the file directly — it strips
    hard line-wrapping introduced during generation so the PDF exporter
    can parse the file correctly.

    Args:
        filename: Filename with or without .txt extension.
        content:  Full cover letter text as generated.

    Returns:
        Confirmation with saved path.
    """
    if not filename.endswith(".txt"):
        filename += ".txt"
    out_dir = config.RESUME_FOLDER / config._cfg["cover_letters_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(_unwrap(content), encoding="utf-8")
    return f"✓ Cover letter saved: {path}"


def resume_diff(file_a: str, file_b: str) -> str:
    """
    Generate a human-readable diff between two resume .txt files.

    Both filenames are resolved against 01-Current-Optimized/. If a full path
    or alternate folder is needed, prefix with 'ref:' to resolve against
    06-Reference-Materials/ instead (e.g. 'ref:Frank MacBride Resume - Consolidated.txt').

    Args:
        file_a: First resume filename (the 'before' / baseline version).
        file_b: Second resume filename (the 'after' / new version).

    Returns:
        Unified diff with a plain-English summary of added/removed/changed sections.
    """
    import difflib

    def _resolve(name: str) -> Path:
        if name.startswith("ref:"):
            return config.RESUME_FOLDER / config._cfg.get("reference_materials_dir", "06-Reference-Materials") / name[4:]
        return config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized") / name

    path_a = _resolve(file_a)
    path_b = _resolve(file_b)

    for p, label in ((path_a, file_a), (path_b, file_b)):
        if not p.exists():
            return f"File not found: {label}\nUse list_existing_materials() to discover available resumes."

    lines_a = path_a.read_text(encoding="utf-8").splitlines(keepends=True)
    lines_b = path_b.read_text(encoding="utf-8").splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=file_a,
            tofile=file_b,
            lineterm="",
        )
    )

    if not diff:
        return f"No differences found between {file_a} and {file_b}."

    added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    summary = [
        f"═══ RESUME DIFF ═══",
        f"  From: {file_a}",
        f"  To:   {file_b}",
        f"  +{added} lines added  /  -{removed} lines removed",
        "",
    ]

    return "\n".join(summary) + "\n".join(diff[:400])  # cap at 400 lines for readability


def register(mcp) -> None:
    mcp.tool()(read_master_resume)
    mcp.tool()(list_existing_materials)
    mcp.tool()(read_existing_resume)
    mcp.tool()(read_reference_file)
    mcp.tool()(save_resume_txt)
    mcp.tool()(save_cover_letter_txt)
    mcp.tool()(resume_diff)
