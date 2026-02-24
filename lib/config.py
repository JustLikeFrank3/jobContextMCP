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

MASTER_RESUME: Path
LEETCODE_CHEATSHEET: Path
QUICK_REFERENCE: Path

RESUME_TEMPLATE_PNG: Path
COVER_LETTER_TEMPLATE_PNG: Path
TEMPLATE_FORMAT: Path
GM_AWARDS: Path
FEEDBACK_RECEIVED: Path
SKILLS_SHORTER: Path


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
    global STATUS_FILE, HEALTH_LOG_FILE, PERSONAL_CONTEXT_FILE, TONE_FILE, SCAN_INDEX_FILE, PEOPLE_FILE, LINKEDIN_POSTS_FILE
    global MASTER_RESUME, LEETCODE_CHEATSHEET, QUICK_REFERENCE
    global RESUME_TEMPLATE_PNG, COVER_LETTER_TEMPLATE_PNG, TEMPLATE_FORMAT
    global GM_AWARDS, FEEDBACK_RECEIVED, SKILLS_SHORTER

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

    MASTER_RESUME = RESUME_FOLDER / cfg["master_resume_path"]
    LEETCODE_CHEATSHEET = LEETCODE_FOLDER / cfg["leetcode_cheatsheet_path"]
    QUICK_REFERENCE = LEETCODE_FOLDER / cfg["quick_reference_path"]

    RESUME_TEMPLATE_PNG = RESUME_FOLDER / cfg["resume_template_png"]
    COVER_LETTER_TEMPLATE_PNG = RESUME_FOLDER / cfg["cover_letter_template_png"]
    TEMPLATE_FORMAT = RESUME_FOLDER / cfg["template_format_path"]
    GM_AWARDS = RESUME_FOLDER / cfg["gm_awards_path"]
    FEEDBACK_RECEIVED = RESUME_FOLDER / cfg["feedback_received_path"]
    SKILLS_SHORTER = RESUME_FOLDER / cfg["skills_shorter_path"]


_reconfigure(_load_config())
