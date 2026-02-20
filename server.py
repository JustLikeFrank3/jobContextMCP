#!/usr/bin/env python3
"""
Job Search MCP Server for Frank MacBride
-----------------------------------------
Provides tools for:
  - Job hunt status tracking
  - Resume / cover letter context generation
  - Job fitment assessment
  - Interview & LeetCode prep
  - sPiCam project skill scanning
  - Mental health check-in logging
"""

import json
import os
import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
# Paths are loaded from config.json (gitignored) sitting next to this file.
# Copy config.example.json → config.json and fill in your own paths.

_HERE = Path(__file__).parent


def _load_config() -> dict:
    config_path = _HERE / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"config.json not found at {config_path}\n"
            "Copy config.example.json → config.json and fill in your paths."
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


_cfg = _load_config()

RESUME_FOLDER   = Path(_cfg["resume_folder"])
LEETCODE_FOLDER = Path(_cfg["leetcode_folder"])
SPICAM_FOLDER   = Path(_cfg["spicam_folder"])
DATA_FOLDER     = Path(_cfg["data_folder"])

STATUS_FILE     = DATA_FOLDER / "status.json"
HEALTH_LOG_FILE = DATA_FOLDER / "mental_health_log.json"

MASTER_RESUME       = RESUME_FOLDER / _cfg["master_resume_path"]
LEETCODE_CHEATSHEET = LEETCODE_FOLDER / _cfg["leetcode_cheatsheet_path"]
QUICK_REFERENCE     = LEETCODE_FOLDER / _cfg["quick_reference_path"]

# ─── SERVER ───────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "job-search-assistant",
    instructions=(
        "You are Frank MacBride's personal job search assistant. "
        "You have direct filesystem access to his resume materials, job hunt status, "
        "and interview prep files. Use the available tools to retrieve context before "
        "generating resumes, cover letters, prep docs, or assessments. "
        "Always read the master resume before generating any application material."
    ),
)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Error reading {path.name}: {e}]"


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ─── TOOLS: JOB HUNT STATUS ───────────────────────────────────────────────────

@mcp.tool()
def get_job_hunt_status() -> str:
    """
    Returns the current status of all tracked job applications with
    next steps, contacts, and notes.
    """
    data = _load_json(STATUS_FILE, {"applications": []})
    apps = data.get("applications", [])
    if not apps:
        return "No applications tracked yet. Use update_application() to add one."

    lines = [
        "═══ JOB HUNT STATUS ═══",
        f"Last updated: {data.get('last_updated', 'unknown')}",
        "",
    ]
    for app in apps:
        lines.append(f"■ {app['company']} — {app['role']}")
        lines.append(f"  Status:       {app['status']}")
        lines.append(f"  Last update:  {app.get('last_updated', '—')}")
        if app.get("next_steps"):
            lines.append(f"  Next steps:   {app['next_steps']}")
        if app.get("contact"):
            lines.append(f"  Contact:      {app['contact']}")
        if app.get("notes"):
            lines.append(f"  Notes:        {app['notes']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def update_application(
    company: str,
    role: str,
    status: str,
    next_steps: str = "",
    contact: str = "",
    notes: str = "",
) -> str:
    """
    Add or update a job application in the tracker.

    status values: applied | phone_screen | technical_screen | coding_assessment
                   system_design | onsite | offer | rejected | withdrawn | waiting
    """
    data = _load_json(STATUS_FILE, {"applications": []})
    apps: list = data.setdefault("applications", [])

    existing = next((a for a in apps if a["company"].lower() == company.lower()), None)
    if existing:
        existing.update(
            role=role,
            status=status,
            next_steps=next_steps,
            contact=contact,
            notes=notes,
            last_updated=_now(),
        )
        action = "Updated"
    else:
        apps.append(
            dict(
                company=company,
                role=role,
                status=status,
                next_steps=next_steps,
                contact=contact,
                notes=notes,
                applied_date=_now(),
                last_updated=_now(),
            )
        )
        action = "Added"

    data["last_updated"] = _now()
    _save_json(STATUS_FILE, data)
    return f"✓ {action}: {company} — {role} ({status})"


# ─── TOOLS: RESUME CONTENT ────────────────────────────────────────────────────

