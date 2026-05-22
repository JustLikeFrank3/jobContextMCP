"""
Contact cross-reference tool — multi-platform contact intelligence.

Cross-references Facebook contacts with LinkedIn connections and the internal
people tracker to surface shared contacts, gaps, and relationship signals
across platforms.

Facebook sources ingested (real relationships only, no suggestions):
  your_friends.json            — confirmed mutual friends
  sent_friend_requests.json    — pending requests Frank sent
  received_friend_requests.json — pending requests Frank received
  removed_friends.json         — formerly connected

Tools:
  run_contact_crossref  — ingest a Facebook export folder and regenerate the registry
  get_contact_crossref  — query the stored registry by insight bucket or name
"""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from lib import config
from lib.io import _load_json, _save_json, _now


# ---------------------------------------------------------------------------
# File path helpers (resolved at call-time so config changes are picked up)
# ---------------------------------------------------------------------------

def _crossref_file() -> Path:
    return config.DATA_FOLDER / "contact_crossref.json"


def _linkedin_file() -> Path:
    return config.DATA_FOLDER / "linkedin_connections.json"


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return " ".join(name.split())


def _first_last(name: str) -> tuple[str, str]:
    parts = _normalize(name).split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return (parts[0] if parts else ""), ""


def _name_keys(raw: str) -> list[str]:
    norm = _normalize(raw)
    fl, ll = _first_last(raw)
    keys = [norm]
    shortform = f"{fl} {ll}"
    if fl and ll and shortform != norm:
        keys.append(shortform)
    return keys


# ---------------------------------------------------------------------------
# Facebook loaders
# ---------------------------------------------------------------------------

_FB_WEIGHT = {"friend": 4, "pending_received": 3, "pending_sent": 2, "removed": 1}

_FB_FILES = {
    "your_friends.json":             ("friends_v2",          "friend"),
    "sent_friend_requests.json":     ("sent_requests_v2",    "pending_sent"),
    "received_friend_requests.json": ("received_requests_v2","pending_received"),
    "removed_friends.json":          ("deleted_friends_v2",  "removed"),
}


def _load_fb_entries(fb_folder: Path) -> tuple[list[dict], dict[str, int]]:
    """Load all real-relationship FB files. Returns (entries, counts_by_type)."""
    entries: list[dict] = []
    counts: dict[str, int] = {}
    for filename, (key, rel_type) in _FB_FILES.items():
        fpath = fb_folder / filename
        if not fpath.exists():
            counts[rel_type] = 0
            continue
        raw = json.loads(fpath.read_text(encoding="utf-8"))
        batch = [
            {"raw": e["name"], "relationship": rel_type, "ts": e["timestamp"]}
            for e in raw.get(key, [])
        ]
        entries.extend(batch)
        counts[rel_type] = len(batch)
    return entries, counts


