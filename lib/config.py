"""
Configuration loader for jobContextMCP.

Reads config.json (or config.example.json as fallback) and exposes
all path constants used across tools and server.py.
"""
from __future__ import annotations

import json
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# ── locate config.json ────────────────────────────────────────────────────────

_HERE = Path(__file__).parent.parent          # jobContextMCP/ root
_CONFIG_PATH = _HERE / "config.json"
_EXAMPLE_PATH = _HERE / "config.example.json"
_ACTIVE_CONFIG_CTX: ContextVar[dict[str, Any] | None] = ContextVar("active_config_ctx", default=None)


def _load_config() -> dict:
    """Load config.json; fall back to config.example.json on missing file."""
    for path in (_CONFIG_PATH, _EXAMPLE_PATH):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _merge_config(base: Any, override: Any) -> Any:
    """Recursively merge two config objects, preferring override values."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge_config(base.get(key), value) if key in base else value
        return merged
    return override


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
SIDE_PROJECT_REPOS: list[str] = _cfg.get("side_project_repos", [])

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
                                   "01-Current-Optimized/Resume - MASTER SOURCE.txt")

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
                                              "06-Reference-Materials/Resume - Template Format.txt")
ACHIEVEMENTS: Path            = _resume_path("achievements_path",
                                              "06-Reference-Materials/Achievements.txt")
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

# OID of the application owner — used to gate owner-only features (e.g. LaTeX export).
# Set via ENTRA_OWNER_OID env var; falls back to config.json "entra_owner_oid" key.
OWNER_OID: str = os.getenv("ENTRA_OWNER_OID", "") or _cfg.get("entra_owner_oid", "")


# ── Per-request workspace folder resolution ───────────────────────────────────
# In production (AKS) RESUME_FOLDER = DATA_FOLDER / "workspace".
# When a per-user data folder override is active (UserDataContextMiddleware),
# the user's workspace lives at override / "workspace" — mirroring the same
# relative layout so all derived paths stay correct.

def get_active_workspace_folder() -> Path:
    """Return the workspace folder for the current request.

    Uses the per-request DATA_FOLDER ContextVar when set (non-owner user),
    otherwise falls back to the global RESUME_FOLDER.
    """
    from lib.user_context import get_data_folder_override
    override = get_data_folder_override()
    if override is not None:
        return override / "workspace"
    return RESUME_FOLDER


def get_active_data_folder() -> Path:
    """Return the data folder for the current request.

    Uses the per-request DATA_FOLDER ContextVar when set (non-owner user),
    otherwise falls back to the global DATA_FOLDER.
    """
    from lib.user_context import get_data_folder_override
    override = get_data_folder_override()
    if override is not None:
        return override
    return DATA_FOLDER


def get_active_leetcode_folder() -> Path:
    """Return the LeetCode workspace folder for the current request.

    Uses the per-request DATA_FOLDER ContextVar when set (non-owner user),
    otherwise falls back to the global LEETCODE_FOLDER.
    """
    from lib.user_context import get_data_folder_override
    override = get_data_folder_override()
    if override is not None:
        return override / "workspace" / "leetcode"
    return LEETCODE_FOLDER


def get_active_workspace_path(relative: str) -> Path:
    """Join get_active_workspace_folder() with a relative path fragment."""
    return get_active_workspace_folder() / relative


def set_active_config(cfg: dict[str, Any] | None) -> object:
    """Bind a request-scoped config override. Returns a reset token."""
    return _ACTIVE_CONFIG_CTX.set(dict(cfg) if cfg is not None else None)


def reset_active_config(token: object) -> None:
    """Restore the previous request-scoped config override."""
    _ACTIVE_CONFIG_CTX.reset(token)  # type: ignore[arg-type]


def get_active_config() -> dict[str, Any]:
    """Return the config for the active request/tenant."""
    active = _ACTIVE_CONFIG_CTX.get()
    if active is not None:
        return active

    from lib.user_context import get_data_folder_override

    override = get_data_folder_override()
    if override is not None:
        user_config_path = override / "config.json"
        if user_config_path.exists():
            try:
                user_cfg = json.loads(user_config_path.read_text(encoding="utf-8"))
            except Exception:
                user_cfg = {}
            if isinstance(user_cfg, dict) and user_cfg:
                return _merge_config(_cfg, user_cfg)

    return _cfg


def get_config_value(key: str, default: Any = "") -> Any:
    """Return a config value for the active request/tenant."""
    return get_active_config().get(key, default)


def get_contact_info() -> dict[str, Any]:
    """Return the active request's contact config block.

    When a per-user data folder is active (multi-tenant / AKS mode) and that
    user has no config.json of their own, the base config's contact block is
    returned only if the requesting user is the app owner (OID matches
    OWNER_OID).  For all other users without their own config.json, an empty
    dict is returned to prevent leaking owner contact data.
    """
    from lib.user_context import get_data_folder_override, get_current_user_oid
    override = get_data_folder_override()
    if override is not None:
        # Per-user session: prefer the user's own config.json if present.
        user_config_path = override / "config.json"
        if user_config_path.exists():
            try:
                user_cfg = json.loads(user_config_path.read_text(encoding="utf-8"))
                contact = user_cfg.get("contact", {})
                return contact if isinstance(contact, dict) else {}
            except Exception:
                pass
        # No user-specific config — fall back to base config only for the owner.
        if OWNER_OID and get_current_user_oid() == OWNER_OID:
            contact = _cfg.get("contact", {})
            return contact if isinstance(contact, dict) else {}
        return {}
    contact = get_active_config().get("contact", {})
    return contact if isinstance(contact, dict) else {}


def get_contact_name(default: str = "") -> str:
    """Return the active request's display name."""
    contact_name = str(get_contact_info().get("name", "") or "").strip()
    if contact_name:
        return contact_name
    return str(get_config_value("name", default) or default)