@mcp.tool()
def read_master_resume() -> str:
    """
    Returns the full MASTER SOURCE resume with all metrics, achievements, and
    personal context notes. Always call this before generating any resume or
    cover letter.
    """
    return _read(MASTER_RESUME)


@mcp.tool()
def list_existing_materials(company: str = "") -> str:
    """
    Lists resumes and cover letters already generated in this workspace.
    Optionally filter by company name.
    """
    optimized_dir    = RESUME_FOLDER / _cfg["optimized_resumes_dir"]
    cover_letter_dir = RESUME_FOLDER / _cfg["cover_letters_dir"]

    def _list_dir(d: Path, label: str) -> list[str]:
        if not d.exists():
            return [f"  (folder not found: {d.name})"]
        files = sorted(
            f.name for f in d.iterdir()
            if f.suffix == ".txt" and "MASTER" not in f.name
            and (not company or company.lower() in f.name.lower())
        )
        out = [f"\n══ {label} ({len(files)}) ══"]
        out += [f"  {f}" for f in files] or ["  (none found)"]
        return out

    lines = []
    lines += _list_dir(optimized_dir,    "RESUMES")
    lines += _list_dir(cover_letter_dir, "COVER LETTERS")
    return "\n".join(lines)


@mcp.tool()
def read_existing_resume(filename: str) -> str:
    """
    Read the content of a specific resume file.
    filename should be just the base filename (no path) from 01-Current-Optimized/.
    Use list_existing_materials() to see available files.
    """
    path = RESUME_FOLDER / _cfg["optimized_resumes_dir"] / filename
    if not path.exists():
        return f"Not found: {filename}\nUse list_existing_materials() to see available resumes."
    return _read(path)


@mcp.tool()
def read_reference_file(filename: str) -> str:
    """
    Read a file from the 06-Reference-Materials/ folder.
    Useful files: 'Frank MacBride Resume - Template Format.txt',
                  'Skills - 10% Shorter.txt',
                  'GM Recognition Awards, Feedback_Received.txt'
    """
    ref_dir = RESUME_FOLDER / _cfg["reference_materials_dir"]
    path = ref_dir / filename
    if not path.exists():
        available = sorted(
            f.name for f in ref_dir.iterdir()
        ) if ref_dir.exists() else []
        return f"Not found: {filename}\nAvailable: {available}"
    return _read(path)


# ─── TOOLS: FITMENT & STRATEGY ────────────────────────────────────────────────

@mcp.tool()
def assess_job_fitment(company: str, role: str, job_description: str) -> str:
    """
    Provides everything needed to assess how well Frank's background maps to a
    job description. Returns the master resume + JD packaged for analysis.

    After calling this tool, produce:
      1. Overall fit score (0–100%)
      2. Key strengths matching requirements
      3. Gaps / risks
      4. Suggested resume emphasis (which bullets to lead with)
      5. Top 3–5 STAR stories from Frank's background most relevant here
      6. Questions to probe / clarify before applying
    """
    master = _read(MASTER_RESUME)
    return (
        f"═══ FITMENT ASSESSMENT ═══\n"
        f"Company: {company}\n"
        f"Role:    {role}\n\n"
        f"──── JOB DESCRIPTION ────\n{job_description}\n\n"
        f"──── FRANK'S MASTER RESUME ────\n{master}"
    )


