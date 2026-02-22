"""
Session startup tool — v1

get_session_context()
    Returns master resume + tone profile + personal context + job hunt status
    in a single call. MUST be the first tool called in every session.
    No exceptions. This is the entire point of the system.
"""

from lib.io import _load_master_context
from tools.tone import get_tone_profile
from tools.context import get_personal_context
from tools.job_hunt import get_job_hunt_status


def get_session_context() -> str:
    """
    SESSION STARTUP — call this first, before anything else, every single session.

    Returns Frank's complete context in one shot:
      1. Master resume with all metrics, projects, and personal notes
      2. Tone profile — Frank's voice. Do not write a single word for him without this.
      3. Personal stories and context — family, identity, motivation
      4. Live job hunt pipeline — current applications and next steps

    This exists so Frank never has to recontextualize. Honor that.
    """
    sections = [
        "═" * 60,
        "SESSION CONTEXT — Frank Vladmir MacBride III",
        "═" * 60,
        "",
        "── 1. MASTER RESUME ──────────────────────────────────────",
        "",
        _load_master_context(),
        "",
        "── 2. TONE PROFILE ───────────────────────────────────────",
        "",
        get_tone_profile(),
        "",
        "── 3. PERSONAL CONTEXT ───────────────────────────────────",
        "",
        get_personal_context(),
        "",
        "── 4. JOB HUNT STATUS ────────────────────────────────────",
        "",
        get_job_hunt_status(),
        "",
        "═" * 60,
        "You are now fully contextualized. Proceed.",
        "═" * 60,
    ]
    return "\n".join(sections)


def register(mcp) -> None:
    mcp.tool()(get_session_context)
