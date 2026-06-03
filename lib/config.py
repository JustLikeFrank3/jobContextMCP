import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
_cfg: dict


RESUME_FOLDER: Path
LEETCODE_FOLDER: Path
SIDE_PROJECT_FOLDERS: list[Path]
DATA_FOLDER: Path

STATUS_FILE: Path
HEALTH_LOG_FILE: Path
PERSONAL_CONTEXT_FILE: Path
TONE_FILE: Path
SCAN_INDEX_FILE: Path
PEOPLE_FILE: Path
LINKEDIN_POSTS_FILE: Path
REJECTIONS_FILE: Path
INTERVIEWS_FILE: Path
JOB_QUEUE_FILE: Path
CONTACT_CROSSREF_FILE: Path
LINKEDIN_CONNECTIONS_FILE: Path
FB_FRIENDS_FOLDER: Path | None

MASTER_RESUME: Path
LEETCODE_CHEATSHEET: Path
QUICK_REFERENCE: Path

RESUME_TEMPLATE_PNG: Path
COVER_LETTER_TEMPLATE_PNG: Path
TEMPLATE_FORMAT: Path
GM_AWARDS: Path
FEEDBACK_RECEIVED: Path
SKILLS_SHORTER: Path
JOB_ASSESSMENTS_FOLDER: Path
INTERVIEW_PREP_FOLDER: Path
LATEX_RESUME_DIR: Path | None

SERPAPI_KEY: str


