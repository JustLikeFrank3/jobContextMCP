"""Persistent dismissals for derived to-do surfaces.

The follow-up queue and Home priorities are DERIVED views over people.json
and the application log — there is no row to delete when an entry stops
making sense (a ghosted recruiter, a priority that's just wrong). This module
is the per-user overlay that records "stop showing me this": keyed by
(kind, key), optionally expiring, stored in the user's partition via lib.io
so it tenant-resolves and syncs like every other workspace file.

Kinds in use:
  "followup"  key = the contact's name (people.json rows have no id)
  "priority"  key = the exact priority text (they are regenerated daily;
              an expiring dismissal lets a genuinely recurring priority
              resurface later instead of being buried forever)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib import config
from lib.io import _load_json, _save_json


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> list[dict]:
    data = _load_json(config.DISMISSALS_FILE, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    return [i for i in items if isinstance(i, dict)]


def _save(items: list[dict]) -> None:
    _save_json(config.DISMISSALS_FILE, {"items": items})


def _is_active(item: dict) -> bool:
    until = item.get("until")
    if not until:
        return True  # permanent
    try:
        return _now() < datetime.fromisoformat(until)
    except ValueError:
        return True  # unparseable expiry: safer to keep it dismissed


def dismiss(kind: str, key: str, days: int | None = None) -> None:
    """Record (or refresh) a dismissal. days=None means permanent."""
    key = (key or "").strip()
    if not key:
        return
    items = [i for i in _load() if not (i.get("kind") == kind and i.get("key") == key)]
    items.append({
        "kind": kind,
        "key": key,
        "dismissed_at": _now().isoformat(),
        "until": (_now() + timedelta(days=days)).isoformat() if days else None,
    })
    _save(items)


def restore(kind: str, key: str) -> None:
    """Remove a dismissal so the entry can surface again."""
    _save([i for i in _load() if not (i.get("kind") == kind and i.get("key") == key)])


def active_keys(kind: str) -> set[str]:
    """The currently-dismissed keys for *kind* (expired ones don't count)."""
    return {
        str(i.get("key"))
        for i in _load()
        if i.get("kind") == kind and i.get("key") and _is_active(i)
    }