def get_active_workspace_subdir(key: str, fallback: str) -> Path:
    """Resolve a workspace-relative config directory for the active request."""
    return get_active_workspace_folder() / str(get_config_value(key, fallback))


def get_active_side_project_folders() -> list[Path]:
    raw = get_config_value("side_project_folders", []) or []
    return [Path(str(p)).expanduser() for p in raw]


def get_active_side_project_repos() -> list[str]:
    return list(get_config_value("side_project_repos", []) or [])


def get_active_optimized_resumes_dir() -> Path:
    return get_active_workspace_subdir("optimized_resumes_dir", "01-Current-Optimized")


def get_active_cover_letters_dir() -> Path:
    return get_active_workspace_subdir("cover_letters_dir", "02-Cover-Letters")


def get_active_reference_materials_dir() -> Path:
    return get_active_workspace_subdir("reference_materials_dir", "06-Reference-Materials")


def get_active_job_assessments_dir() -> Path:
    return get_active_workspace_subdir("job_assessments_dir", "07-Job-Assessments")


def get_active_interview_prep_dir() -> Path:
    return get_active_workspace_subdir("interview_prep_docs_dir", "08-Interview-Prep-Docs")


def get_active_cover_letter_pdfs_dir() -> Path:
    return get_active_workspace_subdir("cover_letter_pdfs_dir", "09-Cover-Letter-PDFs")


def get_active_latex_resume_dir() -> Path:
    raw = str(get_config_value("latex_resume_dir", "") or "").strip()
    return Path(raw).expanduser() if raw else Path()


def get_active_leetcode_cheatsheet_path() -> Path:
    folder = get_active_leetcode_folder()
    return folder / str(get_config_value("leetcode_cheatsheet_path", "GM_Interview_Cheatsheet.md")) if str(folder) else Path()


def get_active_quick_reference_path() -> Path:
    folder = get_active_leetcode_folder()
    return folder / str(get_config_value("quick_reference_path", "INTERVIEW_DAY_QUICK_REFERENCE.md")) if str(folder) else Path()


def get_active_master_resume_path() -> Path:
    optimized_dir = get_active_optimized_resumes_dir()
    candidates = sorted(optimized_dir.glob("*MASTER SOURCE.txt")) if optimized_dir.exists() else []
    if candidates:
        return candidates[0]
    relative = str(get_config_value("master_resume_path", "01-Current-Optimized/Resume - MASTER SOURCE.txt"))
    return get_active_workspace_folder() / relative


# ── LLM client factory ────────────────────────────────────────────────────────

