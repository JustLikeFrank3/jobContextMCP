"""
Beta tester tracking — v6

Tracks who signed up for the jobContextMCP beta, their setup experience,
bugs reported, and feedback. Used to recruit and manage v6 testers.

Tools:
  log_beta_tester    — register a new beta tester
  update_beta_tester — add a bug report, feedback note, or update status
  get_beta_testers   — retrieve tester list with optional filtering
"""

import datetime
from lib import config
from lib.io import _load_json, _save_json, _now


_VALID_STATUSES = ["active", "setup_failed", "completed", "dropped", "pending"]
_VALID_SOURCES = ["linkedin", "reddit", "discord", "twitter", "direct", "other"]


def _next_id(testers: list[dict]) -> int:
    if not testers:
        return 1
    return max(t.get("id", 0) for t in testers) + 1


def log_beta_tester(
    name: str,
    contact: str = "",
    source: str = "linkedin",
    os: str = "",
    ai_client: str = "",
    notes: str = "",
    signed_up: str = "",
) -> str:
    """
    Register a new beta tester for jobContextMCP v6.

    Records where they came from, their environment, and any initial notes.
    Used to track who to follow up with and whether they completed setup.

    Args:
        name:       Tester's name or handle.
        contact:    Email, LinkedIn URL, Reddit username, Discord handle, etc.
        source:     Where they signed up: 'linkedin', 'reddit', 'discord',
                    'twitter', 'direct', 'other'.
        os:         Their OS (e.g. 'macOS', 'Windows', 'Linux').
        ai_client:  MCP client they plan to use (e.g. 'GitHub Copilot',
                    'Claude Desktop', 'Cursor').
        notes:      Any initial context worth tracking.
        signed_up:  ISO date (YYYY-MM-DD). Defaults to today.

    Returns:
        Confirmation string with tester ID.
    """
    data = _load_json(config.BETA_TESTERS_FILE, {"testers": []})
    testers: list = data.setdefault("testers", [])

    entry = {
        "id": _next_id(testers),
        "name": name.strip(),
        "contact": contact.strip(),
        "source": source.strip().lower(),
        "signed_up": signed_up.strip() or datetime.date.today().isoformat(),
        "status": "active",
        "os": os.strip(),
        "ai_client": ai_client.strip(),
        "setup_completed": False,
        "hbdi_completed": False,
        "bugs": [],
        "feedback": [],
        "notes": notes.strip(),
        "last_updated": _now(),
    }
    testers.append(entry)
    _save_json(config.BETA_TESTERS_FILE, data)

    return (
        f"✓ Beta tester logged: {entry['name']} (id: {entry['id']}, "
        f"source: {entry['source']}, contact: {entry['contact'] or 'none'})"
    )


def update_beta_tester(
    tester_id: int,
    status: str = "",
    setup_completed: bool | None = None,
    hbdi_completed: bool | None = None,
    bug: str = "",
    feedback: str = "",
    notes: str = "",
) -> str:
    """
    Update a beta tester's record with new status, a bug report, or feedback.

    Args:
        tester_id:        ID of the tester to update.
        status:           New status: 'active', 'setup_failed', 'completed',
                          'dropped', 'pending'.
        setup_completed:  Mark whether they successfully completed setup_workspace().
        hbdi_completed:   Mark whether they ran run_hbdi_assessment().
        bug:              A bug report string to append to their bug list.
        feedback:         A feedback note to append.
        notes:            Overwrite the general notes field.

    Returns:
        Confirmation string.
    """
    data = _load_json(config.BETA_TESTERS_FILE, {"testers": []})
    testers: list = data.get("testers", [])

    match = next((t for t in testers if t.get("id") == tester_id), None)
    if not match:
        return f"✗ No beta tester found with id {tester_id}."

    if status:
        if status not in _VALID_STATUSES:
            return f"✗ Invalid status '{status}'. Valid: {', '.join(_VALID_STATUSES)}"
        match["status"] = status
    if setup_completed is not None:
        match["setup_completed"] = setup_completed
    if hbdi_completed is not None:
        match["hbdi_completed"] = hbdi_completed
    if bug:
        match.setdefault("bugs", []).append({
            "text": bug.strip(),
            "logged_at": _now(),
        })
    if feedback:
        match.setdefault("feedback", []).append({
            "text": feedback.strip(),
            "logged_at": _now(),
        })
    if notes:
        match["notes"] = notes.strip()
    match["last_updated"] = _now()

    _save_json(config.BETA_TESTERS_FILE, data)
    return f"✓ Beta tester #{tester_id} ({match['name']}) updated."