def _load_config() -> dict:
    config_path = _HERE / "config.json"
    if not config_path.exists():
        fallback = _HERE / "config.example.json"
        if fallback.exists():
            return json.loads(fallback.read_text(encoding="utf-8"))
        raise FileNotFoundError(
            f"config.json not found at {config_path}\n"
            "Copy config.example.json → config.json and fill in your paths."
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


def _reconfigure(cfg: dict) -> None:
    global _cfg
    global RESUME_FOLDER, LEETCODE_FOLDER, SIDE_PROJECT_FOLDERS, DATA_FOLDER
    global STATUS_FILE, HEALTH_LOG_FILE, PERSONAL_CONTEXT_FILE, TONE_FILE, SCAN_INDEX_FILE, PEOPLE_FILE, LINKEDIN_POSTS_FILE, REJECTIONS_FILE, INTERVIEWS_FILE, JOB_QUEUE_FILE
    global CONTACT_CROSSREF_FILE, LINKEDIN_CONNECTIONS_FILE, FB_FRIENDS_FOLDER
    global MASTER_RESUME, LEETCODE_CHEATSHEET, QUICK_REFERENCE
    global RESUME_TEMPLATE_PNG, COVER_LETTER_TEMPLATE_PNG, TEMPLATE_FORMAT
    global GM_AWARDS, FEEDBACK_RECEIVED, SKILLS_SHORTER
    global JOB_ASSESSMENTS_FOLDER, INTERVIEW_PREP_FOLDER, LATEX_RESUME_DIR
    global SERPAPI_KEY

    _cfg = dict(cfg)

    RESUME_FOLDER = Path(cfg["resume_folder"])
    LEETCODE_FOLDER = Path(cfg["leetcode_folder"])
    # Support both legacy single string and new array format
    _spf = cfg.get("side_project_folders") or cfg.get("side_project_folder")
    if isinstance(_spf, list):
        SIDE_PROJECT_FOLDERS = [Path(p) for p in _spf]
    else:
        SIDE_PROJECT_FOLDERS = [Path(_spf)] if _spf else []
    DATA_FOLDER = Path(cfg["data_folder"])

    STATUS_FILE = DATA_FOLDER / "status.json"
    HEALTH_LOG_FILE = DATA_FOLDER / "mental_health_log.json"
    PERSONAL_CONTEXT_FILE = DATA_FOLDER / "personal_context.json"
    TONE_FILE = DATA_FOLDER / "tone_samples.json"
    SCAN_INDEX_FILE = DATA_FOLDER / "scan_index.json"
    PEOPLE_FILE = DATA_FOLDER / "people.json"
    LINKEDIN_POSTS_FILE = DATA_FOLDER / "linkedin_posts.json"
    REJECTIONS_FILE = DATA_FOLDER / "rejections.json"
    INTERVIEWS_FILE = DATA_FOLDER / "interviews.json"
    JOB_QUEUE_FILE = DATA_FOLDER / "job_queue.json"
    CONTACT_CROSSREF_FILE = DATA_FOLDER / "contact_crossref.json"
    LINKEDIN_CONNECTIONS_FILE = DATA_FOLDER / "linkedin_connections.json"
    _fb_raw = cfg.get("fb_friends_folder", "")
    FB_FRIENDS_FOLDER = Path(_fb_raw) if _fb_raw else None

    JOB_ASSESSMENTS_FOLDER = RESUME_FOLDER / cfg.get("job_assessments_dir", "07-Job-Assessments")
    INTERVIEW_PREP_FOLDER = RESUME_FOLDER / cfg.get("interview_prep_docs_dir", "08-Interview-Prep-Docs")
    _latex_dir = cfg.get("latex_resume_dir", "")
    LATEX_RESUME_DIR = Path(_latex_dir) if _latex_dir else None

    MASTER_RESUME = RESUME_FOLDER / cfg["master_resume_path"]
    LEETCODE_CHEATSHEET = LEETCODE_FOLDER / cfg.get("leetcode_cheatsheet_path", "Algorithm_Cheatsheet.md")
    QUICK_REFERENCE = LEETCODE_FOLDER / cfg.get("quick_reference_path", "Interview_Quick_Reference.md")

    RESUME_TEMPLATE_PNG = RESUME_FOLDER / cfg.get("resume_template_png", "06-Reference-Materials/resume_template.png")
    COVER_LETTER_TEMPLATE_PNG = RESUME_FOLDER / cfg.get("cover_letter_template_png", "06-Reference-Materials/cover_letter_template.png")
    TEMPLATE_FORMAT = RESUME_FOLDER / cfg.get("template_format_path", "06-Reference-Materials/Template Format.txt")
    GM_AWARDS = RESUME_FOLDER / cfg.get("gm_awards_path", "06-Reference-Materials/Awards.txt")
    FEEDBACK_RECEIVED = RESUME_FOLDER / cfg.get("feedback_received_path", "06-Reference-Materials/Feedback.txt")
    SKILLS_SHORTER = RESUME_FOLDER / cfg.get("skills_shorter_path", "06-Reference-Materials/Skills Shorter.txt")

    SERPAPI_KEY = cfg.get("serpapi_key", "")

    LLM_PROVIDER = cfg.get("llm_provider", "openai")
    OLLAMA_BASE_URL = cfg.get("ollama_base_url", "http://localhost:11434/v1")
    OLLAMA_MODEL = cfg.get("ollama_model", "llama3.1:8b")


def get_llm_client(task: str = ""):
    """Return (client, model_name) for whichever provider is configured.

    llm_provider = "ollama"  → points the OpenAI SDK at the local Ollama server.
                               No real API key needed; we pass a dummy string.
    llm_provider = "openai"  → normal OpenAI cloud call (default).

    The OpenAI Python SDK is compatible with any OpenAI-spec server, so Ollama
    works by just swapping base_url and model name — no other code changes needed.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None, None

    cfg = _load_config()
    provider = cfg.get("llm_provider", "openai")

    if provider == "ollama":
        base_url = cfg.get("ollama_base_url", "http://localhost:11434/v1")
        model = cfg.get("ollama_model", "llama3.1:8b")
        if task == "assessment":
            model = cfg.get("ollama_model_assessment", model)
        client = OpenAI(base_url=base_url, api_key="ollama")
        return client, model

    # default: openai
    key = cfg.get("openai_api_key", "")
    if not key or key.startswith("sk-..."):
        return None, None
    model = cfg.get("openai_model", "gpt-4o")
    if task == "assessment":
        model = cfg.get("openai_model_assessment", model)
    client = OpenAI(api_key=key)
    return client, model


# ── Generation token budgets ────────────────────────────────────────────────

_DEFAULT_GENERATION_BUDGETS = {
    "personal_context_token_budget": 1500,
    "max_personal_stories": 8,
    "cover_letter_max_tokens": 12000,
    "resume_max_tokens": 12000,
    "safety_margin_tokens": 500,
}


def get_generation_budgets() -> dict:
    """Return generation token budgets, merging config over built-in defaults.

    Centralizes the hard limits that keep generation prompts under the model
    TPM ceiling regardless of how large personal_context.json grows.
    """
    budgets = dict(_DEFAULT_GENERATION_BUDGETS)
    configured = _cfg.get("generation_budgets", {}) if isinstance(_cfg, dict) else {}
    if isinstance(configured, dict):
        for k, v in configured.items():
            if isinstance(v, int) and v >= 0:
                budgets[k] = v
    return budgets


_reconfigure(_load_config())
