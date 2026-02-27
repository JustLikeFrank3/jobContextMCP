"""
HBDI (Herrmann Whole Brain Model) cognitive style profiler.

Two tools:
  run_hbdi_assessment()  — guided 4-question assessment; scores responses into
                           A/B/C/D quadrant profile; logs to personal_context.json;
                           returns synthesis + interview framing advice.
  get_hbdi_profile()     — returns the stored profile, or prompts to run assessment.
"""

from lib import config
from lib.io import _load_json, _save_json, _now

# ── Quadrant metadata ─────────────────────────────────────────────────────────

_QUADRANTS = {
    "A": "Analytical / Logical",
    "B": "Organized / Sequential",
    "C": "Interpersonal / Feeling",
    "D": "Imaginative / Holistic",
}

_SCORE_LABELS = {
    4: "Primary",
    3: "Strong secondary",
    2: "Present (not dominant)",
    1: "Weak",
}

# ── Interview framing advice by dominant quadrant ─────────────────────────────

_FRAMING_ADVICE = {
    "D": [
        "You lead with vision and synthesis — you see the shape of a solution before anyone has named it.",
        "For A-dominant interviewers (metrics-first): consciously flip your opening. Lead data → then vision, not vision → then data.",
        "On 'tell me about yourself': anchor the narrative in a concrete outcome first, then explain the insight that drove it.",
        "On innovation/design questions: this is your home court. Let the D run.",
        "On 'weakness' questions: name the B gap honestly (process, sequencing) and show your tooling strategy — 'I weaponize AI for the B work.'",
        "Under pressure (whiteboard, panel): you run internal analysis before speaking. This reads as calm confidence — it is an asset, not a tell.",
    ],
    "A": [
        "You lead with data, logic, and precision — this lands well with technical interviewers and metrics-driven orgs.",
        "For C-dominant interviewers (relationship-first): open with the human impact before the numbers.",
        "On system design: walk through trade-offs explicitly — you naturally do this, so let it show.",
        "On 'tell me about a time you failed': give the data on what went wrong before the lesson — it signals intellectual honesty.",
        "On 'weakness' questions: the risk is appearing cold or over-optimizing. Counter with a story where stake-holder empathy changed the outcome.",
    ],
    "C": [
        "You lead with relationships, team dynamics, and human outcomes.",
        "For A-dominant interviewers: anchor every story in a before/after metric, even if the metric was secondarily important to you.",
        "On cross-functional and collaboration questions: this is your strongest signal — use it fully.",
        "On conflict questions: your tendency to preserve relationship capital while holding conviction quietly is a premium answer — articulate it explicitly.",
        "On 'tell me about yourself': structure the narrative around people who shaped key outcomes, not just individual technical wins.",
    ],
    "B": [
        "You lead with structure, process, and reliability — strong fit for ops, infra, and regulated environments.",
        "For D-dominant interviewers: open with the problem and why the existing process was failing before describing your solution.",
        "On 'walk me through your process' questions: this is home court — be specific, not generic.",
        "On innovation questions: frame your process improvements as unlocking speed or scale, not just compliance.",
        "On 'strength/weakness': name the D gap (you may under-sell big-picture vision) and show a story where stepping back to see the whole system changed the outcome.",
    ],
}

_SECONDARY_ADVICE = {
    "A": "Back vision claims with data. Build the alternative implementation — not to win, to know.",
    "B": "Capable of thorough finish work. Use tools to compensate for the intrinsic B gap — document output is real even if B-motivation isn't.",
    "C": "Deploy empathy analytically: understand the other person's frame before reacting. Relationship capital is a strategic asset.",
    "D": "Hold the long view even when deferring short-term. The conviction doesn't die — it parks.",
}


def _rank_quadrants(scores: dict[str, int]) -> list[tuple[str, int]]:
    """Return quadrants sorted descending by score."""
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _build_profile_report(
    scores: dict[str, int],
    q1: str,
    q2: str,
    q3: str,
    q4: str,
    notes: str,
) -> str:
    ranked = _rank_quadrants(scores)
    primary_q = ranked[0][0]
    lines = ["═══ HBDI COGNITIVE PROFILE ═══", ""]

    # ── Scores ────────────────────────────────────────────────────────────────
    lines.append("── Quadrant Scores ──")
    for q, score in ranked:
        label = _SCORE_LABELS.get(score, "Unknown")
        lines.append(f"  {q} ({_QUADRANTS[q]}): {score}/4 — {label}")
    lines.append("")

    # ── Q&A answers ───────────────────────────────────────────────────────────
    _QUESTIONS = {
        "Q1": ("No-spec project — first hour approach", q1),
        "Q2": ("Critical feedback on proud work", q2),
        "Q3": ("Six-week project — tedious finish phase", q3),
        "Q4": ("Disagree with senior engineer — what you actually do", q4),
    }
    lines.append("── Assessment Responses ──")
    for label, (prompt, answer) in _QUESTIONS.items():
        lines.append(f"  {label}: {prompt}")
        lines.append(f"  → {answer.strip()}")
        lines.append("")

    if notes:
        lines.append(f"Notes: {notes}")
        lines.append("")

    # ── Synthesis ─────────────────────────────────────────────────────────────
    lines.append("── Synthesis ──")
    lines.append(f"  Primary quadrant: {primary_q} ({_QUADRANTS[primary_q]})")

    secondaries = [(q, s) for q, s in ranked[1:] if s >= 3]
    if secondaries:
        sec_str = ", ".join(f"{q} ({_QUADRANTS[q]})" for q, _ in secondaries)
        lines.append(f"  Strong secondaries: {sec_str}")

    weaponized = [(q, s) for q, s in ranked if s == 2]
    if weaponized:
        wpn_str = ", ".join(f"{q}" for q, _ in weaponized)
        lines.append(f"  Present but not dominant (weaponize via tools/strategy): {wpn_str}")

    lines.append("")

    # ── Secondary advice ──────────────────────────────────────────────────────
    if secondaries:
        lines.append("── Secondary Quadrant Patterns ──")
        for q, _ in secondaries:
            lines.append(f"  {q}: {_SECONDARY_ADVICE[q]}")
        lines.append("")

    # ── Interview framing advice ───────────────────────────────────────────────
    lines.append(f"── Interview Framing Advice (Primary: {primary_q}) ──")
    for tip in _FRAMING_ADVICE.get(primary_q, []):
        lines.append(f"  • {tip}")
    lines.append("")

    # ── Key interview answers from responses ──────────────────────────────────
    lines.append("── Signature Answers (derived from your responses) ──")
    lines.append("  On disagreement: use your Q4 answer verbatim — it shows collaboration,")
    lines.append("    conviction, and empirical mindset in one sentence.")
    lines.append("  On weakness: be specific about your lowest quadrant and name your")
    lines.append("    concrete tooling/strategy that compensates — not a generic 'I'm a perfectionist.'")
    lines.append("  On 'how do you handle being wrong': use your Q2 answer — no self-loathing,")
    lines.append("    no theater. Clean.")

    return "\n".join(lines)