def get_beta_testers(
    status: str = "",
    source: str = "",
    include_bugs: bool = True,
    include_feedback: bool = True,
) -> str:
    """
    Retrieve beta testers with optional filtering and a summary.

    Args:
        status:           Filter by status ('active', 'completed', etc.).
        source:           Filter by signup source ('linkedin', 'reddit', etc.).
        include_bugs:     Include bug reports in output.
        include_feedback: Include feedback notes in output.

    Returns:
        Formatted tester list with summary stats.
    """
    data = _load_json(config.BETA_TESTERS_FILE, {"testers": []})
    testers: list = data.get("testers", [])

    if not testers:
        return "No beta testers logged yet."

    filtered = testers
    if status:
        filtered = [t for t in filtered if t.get("status", "") == status.lower()]
    if source:
        filtered = [t for t in filtered if t.get("source", "") == source.lower()]

    if not filtered:
        return "No beta testers match the specified filters."

    # Summary counts
    total = len(testers)
    active = sum(1 for t in testers if t.get("status") == "active")
    completed = sum(1 for t in testers if t.get("status") == "completed")
    setup_done = sum(1 for t in testers if t.get("setup_completed"))
    hbdi_done = sum(1 for t in testers if t.get("hbdi_completed"))
    bugs_total = sum(len(t.get("bugs", [])) for t in testers)

    lines = [
        f"═══ BETA TESTERS ({len(filtered)} shown / {total} total) ═══",
        f"Active: {active}  |  Completed: {completed}  |  Setup done: {setup_done}/{total}  |  HBDI done: {hbdi_done}/{total}  |  Bugs logged: {bugs_total}",
        "",
    ]

    by_source: dict = {}
    for t in testers:
        s = t.get("source", "other")
        by_source[s] = by_source.get(s, 0) + 1
    if by_source:
        src_str = "  ".join(f"{s}={n}" for s, n in sorted(by_source.items(), key=lambda x: -x[1]))
        lines.append(f"By source: {src_str}")
        lines.append("")

    for t in sorted(filtered, key=lambda x: x.get("signed_up", ""), reverse=True):
        setup_flag = "✓ setup" if t.get("setup_completed") else "✗ setup"
        hbdi_flag = "✓ HBDI" if t.get("hbdi_completed") else "✗ HBDI"
        lines.append(f"■ #{t['id']} {t['name']}  [{t.get('status', '?')}]  {setup_flag}  {hbdi_flag}")
        lines.append(f"  Source:  {t.get('source', '—')}  |  Signed up: {t.get('signed_up', '—')}")
        if t.get("contact"):
            lines.append(f"  Contact: {t['contact']}")
        if t.get("os") or t.get("ai_client"):
            env = "  ".join(filter(None, [t.get("os"), t.get("ai_client")]))
            lines.append(f"  Env:     {env}")
        if t.get("notes"):
            lines.append(f"  Notes:   {t['notes']}")
        if include_bugs and t.get("bugs"):
            lines.append(f"  Bugs ({len(t['bugs'])}):")
            for b in t["bugs"]:
                lines.append(f"    • {b['text']}  [{b.get('logged_at', '')}]")
        if include_feedback and t.get("feedback"):
            lines.append(f"  Feedback ({len(t['feedback'])}):")
            for f in t["feedback"]:
                lines.append(f"    • {f['text']}  [{f.get('logged_at', '')}]")
        lines.append("")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(log_beta_tester)
    mcp.tool()(update_beta_tester)
    mcp.tool()(get_beta_testers)