@mcp.tool()
def get_customization_strategy(role_type: str) -> str:
    """
    Returns the recommended resume emphasis strategy for a given role type.

    role_type options:
      testing | cloud | data_engineering | backend | fullstack | ai_innovation | iot
    """
    strategies = {
        "testing": (
            "Lead with JUnit/Mockito/Selenium expertise, 80%+ coverage metrics, TDD practices. "
            "Feature the 'prevented production defects' story. "
            "Highlight Karma/Jest for frontend testing."
        ),
        "cloud": (
            "Lead with Azure Container Apps, Terraform IaC, zero-downtime PCF→OCF→Azure migration. "
            "Emphasize containerization, CI/CD pipelines, and infrastructure-as-code."
        ),
        "data_engineering": (
            "Lead with IBM DataStage, PySpark ETL pipelines, Oracle→PostgreSQL migration. "
            "Emphasize data modeling, multi-source integration, and warehouse work."
        ),
        "backend": (
            "Lead with microservices architecture, event-driven pub/sub, Spring Boot, "
            "98% SLA compliance on production forecasting app. "
            "Emphasize distributed systems debugging, on-call rotation, observability."
        ),
        "fullstack": (
            "Lead with Java/Spring Boot + Angular/TypeScript full ownership. "
            "Emphasize API design, end-to-end modernization, cross-functional product work."
        ),
        "ai_innovation": (
            "Lead with GitHub Copilot champion story: 35% org adoption, 3.5x target. "
            "Emphasize technical evangelism, AI tooling adoption, and measurable team impact."
        ),
        "iot": (
            "Lead with IoT Engineering degree, sPiCam project (FastAPI + Raspberry Pi + servo HAT), "
            "hardware/software integration, and Azure edge/cloud connectivity. "
            "Tie in LiveVox latency work (2.8ms web, 12.7ms iOS) as embedded-adjacent."
        ),
    }
    result = strategies.get(role_type.lower())
    if result:
        return f"Strategy for '{role_type}':\n\n{result}"
    return (
        f"Unknown role type: '{role_type}'\n"
        f"Available options: {', '.join(strategies)}"
    )


# ─── TOOLS: INTERVIEW & LEETCODE PREP ────────────────────────────────────────

@mcp.tool()
def get_interview_quick_reference() -> str:
    """
    Returns Frank's interview day quick reference: STAR stories, system design
    framework, behavioral talking points, questions to ask. Best used before
    any behavioral or system design interview.
    """
    return _read(QUICK_REFERENCE)


@mcp.tool()
def get_leetcode_cheatsheet(section: str = "") -> str:
    """
    Returns the full LeetCode / algorithm cheatsheet, or a specific section.

    section options (leave empty for full cheatsheet):
      arrays | linkedlist | trees | graphs | stacks | dp | system_design | strings
    """
    content = _read(LEETCODE_CHEATSHEET)
    if not section:
        return content

    # Try to isolate the requested section by header matching
    lines   = content.split("\n")
    result  = []
    inside  = False
    target  = section.lower()

    for line in lines:
        stripped = line.lstrip("#").strip().lower()
        is_header = line.startswith("#")

        if is_header and target in stripped:
            inside = True
        elif is_header and inside and target not in stripped:
            # Hit a same-or-higher-level header — stop
            if line.startswith("# ") or (line.startswith("## ") and not target in stripped):
                break

        if inside:
            result.append(line)

    if result:
        return "\n".join(result)
    return f"Section '{section}' not found. Returning full cheatsheet.\n\n{content}"


@mcp.tool()
def generate_interview_prep_context(
    company: str,
    role: str,
    stage: str = "phone_screen",
    job_description: str = "",
) -> str:
    """
    Packages Frank's master resume + quick reference for interview prep.
    Returns structured context for generating a company-specific prep document.

    stage options: phone_screen | technical_screen | coding_assessment
                   system_design | onsite | behavioral
    """
    master    = _read(MASTER_RESUME)
    quick_ref = _read(QUICK_REFERENCE)

    desc_block = f"\n──── JOB DESCRIPTION ────\n{job_description}" if job_description else ""

    return (
        f"═══ INTERVIEW PREP CONTEXT ═══\n"
        f"Company: {company}\n"
        f"Role:    {role}\n"
        f"Stage:   {stage}\n"
        f"{desc_block}\n\n"
        f"──── FRANK'S MASTER RESUME ────\n{master[:4000]}\n\n"
        f"──── QUICK REFERENCE / STAR STORIES ────\n{quick_ref[:3000]}\n\n"
        f"Use the above to produce:\n"
        f"  1. Top 5 things Frank must communicate for THIS role/stage\n"
        f"  2. Anticipated questions + suggested STAR responses\n"
        f"  3. Technical topics to review (if applicable)\n"
        f"  4. Smart questions for Frank to ask the interviewer\n"
        f"  5. Any gaps to proactively address\n"
        f"  6. Confidence anchors — Frank's strongest achievements relevant here\n"
    )