# ── Public tools ──────────────────────────────────────────────────────────────

def run_hbdi_assessment(
    q1_no_spec_project: str,
    q2_critical_feedback: str,
    q3_tedious_finish: str,
    q4_senior_disagreement: str,
    score_a: int,
    score_b: int,
    score_c: int,
    score_d: int,
    notes: str = "",
) -> str:
    """
    Run an HBDI (Herrmann Whole Brain Model) cognitive style assessment and log the
    resulting profile to personal context.

    Answer the four guided questions honestly, then score each quadrant 1–4:
      A (Analytical/Logical)     — logic, data, metrics, precision
      B (Organized/Sequential)   — process, structure, planning, follow-through
      C (Interpersonal/Feeling)  — relationships, empathy, team dynamics
      D (Imaginative/Holistic)   — vision, synthesis, big-picture thinking

    Scores: 1 = weak   2 = present (not dominant)   3 = strong secondary   4 = primary

    The four guided questions:
      q1_no_spec_project      — How do you approach a project with no spec in the first hour?
      q2_critical_feedback    — You receive critical feedback on work you were proud of. What do you actually do?
      q3_tedious_finish       — Six weeks in, exciting work done, now the tedious finish phase. How do you handle it?
      q4_senior_disagreement  — You disagree with a senior engineer on the right approach. What do you actually do?

    Results are saved to personal_context.json and returned as a full profile report
    with interview framing advice calibrated to your dominant quadrant.
    """
    for name, val in [("score_a", score_a), ("score_b", score_b), ("score_c", score_c), ("score_d", score_d)]:
        if not isinstance(val, int) or val < 1 or val > 4:
            return f"✗ {name} must be an integer between 1 and 4 (got {val!r})."

    scores = {"A": score_a, "B": score_b, "C": score_c, "D": score_d}
    ranked = _rank_quadrants(scores)
    primary_q = ranked[0][0]

    profile = {
        "assessed_at": _now(),
        "scores": scores,
        "primary": primary_q,
        "responses": {
            "q1_no_spec_project": q1_no_spec_project,
            "q2_critical_feedback": q2_critical_feedback,
            "q3_tedious_finish": q3_tedious_finish,
            "q4_senior_disagreement": q4_senior_disagreement,
        },
        "notes": notes,
    }

    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    data["hbdi_profile"] = profile
    _save_json(config.PERSONAL_CONTEXT_FILE, data)

    report = _build_profile_report(
        scores,
        q1=q1_no_spec_project,
        q2=q2_critical_feedback,
        q3=q3_tedious_finish,
        q4=q4_senior_disagreement,
        notes=notes,
    )
    return report + f"\n✓ Profile saved to personal context ({_now()})."


def get_hbdi_profile() -> str:
    """
    Return the stored HBDI cognitive profile. If no assessment has been run yet,
    prompts you to call run_hbdi_assessment() with the four guided questions and your
    A/B/C/D scores (1–4).
    """
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    profile = data.get("hbdi_profile")

    if not profile:
        return (
            "No HBDI profile found. Run run_hbdi_assessment() with:\n"
            "  q1_no_spec_project, q2_critical_feedback, q3_tedious_finish, q4_senior_disagreement\n"
            "  score_a, score_b, score_c, score_d  (each 1–4)\n\n"
            "Scores: 1=weak  2=present  3=strong secondary  4=primary\n"
            "Quadrants: A=Analytical  B=Organized  C=Interpersonal  D=Imaginative"
        )

    scores = profile.get("scores", {})
    responses = profile.get("responses", {})

    return _build_profile_report(
        scores,
        q1=responses.get("q1_no_spec_project", ""),
        q2=responses.get("q2_critical_feedback", ""),
        q3=responses.get("q3_tedious_finish", ""),
        q4=responses.get("q4_senior_disagreement", ""),
        notes=profile.get("notes", ""),
    ) + f"\n(Assessed: {profile.get('assessed_at', 'unknown')})"


def register(mcp) -> None:
    mcp.tool()(run_hbdi_assessment)
    mcp.tool()(get_hbdi_profile)
