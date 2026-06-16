import json
import os
import datetime
from pathlib import Path

# When USE_SQLITE=1 (or true/yes), _load_json reads from SQLite instead of JSON.
# Writes still go to JSON; run scripts/migrate_to_sqlite.py to re-sync.
_USE_SQLITE: bool = os.environ.get("USE_SQLITE", "").strip().lower() in ("1", "true", "yes")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Error reading {path.name}: {e}]"


def _load_json(path: Path, default):
    if _USE_SQLITE:
        from lib.io_sqlite import load_from_sqlite, SQLITE_NO_HANDLER
        result = load_from_sqlite(path, default)
        if result is not SQLITE_NO_HANDLER:
            return result
        # Unmapped file — fall through to JSON below

    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    if _USE_SQLITE:
        from lib.io_sqlite import save_to_sqlite
        save_to_sqlite(path, data)  # upsert to SQLite; no-op for unmapped files
    # Always write JSON too (dual-write): keeps JSON in sync as audit trail
    # and handles unmapped files + hbdi_profile which are not in SQLite.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_master_context() -> str:
    """Read master resume + GM awards + peer feedback as one enriched context block.

    Use this everywhere instead of bare _read(config.MASTER_RESUME) so that
    recognition quotes and peer feedback are always available to the AI when
    drafting resumes, cover letters, fitment assessments, and interview prep.
    """
    from lib import config  # local import avoids circular dependency

    parts = [_read(config.MASTER_RESUME)]

    awards_text = _read(config.GM_AWARDS)
    if not awards_text.startswith("[Error"):
        parts.append(
            "──── GM RECOGNITION AWARDS ────\n"
            "(Peer-written quotes — use exact language in cover letters and fitment assessments)\n"
            + awards_text
        )

    feedback_text = _read(config.FEEDBACK_RECEIVED)
    if not feedback_text.startswith("[Error"):
        parts.append(
            "──── PEER FEEDBACK (verbatim) ────\n"
            "(Direct quotes from managers and colleagues — high-value credibility signals)\n"
            + feedback_text
        )

    return "\n\n".join(parts)