@mcp.tool()
def get_existing_prep_file(company: str) -> str:
    """
    Looks for an existing interview prep file for the given company.
    Searches the top-level Resume 2025 folder for matching .txt files.
    """
    matches = sorted(
        f for f in RESUME_FOLDER.glob("*.txt")
        if company.lower() in f.name.lower()
        and ("prep" in f.name.lower() or "interview" in f.name.lower() or "call" in f.name.lower())
    )
    if not matches:
        return f"No existing prep files found for '{company}'."

    lines = [f"Found {len(matches)} prep file(s) for '{company}':\n"]
    for m in matches:
        lines.append(f"──── {m.name} ────")
        lines.append(_read(m))
        lines.append("")
    return "\n".join(lines)


# ─── TOOLS: SPICAM SKILL SCANNER ──────────────────────────────────────────────

@mcp.tool()
def scan_spicam_for_skills() -> str:
    """
    Scans the sPiCam project codebase and returns:
      - Technologies / patterns detected
      - Suggested resume bullets
      - New skills not yet in the master resume
    """
    if not SPICAM_FOLDER.exists():
        return f"sPiCam folder not found at: {SPICAM_FOLDER}"

    tech_found: set[str] = set()
    file_inventory: list[str] = []

    SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".expo", "build", "dist"}

    for root, dirs, files in os.walk(SPICAM_FOLDER):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

        for fname in files:
            fpath = Path(root) / fname
            rel   = str(fpath.relative_to(SPICAM_FOLDER))
            ext   = fpath.suffix.lower()
            file_inventory.append(rel)

            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue

            # ── Python ──
            if ext == ".py":
                tech_found.add("Python")
                if "fastapi"          in text: tech_found.add("FastAPI")
                if "pydantic"         in text: tech_found.add("Pydantic")
                if "azure"            in text: tech_found.add("Azure Blob Storage")
                if "async def"        in text: tech_found.add("Python async/await")
                if "websocket"        in text: tech_found.add("WebSockets")
                if "pytest"           in text: tech_found.add("pytest")
                if "systemd"          in text: tech_found.add("systemd / Linux services")
                if "gpio"             in text or "rpi" in text: tech_found.add("Raspberry Pi GPIO")
                if "servo"            in text or "adafruit" in text: tech_found.add("Servo / Adafruit HAT")
                if "range"            in text and "http" in text: tech_found.add("HTTP Range requests")
                if "jwt"              in text or "bearer" in text: tech_found.add("JWT authentication")
                if "docker"           in text: tech_found.add("Docker")
                if "retention"        in text: tech_found.add("Automated retention policies")

            # ── TypeScript / React Native ──
            elif ext in (".ts", ".tsx", ".js", ".jsx"):
                tech_found.add("TypeScript/JavaScript")
                if "react-native"     in text or "react native" in text: tech_found.add("React Native")
                if "expo"             in text: tech_found.add("Expo")
                if "testflight"       in text: tech_found.add("iOS TestFlight deployment")

            # ── Swift ──
            elif ext == ".swift":
                tech_found.add("Swift / iOS")

            # ── Infrastructure ──
            elif fname == "Dockerfile":
                tech_found.add("Docker")
            elif fname in ("docker-compose.yml", "docker-compose.yaml"):
                tech_found.add("Docker Compose")
            elif ext in (".tf", ".tfvars"):
                tech_found.add("Terraform IaC")

    already_on_resume = {
        "Python", "FastAPI", "Azure Blob Storage", "React Native", "Pydantic",
        "iOS TestFlight deployment", "HTTP Range requests",
    }
    new_skills = sorted(tech_found - already_on_resume)

    lines = [
        "═══ SPICAM SKILL SCAN ═══",
        f"Files scanned: {len(file_inventory)}",
        "",
        "── All Technologies Detected ──",
    ]
    for t in sorted(tech_found):
        marker = "  ✓" if t in already_on_resume else "  ★ NEW"
        lines.append(f"{marker}  {t}")

    lines += [
        "",
        "── New Skills Not Yet on Master Resume ──",
    ]
    lines += [f"  • {s}" for s in new_skills] or ["  (none — master resume is up to date)"]

    lines += [
        "",
        "── Suggested Resume Bullets ──",
        "  • Built production IoT camera system integrating Raspberry Pi hardware, "
        "    servo HAT, Python/FastAPI backend, and React Native mobile app",
    ]
    if "Pydantic"              in tech_found: lines.append("  • Designed type-safe API layer with FastAPI + Pydantic models")
    if "Python async/await"    in tech_found: lines.append("  • Implemented async Python services for concurrent hardware + network I/O")
    if "Azure Blob Storage"    in tech_found: lines.append("  • Integrated Azure Blob Storage with automated 7-day retention management")
    if "HTTP Range requests"   in tech_found: lines.append("  • Enabled on-demand video streaming via HTTP Range request support")
    if "systemd / Linux services" in tech_found: lines.append("  • Configured systemd service for reliable auto-start on embedded Linux")
    if "WebSockets"            in tech_found: lines.append("  • Delivered real-time camera stream via WebSocket connections")
    if "JWT authentication"    in tech_found: lines.append("  • Secured API endpoints with JWT bearer-token authentication")

    return "\n".join(lines)