def _build_fb_index(entries: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for e in entries:
        for key in _name_keys(e["raw"]):
            existing = index.get(key)
            if existing is None or _FB_WEIGHT.get(e["relationship"], 0) > _FB_WEIGHT.get(existing["relationship"], 0):
                index[key] = e
    return index


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _lookup_fb(norm: str, first: str, last: str, fb_index: dict) -> dict | None:
    if norm in fb_index:
        return fb_index[norm]
    fl_key = f"{first} {last}" if first and last else ""
    if fl_key and fl_key in fb_index:
        return fb_index[fl_key]
    if first and last:
        for entry in fb_index.values():
            ef, el = _first_last(entry["raw"])
            if ef == first and el == last:
                return entry
    return None


def _lookup_internal(norm: str, first: str, last: str, people: list[dict]) -> dict | None:
    for p in people:
        if _normalize(p["name"]) == norm:
            return p
        pf, pl = _first_last(p["name"])
        if first and last and pf == first and pl == last:
            return p
    return None


# ---------------------------------------------------------------------------
# Action hints
# ---------------------------------------------------------------------------

def _hints(fb: dict | None, li: dict | None, internal: dict | None) -> list[str]:
    hints = []
    rel = fb["relationship"] if fb else None
    if fb and li and internal:
        hints.append("priority: on all three platforms")
    elif rel == "friend" and li and internal:
        hints.append("priority: on all three platforms")
    elif rel == "friend" and li:
        hints.append("strong: confirmed FB friend + LinkedIn connection")
    elif rel == "friend" and internal:
        hints.append("close contact: FB friend in tracker — add to LinkedIn?")
    elif li and internal and not fb:
        hints.append("professional: LinkedIn + tracker, not FB friends")
    elif rel == "pending_sent" and li:
        hints.append("note: already on LinkedIn — FB request still pending")
    elif rel == "pending_received" and li:
        hints.append("note: they sent you a FB request — already connected on LinkedIn")
    elif rel == "removed" and li:
        hints.append("flag: unfriended on FB but still connected on LinkedIn")
    elif rel == "friend" and not li and not internal:
        hints.append("opportunity: FB friend not in professional network")
    elif li and not fb and not internal:
        hints.append("linkedin only — not tracked, not on FB")
    return hints


# ---------------------------------------------------------------------------
# Core crossref engine
# ---------------------------------------------------------------------------

def _run_crossref(fb_folder: Path) -> dict:
    """Execute the full crossref and return the report dict."""
    fb_entries, fb_counts = _load_fb_entries(fb_folder)
    fb_index = _build_fb_index(fb_entries)

    li_data = _load_json(_linkedin_file(), {"metadata": {}, "connections": []})
    li_list = li_data.get("connections", [])

    people_data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = people_data.get("people", [])

    registry: dict[str, dict] = {}

    # --- Seed from LinkedIn ---
    for conn in li_list:
        norm  = conn.get("full_name_normalized") or _normalize(conn.get("full_name", ""))
        first = _normalize(conn.get("first_name", ""))
        last  = _normalize(conn.get("last_name", ""))
        fb    = _lookup_fb(norm, first, last, fb_index)
        intl  = _lookup_internal(norm, first, last, people)

        entry = registry.setdefault(norm, {
            "canonical_name": conn["full_name"],
            "normalized": norm,
            "platforms": {},
        })
        entry["platforms"]["linkedin"] = {
            "url": conn.get("linkedin_url", ""),
            "company": conn.get("company", ""),
            "position": conn.get("position", ""),
            "connected_on": conn.get("connected_on", ""),
        }
        if fb:
            entry["platforms"]["facebook"] = {
                "relationship": fb["relationship"],
                "raw_name": fb["raw"],
                "ts": fb["ts"],
            }
            conn["facebook_match"] = {
                "matched": True,
                "relationship": fb["relationship"],
                "facebook_name": fb["raw"],
                "ts": fb["ts"],
            }
        else:
            conn["facebook_match"] = {"matched": False}
        if intl:
            entry["platforms"]["internal"] = {
                "id": intl.get("id"),
                "outreach_status": intl.get("outreach_status", ""),
                "tags": intl.get("tags", []),
                "company": intl.get("company", ""),
            }

    # --- Add FB-only contacts ---
    seen = set(registry.keys())
    for e in fb_entries:
        norm = _normalize(e["raw"])
        if any(k in seen for k in _name_keys(e["raw"])):
            continue
        first, last = _first_last(e["raw"])
        intl = _lookup_internal(norm, first, last, people)
        entry = registry.setdefault(norm, {
            "canonical_name": e["raw"],
            "normalized": norm,
            "platforms": {},
        })
        existing_fb = entry["platforms"].get("facebook")
        if not existing_fb or _FB_WEIGHT.get(e["relationship"], 0) > _FB_WEIGHT.get(existing_fb.get("relationship"), 0):
            entry["platforms"]["facebook"] = {
                "relationship": e["relationship"],
                "raw_name": e["raw"],
                "ts": e["ts"],
            }
        if intl and "internal" not in entry["platforms"]:
            entry["platforms"]["internal"] = {
                "id": intl.get("id"),
                "outreach_status": intl.get("outreach_status", ""),
                "tags": intl.get("tags", []),
                "company": intl.get("company", ""),
            }

    # --- Add internal-only contacts ---
    for p in people:
        norm = _normalize(p["name"])
        if norm not in registry:
            registry[norm] = {
                "canonical_name": p["name"],
                "normalized": norm,
                "platforms": {
                    "internal": {
                        "id": p.get("id"),
                        "outreach_status": p.get("outreach_status", ""),
                        "tags": p.get("tags", []),
                        "company": p.get("company", ""),
                    }
                },
            }

    # --- Finalize entries ---
    contacts = []
    for entry in registry.values():
        fb   = entry["platforms"].get("facebook")
        li   = entry["platforms"].get("linkedin")
        intl = entry["platforms"].get("internal")
        entry["platform_count"] = len(entry["platforms"])
        entry["signals"] = sorted(entry["platforms"].keys())
        entry["action_hints"] = _hints(fb, li, intl)
        contacts.append(entry)

    contacts.sort(key=lambda x: (-x["platform_count"], x["canonical_name"].lower()))

    # --- Insight buckets ---
    def _bucket(pred):
        return [
            {
                "name": c["canonical_name"],
                **{k: c["platforms"].get(k, {}) for k in c["signals"]},
                "action_hints": c["action_hints"],
            }
            for c in contacts if pred(c)
        ]

    def _fb_rel(c):
        return c["platforms"].get("facebook", {}).get("relationship")

    insights = {
        "all_three_platforms": _bucket(
            lambda c: set(c["signals"]) == {"facebook", "linkedin", "internal"}),
        "fb_friend_and_linkedin": _bucket(
            lambda c: _fb_rel(c) == "friend" and "linkedin" in c["platforms"] and "internal" not in c["platforms"]),
        "fb_friend_and_internal": _bucket(
            lambda c: _fb_rel(c) == "friend" and "internal" in c["platforms"] and "linkedin" not in c["platforms"]),
        "linkedin_and_internal_no_fb": _bucket(
            lambda c: "linkedin" in c["platforms"] and "internal" in c["platforms"] and "facebook" not in c["platforms"]),
        "fb_pending_sent_on_linkedin": _bucket(
            lambda c: _fb_rel(c) == "pending_sent" and "linkedin" in c["platforms"]),
        "fb_pending_received_on_linkedin": _bucket(
            lambda c: _fb_rel(c) == "pending_received" and "linkedin" in c["platforms"]),
        "fb_removed_still_on_linkedin": _bucket(
            lambda c: _fb_rel(c) == "removed" and "linkedin" in c["platforms"]),
        "linkedin_only": _bucket(
            lambda c: c["signals"] == ["linkedin"]),
        "fb_friend_only": _bucket(
            lambda c: c["signals"] == ["facebook"] and _fb_rel(c) == "friend"),
        "internal_only": _bucket(
            lambda c: c["signals"] == ["internal"]),
    }

    # Save updated LinkedIn file
    li_data["metadata"].update({
        "facebook_crossref_done": True,
        "facebook_crossref_date": _now(),
        "facebook_matches": sum(1 for c in li_list if c.get("facebook_match", {}).get("matched")),
    })
    _save_json(_linkedin_file(), li_data)

    report = {
        "metadata": {
            "generated": _now(),
            "fb_folder": str(fb_folder),
            "sources": {
                "facebook_friends":           fb_counts.get("friend", 0),
                "facebook_sent_requests":     fb_counts.get("pending_sent", 0),
                "facebook_received_requests": fb_counts.get("pending_received", 0),
                "facebook_removed":           fb_counts.get("removed", 0),
                "linkedin_connections":       len(li_list),
                "people_db":                  len(people),
            },
            "totals": {
                "unique_contacts": len(contacts),
                "multi_platform":  sum(1 for c in contacts if c["platform_count"] > 1),
            },
        },
        "insights": {k: {"count": len(v), "contacts": v} for k, v in insights.items()},
        "contacts": contacts,
    }
    _save_json(_crossref_file(), report)
    return report


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def run_contact_crossref(fb_folder: str = "") -> str:
    """
    Ingest a Facebook data export and cross-reference it against LinkedIn
    connections and the internal people tracker.

    Reads four Facebook files (friends, sent/received requests, removed) from
    the provided folder path, matches names against LinkedIn connections and
    people.json, and writes a full multi-platform contact registry to
    data/contact_crossref.json.

    Run this whenever you have a fresh Facebook or LinkedIn export.

    Args:
        fb_folder: Path to the Facebook export folder containing your_friends.json
                   and related files. If omitted, uses the fb_friends_folder value
                   from config.json.

    Returns:
        Summary of results: unique contacts indexed, multi-platform overlaps,
        and counts per insight bucket.
    """
    folder = Path(fb_folder) if fb_folder else config.FB_FRIENDS_FOLDER
    if not folder or not folder.exists():
        return (
            "✗ No Facebook export folder found. "
            "Pass fb_folder= explicitly or set fb_friends_folder in config.json."
        )

    report = _run_crossref(folder)
    meta = report["metadata"]
    src  = meta["sources"]
    tot  = meta["totals"]
    ins  = report["insights"]

    lines = [
        f"✓ Contact crossref complete — {meta['generated']}",
        "",
        "Sources ingested:",
        f"  Facebook friends:       {src['facebook_friends']}",
        f"  FB sent requests:       {src['facebook_sent_requests']}",
        f"  FB received requests:   {src['facebook_received_requests']}",
        f"  FB removed:             {src['facebook_removed']}",
        f"  LinkedIn connections:   {src['linkedin_connections']}",
        f"  Internal people db:     {src['people_db']}",
        "",
        f"Unique contacts indexed: {tot['unique_contacts']}",
        f"On multiple platforms:   {tot['multi_platform']}",
        "",
        "Insight buckets:",
    ]
    for key, bucket in ins.items():
        n = bucket["count"]
        if n:
            lines.append(f"  {key.replace('_', ' '):45s} {n}")

    lines += [
        "",
        f"Saved: contact_crossref.json",
        f"Updated: linkedin_connections.json (facebook_match per connection)",
    ]
    return "\n".join(lines)


def get_contact_crossref(insight: str = "", name: str = "") -> str:
    """
    Query the cross-platform contact registry.

    Use after run_contact_crossref has been called at least once.

    Args:
        insight: Return contacts from a specific insight bucket. One of:
                   all_three_platforms, fb_friend_and_linkedin,
                   fb_friend_and_internal, linkedin_and_internal_no_fb,
                   fb_pending_sent_on_linkedin, fb_pending_received_on_linkedin,
                   fb_removed_still_on_linkedin, linkedin_only,
                   fb_friend_only, internal_only.
                 Omit to return the full summary.
        name:    Look up a specific person by name (partial match).
                 If provided, insight is ignored.

    Returns:
        Formatted contact data with platform presence and action hints.
    """
    data = _load_json(_crossref_file(), None)
    if data is None:
        return "✗ No crossref data found. Run run_contact_crossref first."

    meta = data["metadata"]
    tot  = meta["totals"]

    # --- Name lookup ---
    if name:
        needle = _normalize(name)
        matches = [
            c for c in data["contacts"]
            if needle in c["normalized"] or needle in _normalize(c["canonical_name"])
        ]
        if not matches:
            return f"No contacts found matching '{name}'."
        lines = [f"Contacts matching '{name}':"]
        for c in matches:
            lines.append(f"\n  {c['canonical_name']}  ({', '.join(c['signals'])})")
            for platform, pdata in c["platforms"].items():
                if platform == "facebook":
                    lines.append(f"    Facebook: {pdata.get('relationship')} — {pdata.get('raw_name', '')}")
                elif platform == "linkedin":
                    lines.append(f"    LinkedIn: {pdata.get('company', '')} / {pdata.get('position', '')}")
                elif platform == "internal":
                    lines.append(f"    Tracker:  status={pdata.get('outreach_status', '')}  tags={pdata.get('tags', [])}")
            if c.get("action_hints"):
                lines.append(f"    → {'; '.join(c['action_hints'])}")
        return "\n".join(lines)

    # --- Insight bucket ---
    if insight:
        bucket = data["insights"].get(insight)
        if bucket is None:
            available = ", ".join(data["insights"].keys())
            return f"✗ Unknown insight '{insight}'. Available: {available}"
        contacts = bucket["contacts"]
        if not contacts:
            return f"No contacts in '{insight}' bucket."
        lines = [f"{insight.replace('_', ' ')} ({bucket['count']} contacts):", ""]
        for c in contacts:
            platforms = ", ".join(k for k in ("facebook", "linkedin", "internal") if k in c)
            hints = "; ".join(c.get("action_hints", []))
            fb_rel = c.get("facebook", {}).get("relationship", "")
            li_co  = c.get("linkedin", {}).get("company", "")
            detail = " | ".join(filter(None, [fb_rel, li_co]))
            lines.append(f"  {c['name']}" + (f"  [{detail}]" if detail else ""))
            if hints:
                lines.append(f"    → {hints}")
        return "\n".join(lines)

    # --- Full summary ---
    lines = [
        f"Contact crossref — generated {meta['generated']}",
        f"Unique contacts: {tot['unique_contacts']}  |  Multi-platform: {tot['multi_platform']}",
        "",
        "Insight buckets:",
    ]
    for key, bucket in data["insights"].items():
        n = bucket["count"]
        lines.append(f"  {key.replace('_', ' '):45s} {n}")
    lines.append("")
    lines.append("Use insight= to drill into a bucket, or name= to look up a person.")
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(run_contact_crossref)
    mcp.tool()(get_contact_crossref)
