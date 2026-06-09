"""
Configuration loader for jobContextMCP.

Reads config.json (or config.example.json as fallback) and exposes
all path constants used across tools and server.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── locate config.json ────────────────────────────────────────────────────────

_HERE = Path(__file__).parent.parent          # jobContextMCP/ root
_CONFIG_PATH = _HERE / "config.json"
_EXAMPLE_PATH = _HERE / "config.example.json"


def _load_config() -> dict:
    """Load config.json; fall back to config.example.json on missing file."""
    for path in (_CONFIG_PATH, _EXAMPLE_PATH):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


# ── mutable config state ──────────────────────────────────────────────────────

_cfg: dict = _load_config()

# ── derived path helpers ──────────────────────────────────────────────────────

def _p(key: str, fallback: str = "") -> Path:
    """Resolve a config key to an absolute Path."""
    raw = _cfg.get(key, fallback)
    if not raw:
        return Path(fallback) if fallback else Path()
    return Path(raw).expanduser()


def _resume_path(relative_key: str, fallback: str = "") -> Path:
    """Join RESUME_FOLDER with a config-specified relative path."""
    rel = _cfg.get(relative_key, fallback)
    if not rel:
        return RESUME_FOLDER / fallback
    return RESUME_FOLDER / rel


# ── primary folder paths ──────────────────────────────────────────────────────

RESUME_FOLDER: Path = _p("resume_folder")
LEETCODE_FOLDER: Path = _p("leetcode_folder")
DATA_FOLDER: Path = _p("data_folder")
FB_FRIENDS_FOLDER: Path = _p("fb_friends_folder")

SIDE_PROJECT_FOLDERS: list[Path] = [
    Path(p).expanduser() for p in _cfg.get("side_project_folders", [])
]

LATEX_RESUME_DIR: Path = _p("latex_resume_dir")

# ── data file paths ───────────────────────────────────────────────────────────

STATUS_FILE: Path               = DATA_FOLDER / "status.json"
HEALTH_LOG_FILE: Path           = DATA_FOLDER / "mental_health_log.json"
PERSONAL_CONTEXT_FILE: Path     = DATA_FOLDER / "personal_context.json"
TONE_FILE: Path                 = DATA_FOLDER / "tone_samples.json"
SCAN_INDEX_FILE: Path           = DATA_FOLDER / "scan_index.json"
PEOPLE_FILE: Path               = DATA_FOLDER / "people.json"
LINKEDIN_POSTS_FILE: Path       = DATA_FOLDER / "linkedin_posts.json"
REJECTIONS_FILE: Path           = DATA_FOLDER / "rejections.json"
INTERVIEWS_FILE: Path           = DATA_FOLDER / "interviews.json"
CONTACT_CROSSREF_FILE: Path     = DATA_FOLDER / "contact_crossref.json"
LINKEDIN_CONNECTIONS_FILE: Path = DATA_FOLDER / "linkedin_connections.json"
GITHUB_METRICS_FILE: Path       = DATA_FOLDER / "github_metrics.json"
JOB_QUEUE_FILE: Path            = DATA_FOLDER / "job_queue.json"

# ── resume / reference file paths ────────────────────────────────────────────

MASTER_RESUME: Path = _resume_path("master_resume_path",
                                   "01-Current-Optimized/Frank Vladmir MacBride III Resume - MASTER SOURCE.txt")

LEETCODE_CHEATSHEET: Path = (
    LEETCODE_FOLDER / _cfg.get("leetcode_cheatsheet_path", "GM_Interview_Cheatsheet.md")
    if _cfg.get("leetcode_folder")
    else Path()
)

QUICK_REFERENCE: Path = (
    LEETCODE_FOLDER / _cfg.get("quick_reference_path", "INTERVIEW_DAY_QUICK_REFERENCE.md")
    if _cfg.get("leetcode_folder")
    else Path()
)

RESUME_TEMPLATE_PNG: Path     = _resume_path("resume_template_png",
                                              "06-Reference-Materials/resume_template.png")
COVER_LETTER_TEMPLATE_PNG: Path = _resume_path("cover_letter_template_png",
                                                "06-Reference-Materials/cover_letter_template.png")
TEMPLATE_FORMAT: Path         = _resume_path("template_format_path",
                                              "06-Reference-Materials/Frank MacBride Resume - Template Format.txt")
GM_AWARDS: Path               = _resume_path("gm_awards_path",
                                              "06-Reference-Materials/GM Recognition Awards.txt")
FEEDBACK_RECEIVED: Path       = _resume_path("feedback_received_path",
                                              "06-Reference-Materials/Feedback_Received.txt")
SKILLS_SHORTER: Path          = _resume_path("skills_shorter_path",
                                              "06-Reference-Materials/Skills - 10% Shorter.txt")

# ── folder paths derived from resume_folder ──────────────────────────────────

INTERVIEW_PREP_FOLDER: Path = RESUME_FOLDER / _cfg.get("interview_prep_docs_dir",
                                                         "08-Interview-Prep-Docs")
JOB_ASSESSMENTS_FOLDER: Path = RESUME_FOLDER / _cfg.get("job_assessments_dir",
                                                          "07-Job-Assessments")

# ── misc ──────────────────────────────────────────────────────────────────────

SERPAPI_KEY: str = _cfg.get("serpapi_key", "")


# ── LLM client factory ────────────────────────────────────────────────────────

def get_llm_client(task: str = "") -> tuple[Any, str]:
    """Return (openai_client, model_name) for the configured LLM provider.

    Supported providers (config.json key ``llm_provider``):
      - ``"openai"``  (default) — calls api.openai.com
      - ``"ollama"``            — calls localhost:11434/v1 (OpenAI-compatible)

    Returns ``(None, "")`` when no API key is configured and provider is openai,
    allowing callers to gracefully degrade rather than crash.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None, ""

    provider = _cfg.get("llm_provider", "openai").lower()
    model = _cfg.get("openai_model", "gpt-4o-mini")

    if provider == "ollama":
        ollama_base = _cfg.get("ollama_base_url", "http://localhost:11434/v1")
        ollama_model = _cfg.get("ollama_model", "llama3.1:8b")
        client = OpenAI(base_url=ollama_base, api_key="ollama")
        return client, ollama_model

    # openai (default)
    api_key = _cfg.get("openai_api_key", "")
    if not api_key:
        return None, ""
    client = OpenAI(api_key=api_key)
    return client, model