# ─── TOOLS: MENTAL HEALTH CHECK-INS ──────────────────────────────────────────

@mcp.tool()
def log_mental_health_checkin(
    mood: str,
    energy: int,
    notes: str = "",
    productive: bool = False,
) -> str:
    """
    Log a mental health check-in entry.

    mood:      e.g. 'good' | 'anxious' | 'depressed' | 'hyperfocus' | 'stable' | 'low' | 'motivated'
    energy:    1–10 scale (1 = can barely get out of bed, 10 = hyperfocus mode)
    notes:     optional free-text context
    productive: did you get meaningful work done today?
    """
    data = _load_json(HEALTH_LOG_FILE, {"entries": []})
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "date":      datetime.date.today().isoformat(),
        "mood":      mood,
        "energy":    max(1, min(10, int(energy))),
        "productive": bool(productive),
        "notes":     notes,
    }
    data.setdefault("entries", []).append(entry)
    _save_json(HEALTH_LOG_FILE, data)

    energy_int = entry["energy"]
    if energy_int <= 3 or mood in ("depressed", "low"):
        guidance = (
            "Low energy logged. Small wins count — "
            "even one LeetCode problem or one email sent is real progress. "
            "You're still moving, even on hard days."
        )
    elif mood == "hyperfocus" or energy_int >= 8:
        guidance = (
            "High energy logged. Good time for deep work. "
            "Just remember to eat, hydrate, and step away before burnout hits."
        )
    else:
        guidance = "Logged. You're doing the work, even when it's hard."

    return f"Check-in saved ({entry['date']}, energy {energy_int}/10, mood: {mood}).\n{guidance}"


@mcp.tool()
def get_mental_health_log(days: int = 14) -> str:
    """
    Returns mental health log entries from the last N days (default: 14).
    Includes average energy trend and any notable patterns.
    """
    data    = _load_json(HEALTH_LOG_FILE, {"entries": []})
    entries = data.get("entries", [])

    cutoff  = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    recent  = [e for e in entries if e.get("date", "") >= cutoff]

    if not recent:
        return f"No check-ins logged in the past {days} days."

    lines = [f"═══ MENTAL HEALTH LOG (last {days} days) ═══", ""]
    for e in reversed(recent):
        eng = e.get("energy", 0)
        bar = "🟥" if eng <= 3 else "🟨" if eng <= 6 else "🟩"
        prod = "✓" if e.get("productive") else "–"
        lines.append(
            f"{e['date']}  {bar}  mood: {e['mood']:<12}  energy: {eng}/10  productive: {prod}"
        )
        if e.get("notes"):
            lines.append(f"          ↳ {e['notes']}")

    avg = sum(e.get("energy", 0) for e in recent) / len(recent)
    lines += ["", f"Average energy over {days} days: {avg:.1f}/10"]

    # Trend note
    if avg <= 4:
        lines.append("⚠  Trend: extended low-energy period. Consider reaching out for support.")
    elif avg >= 7:
        lines.append("✓  Trend: strong energy. Keep the momentum going.")

    return "\n".join(lines)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
