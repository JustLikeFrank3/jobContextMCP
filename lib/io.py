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


def _format_personal_stories(stories_token_budget: int | None = None) -> str:
    """Render personal stories + STAR stories as one plain-text block.

    Reads config.PERSONAL_CONTEXT_FILE through _load_json (SQLite-aware,
    partition-aware). Order is file order — deterministic, never query-ranked —
    and *stories_token_budget* trims whole stories from the tail, so a budgeted
    caller's block is always an exact prefix of an unbudgeted caller's block.
    That prefix property is what lets the eval judge (unbudgeted) verify every
    story fact a budgeted generator could have cited.
    """
    from lib import config  # local import avoids circular dependency

    data = _load_json(config.PERSONAL_CONTEXT_FILE, {})
    if not isinstance(data, dict):
        return ""

    blocks: list[str] = []
    for s in data.get("stories") or []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip()
        body = str(s.get("story", "")).strip()
        if not (title or body):
            continue
        blocks.append(f"• {title}\n{body}".strip())
    for s in data.get("star_stories") or []:
        if not isinstance(s, dict):
            continue
        lines = [f"• {str(s.get('title', '')).strip()} (STAR)"]
        for label in ("situation", "task", "action", "result"):
            value = str(s.get(label, "")).strip()
            if value:
                lines.append(f"  {label.capitalize()}: {value}")
        metrics = [str(m).strip() for m in (s.get("metric_bullets") or []) if str(m).strip()]
        if metrics:
            lines.append("  Metrics: " + "; ".join(metrics))
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    if stories_token_budget is not None:
        # Same estimator the prompt builders use to measure headroom (tiktoken
        # when installed, chars/4 otherwise). Mixing estimators here — chars/4
        # trim vs tiktoken headroom — let a "fitting" stories section overshoot
        # the ceiling, and the last-resort ceiling guard truncates the prompt
        # TAIL, i.e. the format spec, not the stories (caught by CI, where
        # tiktoken is installed, on the first qa run of this feature). Whole-
        # story granularity: a half-story invites the model to complete it.
        from lib.story_retrieval import estimate_tokens  # noqa: PLC0415 — lazy: story_retrieval imports lib.io

        kept: list[str] = []
        used = 0
        for block in blocks:
            cost = estimate_tokens(block) + 2  # +2 ≈ the "\n\n" join
            if used + cost > stories_token_budget:
                break
            kept.append(block)
            used += cost
        blocks = kept

    return "\n\n".join(blocks)


def _load_master_context(stories_token_budget: int | None = None) -> str:
    """Read master resume + GM awards + peer feedback + personal stories as one
    enriched context block — THE source-of-truth bundle.

    Use this everywhere instead of bare _read(config.MASTER_RESUME) so that
    recognition quotes, peer feedback, and story facts are always available to
    the AI when drafting resumes, cover letters, fitment assessments, and
    interview prep — and, symmetrically, to the eval judge scoring those
    documents. Generator and judge consuming the same loader is what makes
    "hallucination" mean fabrication rather than "sourced from a section the
    judge wasn't shown" (the 2026-08 story blind spot).

    *stories_token_budget* trims only the STORIES section, tail-first and
    deterministically (see _format_personal_stories): pass a budget from
    prompt-assembly code that must respect a token ceiling; pass None (the
    default) to get everything — the judge and other verification paths must
    never pass a budget, or the blind spot returns via truncation.

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

    # Stories are part of the citable source of truth: facts stated here may be
    # used in generated documents exactly as written. This section is LAST so a
    # token-budgeted trim only ever shortens the stories tail — the sections
    # above stay byte-identical for every consumer of the bundle.
    stories_header = (
        "──── STORIES (first-person stories — part of the source of truth) ────\n"
        "(Facts, numbers, names, and dates below are citable exactly as written; "
        "adapt wording to the target role but never alter a number, name, or date)\n"
    )
    if stories_token_budget is None:
        effective_budget = None
    else:
        # The header spends from the same budget the caller measured headroom
        # for — an uncounted header is a small, silent ceiling overshoot.
        from lib.story_retrieval import estimate_tokens  # noqa: PLC0415 — lazy: story_retrieval imports lib.io

        effective_budget = max(0, stories_token_budget - estimate_tokens(stories_header))
    stories_text = _format_personal_stories(effective_budget)
    if stories_text:
        parts.append(stories_header + stories_text)

    return "\n\n".join(parts)
