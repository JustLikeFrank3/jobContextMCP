"""
setup_workspace — conversational workspace bootstrapper (v6).

Two tools:
  check_workspace()   — diagnostic scan; reports what's present / missing.
                        Safe to call any time, makes no changes.
  setup_workspace()   — creates everything from user-provided info.
                        Idempotent: skips files/dirs that already exist.
                        After running, the user can call get_session_context()
                        and generate_resume() immediately.
"""

import json
import shutil
from pathlib import Path

from lib import config
from lib.io import _save_json

_HERE = Path(__file__).resolve().parent.parent  # repo root

# ── Workspace layout — derived from config so Docker volumes are respected ────
# Use lazy helpers so we always read the live config values rather than
# snapshotting them at import time (config may not be loaded yet).

def _resumes_root() -> Path:
    """Resume workspace root — honours per-user context in multi-tenant mode."""
    return config.get_active_workspace_folder()

def _leetcode_root() -> Path:
    """LeetCode workspace root — honours per-user context in multi-tenant mode."""
    return config.get_active_leetcode_folder()

def _data_dir() -> Path:
    """Data directory — honours per-user context in multi-tenant mode."""
    return config.get_active_data_folder()

# Kept only for _build_config which constructs a brand-new config.json
_WORKSPACE_ROOT = _HERE / "workspace"

_RESUME_SUBDIRS = [
    "01-Current-Optimized",
    "02-Cover-Letters",
    "03-Resume-PDFs",
    "04-Performance-Reviews",
    "05-Archived-Versions",
    "06-Reference-Materials",
    "07-Job-Assessments",
    "08-Interview-Prep-Docs",
    "09-Cover-Letter-PDFs",
]

_DATA_FILES = [
    "status.json",
    "mental_health_log.json",
    "personal_context.json",
    "tone_samples.json",
    "people.json",
    "linkedin_posts.json",
    "rejections.json",
]

# ── LeetCode language scaffolding ─────────────────────────────────────────────

_LC_SUPPORTED_LANGS = {"java", "python", "javascript", "typescript", "cpp"}

_LC_PROBLEMS_DIR = {
    "java":       "src/problems",
    "python":     "problems",
    "javascript": "problems",
    "typescript": "problems",
    "cpp":        "problems",
}

_LC_STUB = {
    "java": (
        "HelloWorld.java",
        '// LeetCode practice — Java\npublic class HelloWorld {\n'
        '    public static void main(String[] args) {\n'
        '        System.out.println("Ready.");\n'
        '    }\n}\n',
    ),
    "python": (
        "hello_world.py",
        "# LeetCode practice — Python\nprint('Ready.')\n",
    ),
    "javascript": (
        "helloWorld.js",
        "// LeetCode practice — JavaScript\nconsole.log('Ready.');\n",
    ),
    "typescript": (
        "helloWorld.ts",
        "// LeetCode practice — TypeScript\nconsole.log('Ready.');\n",
    ),
    "cpp": (
        "hello_world.cpp",
        '#include <iostream>\nint main() {\n    std::cout << "Ready." << std::endl;\n    return 0;\n}\n',
    ),
}

_CHEATSHEET_STUB = """# Algorithm Cheatsheet

Fill this in as you practice. Suggested sections:

## HashMap / Two Sum Pattern
## Two Pointers
## Sliding Window
## Fast / Slow Pointers
## Tree DFS / BFS
## Graph DFS / BFS
## Stack (Monotonic)
## Dynamic Programming
## System Design Framework
"""

_QUICK_REF_STUB = """# Interview Day Quick Reference

## Pre-Interview Checklist
- [ ] Good sleep, water, food
- [ ] Second monitor / cheatsheet open
- [ ] IDE ready with test file
- [ ] Talk through approach before typing

## Problem-Solving Framework
1. Clarify constraints and examples
2. State brute-force approach + complexity
3. Identify optimization (HashMap? Two pointers? DP?)
4. Code the optimized solution
5. Test with edge cases: null, empty, single element, duplicates

## System Design (5 Steps)
1. Requirements (functional + non-functional)
2. High-level architecture
3. Data model
4. Core logic / algorithms
5. Scale + failure modes
"""

# ── Seed data structures ──────────────────────────────────────────────────────

