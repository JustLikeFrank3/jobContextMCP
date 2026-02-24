import os
import subprocess
from pathlib import Path

from lib import config
from lib.io import _load_master_context


def _git_pull(folder: Path) -> str:
    """Attempt git pull on a project folder. Returns a one-line status string."""
    try:
        result = subprocess.run(
            ["git", "-C", str(folder), "pull"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return output or "Already up to date."
        return f"warning: {output}"
    except subprocess.TimeoutExpired:
        return "skipped: git pull timed out (>20s)"
    except FileNotFoundError:
        return "skipped: git not found in PATH"
    except Exception as e:
        return f"skipped: {e}"

# Maps each detected tech label to keywords that would appear in the master resume (lowercase).
# Any match → already on resume. Defaults to lowercased tech name if not listed.
_TECH_KEYWORDS: dict[str, list[str]] = {
    "Python":                       ["python"],
    "FastAPI":                       ["fastapi"],
    "Pydantic":                      ["pydantic"],
    "Azure Blob Storage":            ["azure blob"],
    "Python async/await":            ["async/await", "async def"],
    "WebSockets":                    ["websocket"],
    "pytest":                        ["pytest"],
    "systemd / Linux services":      ["systemd"],
    "Raspberry Pi GPIO":             ["gpio"],
    "Servo / Adafruit HAT":          ["servo"],
    "HTTP Range requests":           ["range request", "http range"],
    "JWT authentication":            ["jwt"],
    "Docker":                        ["docker"],
    "Automated retention policies":  ["retention"],
    "TypeScript/JavaScript":         ["typescript"],
    "React Native":                  ["react native"],
    "Expo":                          ["expo"],
    "iOS TestFlight deployment":     ["testflight"],
    "Swift / iOS":                   ["swift"],
    "Docker Compose":                ["docker compose"],
    "Terraform IaC":                 ["terraform"],
    "Model Context Protocol (MCP)":  ["model context protocol", "mcp server", "fastmcp"],
    "FastMCP":                       ["fastmcp"],
    "WeasyPrint / PDF generation":   ["weasyprint"],
    "RAG / semantic search":         ["rag", "faiss", "sentence_transformers", "text-embedding"],
}


def _scan_folder(folder: Path) -> tuple[set[str], int]:
    """Scan a single project folder and return (tech_found, file_count)."""
    tech_found: set[str] = set()
    file_count = 0
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".expo", "build", "dist"}

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

        for fname in files:
            fpath = Path(root) / fname
            ext = fpath.suffix.lower()
            file_count += 1

            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue

            if ext == ".py":
                tech_found.add("Python")
                if "fastapi" in text:
                    tech_found.add("FastAPI")
                if "pydantic" in text:
                    tech_found.add("Pydantic")
                if "azure" in text:
                    tech_found.add("Azure Blob Storage")
                if "async def" in text:
                    tech_found.add("Python async/await")
                if "websocket" in text:
                    tech_found.add("WebSockets")
                if "pytest" in text or "conftest" in fname:
                    tech_found.add("pytest")
                if "systemd" in text:
                    tech_found.add("systemd / Linux services")
                if "gpio" in text or "rpi" in text:
                    tech_found.add("Raspberry Pi GPIO")
                if "servo" in text or "adafruit" in text:
                    tech_found.add("Servo / Adafruit HAT")
                if "range" in text and "http" in text:
                    tech_found.add("HTTP Range requests")
                if "jwt" in text or "bearer" in text:
                    tech_found.add("JWT authentication")
                if "docker" in text:
                    tech_found.add("Docker")
                if "retention" in text:
                    tech_found.add("Automated retention policies")
                if "fastmcp" in text or "mcp.tool" in text:
                    tech_found.add("Model Context Protocol (MCP)")
                    tech_found.add("FastMCP")
                if "weasyprint" in text:
                    tech_found.add("WeasyPrint / PDF generation")
                if "faiss" in text or "sentence_transformers" in text or "text-embedding" in text:
                    tech_found.add("RAG / semantic search")
            elif ext in (".ts", ".tsx", ".js", ".jsx"):
                tech_found.add("TypeScript/JavaScript")
                if "react-native" in text or "react native" in text:
                    tech_found.add("React Native")
                if "expo" in text:
                    tech_found.add("Expo")
                if "testflight" in text:
                    tech_found.add("iOS TestFlight deployment")
            elif ext == ".swift":
                tech_found.add("Swift / iOS")
            elif fname == "Dockerfile":
                tech_found.add("Docker")
            elif fname in ("docker-compose.yml", "docker-compose.yaml"):
                tech_found.add("Docker Compose")
            elif ext in (".tf", ".tfvars"):
                tech_found.add("Terraform IaC")

    return tech_found, file_count


def scan_project_for_skills() -> str:
    """Scan all configured side-project directories (side_project_folders in config.json) and detect technologies used. Pulls latest changes from git before scanning each. Reports newly detected skills not yet on the master resume so they can be added."""
    folders = config.SIDE_PROJECT_FOLDERS
    if not folders:
        return "No side project folders configured. Add 'side_project_folders' (array) to config.json."

    missing = [str(f) for f in folders if not f.exists()]
    if missing:
        return "Side project folder(s) not found:\n" + "\n".join(f"  {m}" for m in missing)

    all_tech: set[str] = set()
    per_project: list[tuple[str, set[str], int, str]] = []  # (name, tech, file_count, pull_status)

    for folder in folders:
        pull_status = _git_pull(folder)
        tech, file_count = _scan_folder(folder)
        all_tech |= tech
        per_project.append((folder.name, tech, file_count, pull_status))

    resume_text = _load_master_context().lower()

    def _on_resume(tech: str) -> bool:
        keywords = _TECH_KEYWORDS.get(tech, [tech.lower()])
        return any(kw in resume_text for kw in keywords)

    already_on_resume = {t for t in all_tech if _on_resume(t)}
    new_skills = sorted(all_tech - already_on_resume)

    lines = ["═══ SIDE PROJECT SKILL SCAN ═══", ""]

    for name, tech, file_count, pull_status in per_project:
        lines.append(f"── {name} ({file_count} files, git pull: {pull_status}) ──")
        for t in sorted(tech):
            marker = "  ✓" if t in already_on_resume else "  ★ NEW"
            lines.append(f"{marker}  {t}")
        lines.append("")

    lines += ["── New Skills Not Yet on Master Resume (across all projects) ──"]
    lines += [f"  • {s}" for s in new_skills] or ["  (none — master resume is up to date)"]

    lines += [
        "",
        "── Suggested Resume Bullets ──",
    ]

    if "Raspberry Pi GPIO" in all_tech:
        lines.append("  • Built production IoT camera system integrating Raspberry Pi hardware, "
                     "servo HAT, Python/FastAPI backend, and React Native mobile app")
    if "Pydantic" in all_tech:
        lines.append("  • Designed type-safe API layer with FastAPI + Pydantic models")
    if "Python async/await" in all_tech:
        lines.append("  • Implemented async Python services for concurrent hardware + network I/O")
    if "Azure Blob Storage" in all_tech:
        lines.append("  • Integrated Azure Blob Storage with automated 7-day retention management")
    if "HTTP Range requests" in all_tech:
        lines.append("  • Enabled on-demand video streaming via HTTP Range request support")
    if "systemd / Linux services" in all_tech:
        lines.append("  • Configured systemd service for reliable auto-start on embedded Linux")
    if "WebSockets" in all_tech:
        lines.append("  • Delivered real-time camera stream via WebSocket connections")
    if "JWT authentication" in all_tech:
        lines.append("  • Secured API endpoints with JWT bearer-token authentication")
    if "Model Context Protocol (MCP)" in all_tech:
        lines.append("  • Built production MCP server enabling persistent AI context across job search sessions "
                     "via FastMCP (Python) with 30+ tools, RAG semantic search, and PDF generation")
    if "WeasyPrint / PDF generation" in all_tech:
        lines.append("  • Implemented PDF generation pipeline from plain .txt via WeasyPrint HTML/CSS templates")
    if "RAG / semantic search" in all_tech:
        lines.append("  • Built RAG semantic search layer over resume materials using text embeddings")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(scan_project_for_skills)
