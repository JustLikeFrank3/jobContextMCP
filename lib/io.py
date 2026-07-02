import json
import os
import datetime
from pathlib import Path

# When USE_SQLITE=1 (or true/yes), _load_json reads from SQLite instead of JSON.
# By default writes go to BOTH SQLite and JSON (dual-write audit trail).
# Set SQLITE_ONLY=1 to disable JSON writes once SQLite is the sole source of
# truth (e.g. in production AKS where the JSON files are not used).
_USE_SQLITE: bool = os.environ.get("USE_SQLITE", "").strip().lower() in ("1", "true", "yes")
_SQLITE_ONLY: bool = os.environ.get("SQLITE_ONLY", "").strip().lower() in ("1", "true", "yes")


def _resolve_data_path(path: Path) -> Path:
    """Reroute a DATA_FOLDER-relative path to the per-request user data dir.

    When a UserDataContextMiddleware has set an override (non-owner login),
    any path that lives under the global DATA_FOLDER is transparently redirected
    to the user's own partition.  Paths outside DATA_FOLDER (workspace files,
    config, etc.) are returned unchanged.
    """
    from lib.user_context import get_data_folder_override
    override = get_data_folder_override()
    if override is None:
        return path
    # Idempotency guard: if the path is already inside the user's partition,
    # return it untouched. Callers such as setup_workspace pass paths that are
    # already tenant-resolved (DATA_FOLDER/users/<oid>/x.json); re-applying the
    # override would double the partition (…/users/<oid>/users/<oid>/x.json).
    try:
        path.relative_to(override)
        return path
    except ValueError:
        pass
    import lib.config as _config
    try:
        relative = path.relative_to(_config.DATA_FOLDER)
        return override / relative
    except ValueError:
        return path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Error reading {path.name}: {e}]"


def _load_json(path: Path, default):
    path = _resolve_data_path(path)
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
    path = _resolve_data_path(path)
    if _USE_SQLITE:
        from lib.io_sqlite import save_to_sqlite
        save_to_sqlite(path, data)  # upsert to SQLite; no-op for unmapped files
    # Dual-write JSON unless SQLITE_ONLY=1.  Always write for unmapped files
    # (contact_crossref, linkedin_connections, rag_index, scan_index, etc.)
    # because those have no SQLite handler regardless of the flag.
    from lib.io_sqlite import _SAVE_HANDLERS  # type: ignore[attr-defined]
    is_mapped = path.name in _SAVE_HANDLERS
    if not (_USE_SQLITE and _SQLITE_ONLY and is_mapped):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")  # NOSONAR


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_master_context() -> str:
    """Read master resume + GM awards + peer feedback as one enriched context block.

    Use this everywhere instead of bare _read(config.MASTER_RESUME) so that
    recognition quotes and peer feedback are always available to the AI when
    drafting resumes, cover letters, fitment assessments, and interview prep.

    Respects the per-request workspace ContextVar so non-owner users get their
    own resume file rather than the global MASTER_RESUME path.
    """
    from lib import config  # local import avoids circular dependency

    # Dynamically resolve master resume path for the current user.
    master_path = config.get_active_master_resume_path()

    parts = [_read(master_path)]

    # Only append awards/feedback from the same workspace — never cross-tenant.
    # Resolve against the active workspace's 06-Reference-Materials/ so each
    # user gets their own files (or nothing, if they haven't uploaded them yet).
    ref_dir = config.get_active_reference_materials_dir()
    # achievements_path is the current key; gm_awards_path is the legacy key kept
    # for backward compatibility with config.json files that haven't been updated yet.
    _awards_val = (
        config.get_config_value("achievements_path", "")
        or config.get_config_value("gm_awards_path", "Achievements.txt")
    )
    awards_path = ref_dir / str(_awards_val).split("/")[-1]
    feedback_path = ref_dir / str(config.get_config_value("feedback_received_path", "Feedback_Received.txt")).split("/")[-1]

    awards_text = _read(awards_path)
    if not awards_text.startswith("[Error"):
        parts.append(
            "──── ACHIEVEMENTS ────\n"
            "(Peer-written quotes — use exact language in cover letters and fitment assessments)\n"
            + awards_text
        )

    feedback_text = _read(feedback_path)
    if not feedback_text.startswith("[Error"):
        parts.append(
            "──── PEER FEEDBACK (verbatim) ────\n"
            "(Direct quotes from managers and colleagues — high-value credibility signals)\n"
            + feedback_text
        )

    return "\n\n".join(parts)