def _seed_data(name: str) -> dict:
    return {
        "status.json": {
            "last_updated": "—",
            "applications": [],
            "pipeline_summary": f"Fresh workspace for {name}. Add your first application with update_application().",
        },
        "mental_health_log.json": {"checkins": []},
        "personal_context.json":  {"stories": []},
        "tone_samples.json":      {"samples": []},
        "people.json":            {"people": []},
        "linkedin_posts.json":    {"posts": []},
        "rejections.json":        {"rejections": []},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_name(full_name: str) -> str:
    """'Jane Smith' → 'Jane Smith'  (already clean, just strip)."""
    return full_name.strip()


def _master_resume_filename(name: str) -> str:
    return f"{_safe_name(name)} Resume - MASTER SOURCE.txt"


def _to_tilde(p: Path) -> str:
    """Convert an absolute path to ~/... form when it lives under $HOME.

    Makes config.json portable across machines and mount points — the
    stored value works as long as $HOME resolves correctly, regardless
    of whether the home directory is on the boot volume or an external drive.
    """
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def _build_config(
    name: str,
    email: str,
    phone: str,
    linkedin: str,
    city_state: str,
    address: str,
    openai_api_key: str,
    leetcode_language: str,
    side_project_folders: list[str],
) -> dict:
    lang = leetcode_language.lower()
    lc_problems_subdir = _LC_PROBLEMS_DIR.get(lang, "problems")

    cfg: dict = {
        "resume_folder":    _to_tilde(_resumes_root()),
        "leetcode_folder":  _to_tilde(_leetcode_root()),
        "data_folder":      _to_tilde(_HERE / "data"),
        "side_project_folders": [_to_tilde(Path(p).expanduser()) for p in (side_project_folders or [])],

        "master_resume_path":         f"01-Current-Optimized/{_master_resume_filename(name)}",
        "leetcode_cheatsheet_path":   "Algorithm_Cheatsheet.md",
        "quick_reference_path":       "Interview_Quick_Reference.md",
        "optimized_resumes_dir":      "01-Current-Optimized",
        "cover_letters_dir":          "02-Cover-Letters",
        "reference_materials_dir":    "06-Reference-Materials",
        "job_assessments_dir":        "07-Job-Assessments",
        "interview_prep_docs_dir":    "08-Interview-Prep-Docs",

        # Optional reference paths — left blank; won't crash if files don't exist
        "resume_template_png":        "06-Reference-Materials/resume_template.png",
        "cover_letter_template_png":  "06-Reference-Materials/cover_letter_template.png",
        "template_format_path":       "06-Reference-Materials/Template Format.txt",
        "achievements_path":           "06-Reference-Materials/Achievements.txt",
        "feedback_received_path":     "06-Reference-Materials/Feedback.txt",
        "skills_shorter_path":        "06-Reference-Materials/Skills Shorter.txt",

        "leetcode_language":          lang,
        "leetcode_problems_dir":      lc_problems_subdir,

        "contact": {
            "name":       _safe_name(name),
            "phone":      phone.strip(),
            "email":      email.strip(),
            "linkedin":   linkedin.strip(),
            "address":    address.strip(),
            "city_state": city_state.strip(),
            "location":   city_state.strip(),
        },
    }

    if openai_api_key:
        cfg["openai_api_key"] = openai_api_key.strip()
        cfg["openai_model"] = "gpt-4o-mini"

    return cfg


# ── check_workspace ───────────────────────────────────────────────────────────

def check_workspace() -> str:
    """
    Scan the workspace and report what's present, missing, or incomplete.
    Makes no changes. Safe to call at any time.
    Returns a structured status report with next-step instructions.
    """
    lines = ["═══ WORKSPACE STATUS ═══", ""]

    # config.json
    config_path = _HERE / "config.json"
    if config_path.exists():
        lines.append("✓ config.json — present")
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            contact = cfg.get("contact", {})
            lines.append(f"  Name:    {contact.get('name', '(missing)')}")
            lines.append(f"  Email:   {contact.get('email', '(missing)')}")
            if cfg.get("openai_api_key"):
                lines.append("  OpenAI:  key configured (auto-generation enabled)")
            else:
                lines.append("  OpenAI:  no key — Copilot-assisted generation mode")
            lines.append(f"  LeetCode language: {cfg.get('leetcode_language', '(not set)')}")
        except Exception as e:
            lines.append(f"  ⚠ Could not parse config.json: {e}")
    else:
        lines.append("✗ config.json — MISSING  ← run setup_workspace() to create")

    lines.append("")

    # Resume folder subdirs
    resumes_root = _resumes_root()
    lines.append("── Resume workspace ──")
    for subdir in _RESUME_SUBDIRS:
        p = resumes_root / subdir
        lines.append(f"  {'✓' if p.exists() else '✗'} {resumes_root}/{subdir}/")

    # Master resume
    lines.append("")
    lines.append("── Master resume ──")
    if config_path.exists():
        try:
            mr = config.get_active_master_resume_path()
            if mr.exists():
                word_count = len(mr.read_text(encoding="utf-8", errors="replace").split())
                lines.append(f"  ✓ {mr.name} ({word_count} words)")
            else:
                lines.append(f"  ✗ {mr.name} — not found")
                lines.append("    → Paste your resume content via setup_workspace(master_resume_content=...)")
        except Exception:
            lines.append("  ✗ Could not determine master resume path")
    else:
        lines.append("  ✗ Cannot check — config.json missing")

    lines.append("")

    # LeetCode
    lc_root = _leetcode_root()
    lines.append("── LeetCode workspace ──")
    lc_exists = lc_root.exists()
    lines.append(f"  {'✓' if lc_exists else '✗'} {lc_root}/")
    if lc_exists:
        cheat = config.get_active_leetcode_cheatsheet_path()
        qref  = config.get_active_quick_reference_path()
        lines.append(f"  {'✓' if cheat.exists() else '✗'} {cheat.name}")
        lines.append(f"  {'✓' if qref.exists() else '✗'} {qref.name}")

    lines.append("")

    # Data files
    lines.append("── Data files ──")
    data_dir = _data_dir()
    for fname in _DATA_FILES:
        p = data_dir / fname
        lines.append(f"  {'✓' if p.exists() else '✗'} {data_dir}/{fname}")

    lines.append("")

    # Summary
    missing_config    = not config_path.exists()
    missing_data      = any(not (data_dir / f).exists() for f in _DATA_FILES)
    missing_workspace = not resumes_root.exists() or not lc_root.exists()

    if not missing_config and not missing_data and not missing_workspace:
        lines.append("✓ Workspace looks complete. Call get_session_context() to begin.")
    else:
        lines.append("⚠ Workspace incomplete. Call setup_workspace() with your details to finish setup.")
        lines.append("")
        lines.append("Minimum required parameters:")
        lines.append("  name, email, phone, linkedin, city_state, master_resume_content")
        lines.append("  leetcode_language (default: 'java') — options: java, python, javascript, typescript, cpp")

    return "\n".join(lines)


# ── setup_workspace ───────────────────────────────────────────────────────────

def setup_workspace(
    name: str,
    email: str,
    phone: str,
    linkedin: str,
    city_state: str,
    master_resume_content: str,
    address: str = "",
    openai_api_key: str = "",
    leetcode_language: str = "java",
    side_project_folders: list[str] | None = None,
) -> str:
    """
    Bootstrap a complete JobContextMCP workspace from scratch.

    Creates config.json, all data files, resume folder structure (01–08),
    and a LeetCode workspace scaffolded for your preferred language.
    Idempotent — safe to re-run; skips anything that already exists.

    HOW TO PROVIDE YOUR MASTER RESUME:
      Drag your existing resume file into this chat, or paste the raw text.
      The AI will pass the full text as master_resume_content.

    LEETCODE LANGUAGE OPTIONS: java | python | javascript | typescript | cpp

    Args:
        name:                   Your full legal name (used in resume headers).
        email:                  Contact email.
        phone:                  Phone number.
        linkedin:               LinkedIn URL (e.g. linkedin.com/in/yourhandle).
        city_state:             City, State (e.g. Atlanta, GA).
        master_resume_content:  Full text of your master resume. Paste it raw —
                                formatting will be applied during PDF export.
        address:                Street address (optional — cover letter sidebar only).
        openai_api_key:         Optional. Enables fully-automated resume/cover letter
                                generation via OpenAI. Without it, Copilot writes
                                the content instead. Either mode works.
        leetcode_language:      Programming language for LeetCode practice.
                                Default: java.
        side_project_folders:   Absolute paths to side projects to scan for skills.
    """
    lang = leetcode_language.lower()
    if lang not in _LC_SUPPORTED_LANGS:
        return (
            f"✗ Unsupported leetcode_language '{leetcode_language}'.\n"
            f"Supported: {', '.join(sorted(_LC_SUPPORTED_LANGS))}"
        )

    created: list[str] = []
    skipped: list[str] = []

    def _mark(label: str, was_created: bool) -> None:
        (created if was_created else skipped).append(label)

    # Resolve live paths from config (respects Docker volume mounts)
    resumes_root = _resumes_root()
    lc_root      = _leetcode_root()
    data_dir     = _data_dir()

    # 1. Resume folder subdirs
    for subdir in _RESUME_SUBDIRS:
        p = resumes_root / subdir
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            _mark(f"{resumes_root}/{subdir}/", True)
        else:
            _mark(f"{resumes_root}/{subdir}/", False)

    # 2. Master resume
    mr_filename = _master_resume_filename(name)
    mr_path = resumes_root / "01-Current-Optimized" / mr_filename
    if not mr_path.exists():
        mr_path.write_text(master_resume_content.strip(), encoding="utf-8")
        _mark(f"01-Current-Optimized/{mr_filename}", True)
    else:
        _mark(f"01-Current-Optimized/{mr_filename} (already exists — not overwritten)", False)

    # 3. LeetCode workspace
    lc_problems_subdir = _LC_PROBLEMS_DIR[lang]
    lc_problems_dir = lc_root / lc_problems_subdir
    if not lc_problems_dir.exists():
        lc_problems_dir.mkdir(parents=True, exist_ok=True)
        _mark(f"{lc_root}/{lc_problems_subdir}/", True)
    else:
        _mark(f"{lc_root}/{lc_problems_subdir}/", False)

    # Stub problem file
    stub_fname, stub_content = _LC_STUB[lang]
    stub_path = lc_problems_dir / stub_fname
    if not stub_path.exists():
        stub_path.write_text(stub_content, encoding="utf-8")
        _mark(f"{lc_root}/{lc_problems_subdir}/{stub_fname}", True)
    else:
        _mark(f"{lc_root}/{lc_problems_subdir}/{stub_fname}", False)

    # Cheatsheet + quick reference stubs
    for fname, content in [
        ("Algorithm_Cheatsheet.md", _CHEATSHEET_STUB),
        ("Interview_Quick_Reference.md", _QUICK_REF_STUB),
    ]:
        p = lc_root / fname
        if not p.exists():
            p.write_text(content, encoding="utf-8")
            _mark(f"{lc_root}/{fname}", True)
        else:
            _mark(f"{lc_root}/{fname}", False)

    # 4. Data files
    data_dir.mkdir(exist_ok=True)
    seeds = _seed_data(name)
    for fname in _DATA_FILES:
        p = data_dir / fname
        if not p.exists():
            example = _HERE / "data" / fname.replace(".json", ".example.json")
            if example.exists():
                # Use official example as seed (has correct schema)
                shutil.copy(example, p)
            else:
                _save_json(p, seeds.get(fname, {}))
            _mark(f"{data_dir}/{fname}", True)
        else:
            _mark(f"{data_dir}/{fname}", False)

    # 5. config.json — local mode only
    # In multi-tenant AKS mode the config is injected via ConfigMap env vars
    # and there is no writable config.json at the repo root.  Skip when a
    # per-user data folder override is active (i.e. a guest user session).
    from lib.user_context import get_data_folder_override
    if get_data_folder_override() is None:
        config_path = _HERE / "config.json"
        if not config_path.exists():
            cfg = _build_config(
                name=name,
                email=email,
                phone=phone,
                linkedin=linkedin,
                city_state=city_state,
                address=address,
                openai_api_key=openai_api_key,
                leetcode_language=lang,
                side_project_folders=list(side_project_folders or []),
            )
            config_path.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            _mark("config.json", True)
            # Reload live config so tools work immediately
            from lib.config import _reconfigure
            _reconfigure(cfg)
        else:
            _mark("config.json (already exists — not overwritten)", False)

    # ── Report ────────────────────────────────────────────────────────────────
    lines = ["═══ WORKSPACE SETUP COMPLETE ═══", ""]

    if created:
        lines.append(f"Created ({len(created)}):")
        for item in created:
            lines.append(f"  ✓ {item}")
        lines.append("")

    if skipped:
        lines.append(f"Already existed — skipped ({len(skipped)}):")
        for item in skipped:
            lines.append(f"  · {item}")
        lines.append("")

    lines.append("── What's ready ──")
    lines.append(f"  Master resume : 01-Current-Optimized/{mr_filename}")
    lines.append(f"  LeetCode lang : {lang} → workspace/leetcode/{lc_problems_subdir}/")
    if openai_api_key:
        lines.append("  Generation    : OpenAI key set — generate_resume() runs fully automated")
    else:
        lines.append("  Generation    : No OpenAI key — Copilot writes resume content (still works)")
    lines.append("")
    lines.append("── Next steps ──")
    lines.append("  1. Call get_session_context() — loads your resume + empty pipeline")
    lines.append("  2. Paste a job description and call generate_resume() to create your first tailored resume")
    lines.append("  3. Call setup_workspace() again at any time to self-heal missing files")
    lines.append("")
    lines.append("  Optional enrichment:")
    lines.append("  • ingest_anecdote() — add STAR stories and voice samples")
    lines.append("  • update_application() — start tracking applications")
    lines.append("  • log_tone_sample() — paste cover letters you've written to calibrate your voice")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(check_workspace)
    mcp.tool()(setup_workspace)