# ── generation budget helper ──────────────────────────────────────────────────

def get_generation_budgets() -> dict:
    """Return token/count budgets for AI generation calls."""
    defaults = {
        "personal_context_token_budget": 1500,
        "max_personal_stories": 8,
        "tone_token_budget": 1500,
        "max_tone_samples": 6,
        "cover_letter_max_tokens": 12000,
        "resume_max_tokens": 12000,
        "safety_margin_tokens": 500,
    }
    configured = _cfg.get("generation_budgets", {})
    return {**defaults, **configured}


# ── reconfigure (called by server._reconfigure and tests) ────────────────────

def _reconfigure(cfg: dict) -> None:
    """Replace all module-level path constants from a new config dict.

    Called by server._reconfigure() and by the test suite's isolated_server
    fixture to redirect all file I/O to a temporary directory.
    """
    global _cfg
    global RESUME_FOLDER, LEETCODE_FOLDER, SIDE_PROJECT_FOLDERS, DATA_FOLDER
    global FB_FRIENDS_FOLDER, LATEX_RESUME_DIR
    global STATUS_FILE, HEALTH_LOG_FILE, PERSONAL_CONTEXT_FILE, TONE_FILE
    global SCAN_INDEX_FILE, PEOPLE_FILE, LINKEDIN_POSTS_FILE, REJECTIONS_FILE
    global INTERVIEWS_FILE, CONTACT_CROSSREF_FILE, LINKEDIN_CONNECTIONS_FILE
    global GITHUB_METRICS_FILE, JOB_QUEUE_FILE
    global MASTER_RESUME, LEETCODE_CHEATSHEET, QUICK_REFERENCE
    global RESUME_TEMPLATE_PNG, COVER_LETTER_TEMPLATE_PNG, TEMPLATE_FORMAT
    global GM_AWARDS, FEEDBACK_RECEIVED, SKILLS_SHORTER
    global INTERVIEW_PREP_FOLDER, JOB_ASSESSMENTS_FOLDER
    global SERPAPI_KEY

    _cfg = cfg

    def _rp(key: str, fallback: str = "") -> Path:
        raw = cfg.get(key, fallback)
        return Path(raw).expanduser() if raw else Path(fallback)

    RESUME_FOLDER   = _rp("resume_folder")
    LEETCODE_FOLDER = _rp("leetcode_folder")
    DATA_FOLDER     = _rp("data_folder")
    FB_FRIENDS_FOLDER = _rp("fb_friends_folder")
    LATEX_RESUME_DIR  = _rp("latex_resume_dir")

    SIDE_PROJECT_FOLDERS = [
        Path(p).expanduser() for p in cfg.get("side_project_folders", [])
    ]

    # data files
    STATUS_FILE               = DATA_FOLDER / "status.json"
    HEALTH_LOG_FILE           = DATA_FOLDER / "mental_health_log.json"
    PERSONAL_CONTEXT_FILE     = DATA_FOLDER / "personal_context.json"
    TONE_FILE                 = DATA_FOLDER / "tone_samples.json"
    SCAN_INDEX_FILE           = DATA_FOLDER / "scan_index.json"
    PEOPLE_FILE               = DATA_FOLDER / "people.json"
    LINKEDIN_POSTS_FILE       = DATA_FOLDER / "linkedin_posts.json"
    REJECTIONS_FILE           = DATA_FOLDER / "rejections.json"
    INTERVIEWS_FILE           = DATA_FOLDER / "interviews.json"
    CONTACT_CROSSREF_FILE     = DATA_FOLDER / "contact_crossref.json"
    LINKEDIN_CONNECTIONS_FILE = DATA_FOLDER / "linkedin_connections.json"
    GITHUB_METRICS_FILE       = DATA_FOLDER / "github_metrics.json"
    JOB_QUEUE_FILE            = DATA_FOLDER / "job_queue.json"

    def _res(key: str, fallback: str) -> Path:
        return RESUME_FOLDER / cfg.get(key, fallback)

    MASTER_RESUME       = _res("master_resume_path",
                               "01-Current-Optimized/Frank Vladmir MacBride III Resume - MASTER SOURCE.txt")
    TEMPLATE_FORMAT     = _res("template_format_path",
                               "06-Reference-Materials/Frank MacBride Resume - Template Format.txt")
    GM_AWARDS           = _res("gm_awards_path",
                               "06-Reference-Materials/GM Recognition Awards.txt")
    FEEDBACK_RECEIVED   = _res("feedback_received_path",
                               "06-Reference-Materials/Feedback_Received.txt")
    SKILLS_SHORTER      = _res("skills_shorter_path",
                               "06-Reference-Materials/Skills - 10% Shorter.txt")
    RESUME_TEMPLATE_PNG = _res("resume_template_png",
                               "06-Reference-Materials/resume_template.png")
    COVER_LETTER_TEMPLATE_PNG = _res("cover_letter_template_png",
                                     "06-Reference-Materials/cover_letter_template.png")

    lc = LEETCODE_FOLDER
    LEETCODE_CHEATSHEET = lc / cfg.get("leetcode_cheatsheet_path", "GM_Interview_Cheatsheet.md") if str(lc) else Path()
    QUICK_REFERENCE     = lc / cfg.get("quick_reference_path", "INTERVIEW_DAY_QUICK_REFERENCE.md") if str(lc) else Path()

    INTERVIEW_PREP_FOLDER  = RESUME_FOLDER / cfg.get("interview_prep_docs_dir", "08-Interview-Prep-Docs")
    JOB_ASSESSMENTS_FOLDER = RESUME_FOLDER / cfg.get("job_assessments_dir", "07-Job-Assessments")

    SERPAPI_KEY = cfg.get("serpapi_key", "")