def get_llm_client(task: str = "") -> tuple[Any, str]:
    """Return (openai_client, model_name) for the configured LLM provider.

    Supported providers (config.json key ``llm_provider``):
      - ``"openai"``   (default) — calls api.openai.com
      - ``"ollama"``             — calls localhost:11434/v1 (OpenAI-compatible)
      - ``"foundry"``            — calls Azure AI Foundry endpoint (AzureOpenAI)

    Returns ``(None, "")`` when no API key is configured and provider is openai,
    allowing callers to gracefully degrade rather than crash.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None, ""

    active_cfg = get_active_config()
    provider = str(active_cfg.get("llm_provider", "openai")).lower()
    # LLM_PROVIDER env var overrides config.json (used in AKS / Docker deployments)
    provider = os.environ.get("LLM_PROVIDER", provider).lower()
    model = active_cfg.get("openai_model", "gpt-4o-mini")

    if provider == "ollama":
        ollama_base = active_cfg.get("ollama_base_url", "http://localhost:11434/v1")
        ollama_model = active_cfg.get("ollama_model", "llama3.1:8b")
        client = OpenAI(base_url=ollama_base, api_key="ollama")
        return client, ollama_model

    if provider == "foundry":
        try:
            from openai import AzureOpenAI
        except ImportError:
            return None, ""
        # Strip trailing /openai/v1 if present — AzureOpenAI adds its own path
        endpoint = str(active_cfg.get("azure_foundry_endpoint", "")).rstrip("/")
        if endpoint.endswith("/openai/v1"):
            endpoint = endpoint[: -len("/openai/v1")]
        deployment = active_cfg.get("azure_foundry_deployment", "gpt-4.1-mini")
        api_version = active_cfg.get("azure_foundry_api_version", "2025-01-01-preview")
        if not endpoint:
            return None, ""
        # Prefer explicit key (local dev / non-Azure CI). If absent, fall back to
        # DefaultAzureCredential — works automatically in AKS via workload identity
        # and locally via `az login`. No secret needed in production.
        api_key = os.environ.get("LLM_API_KEY") or active_cfg.get("azure_foundry_api_key", "")
        if api_key:
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            except ImportError:
                return None, ""
            scope = active_cfg.get("azure_foundry_scope", "https://ai.azure.com/.default")
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), scope)
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )
        return client, deployment

    # openai (default)
    # LLM_API_KEY env var overrides config.json openai_api_key
    api_key = os.environ.get("LLM_API_KEY") or active_cfg.get("openai_api_key", "")
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
    configured = get_config_value("generation_budgets", {})
    return {**defaults, **configured}


def get_github_metrics_config() -> dict:
    """Return the github_metrics config block (username + repos to track).

    Shape: {"username": str, "repos": [str, ...]}. Repo entries may be either
    bare names (combined with username) or full "owner/name" slugs.
    """
    block = get_config_value("github_metrics", {})
    if not isinstance(block, dict):
        return {"username": "", "repos": []}
    return {
        "username": block.get("username", ""),
        "repos": list(block.get("repos", []) or []),
    }


# ── reconfigure (called by server._reconfigure and tests) ────────────────────

def _reconfigure(cfg: dict) -> None:
    """Replace all module-level path constants from a new config dict.

    Called by server._reconfigure() and by the test suite's isolated_server
    fixture to redirect all file I/O to a temporary directory.
    """
    global _cfg
    global RESUME_FOLDER, LEETCODE_FOLDER, SIDE_PROJECT_FOLDERS, SIDE_PROJECT_REPOS, DATA_FOLDER
    global FB_FRIENDS_FOLDER, LATEX_RESUME_DIR
    global STATUS_FILE, HEALTH_LOG_FILE, PERSONAL_CONTEXT_FILE, TONE_FILE
    global SCAN_INDEX_FILE, PEOPLE_FILE, LINKEDIN_POSTS_FILE, REJECTIONS_FILE
    global INTERVIEWS_FILE, CONTACT_CROSSREF_FILE, LINKEDIN_CONNECTIONS_FILE
    global GITHUB_METRICS_FILE, JOB_QUEUE_FILE
    global MASTER_RESUME, LEETCODE_CHEATSHEET, QUICK_REFERENCE
    global RESUME_TEMPLATE_PNG, COVER_LETTER_TEMPLATE_PNG, TEMPLATE_FORMAT
    global ACHIEVEMENTS, FEEDBACK_RECEIVED, SKILLS_SHORTER
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
    SIDE_PROJECT_REPOS = cfg.get("side_project_repos", [])

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
                               "01-Current-Optimized/Resume - MASTER SOURCE.txt")
    TEMPLATE_FORMAT     = _res("template_format_path",
                               "06-Reference-Materials/Resume - Template Format.txt")
    ACHIEVEMENTS        = _res("achievements_path",
                               "06-Reference-Materials/Achievements.txt")
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
