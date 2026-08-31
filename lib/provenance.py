"""Deterministic provenance checking for generated documents.

The problem: the generation pipeline's LLM reviewer checks *quality*, but
nothing checks *truth* — a drafted resume can carry a metric ("cut latency
34%") that appears nowhere in the source material, and the reviewer will
happily approve it. This module is tier 1 of the validation ladder: cheap,
deterministic, no LLM.

Approach: fabricated specifics are the hallucination surface that matters
in application materials — percentages, dollar amounts, magnitudes,
multipliers, years. Those are extractable with regexes, and the check is
global set membership: every numeric claim in the draft must appear
somewhere in the run's source material (master resume, retrieved chunks,
STAR stories, and the job description). No sentence-to-chunk attribution
needed; that's tier 2's job (NLI entailment) if it ever earns its cost.

Known trade-off, documented on purpose: including the JD as a source means
a draft could parrot a JD metric as its own achievement and pass tier 1.
Excluding it would false-positive on every legitimate JD echo ("your team
of 12"). Tier 1 optimizes for zero false positives so the gate can hard-
block; the general parroting case is what the (future) entailment tier is
for. ONE claim shape is carved out of that policy: years-of-experience
claims ("5+ years of X") check against master-side sources only — human
triage (2026-08) showed the JD echo IS the failure there, and a years
requirement appears in essentially every JD, so the carve-out costs no
legitimate echoes. See check_years_claims.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from lib.metrics import inc

# Numeric-claim patterns, in priority order. Each match is normalized before
# comparison so "1,200" == "1200" and "$1.2M" == "$1.2m".
_CLAIM_PATTERNS = [
    r"\$\s?\d[\d,.]*\s?(?:[kmb]illion|[kmb])?\b",   # $1.2M, $500k, $1,200
    # No \b after '%': word boundaries need a word char on one side, and
    # '%' followed by space/punctuation has none — '34%' would never match.
    r"\b\d[\d,.]*\s?(?:%|percent\b)",               # 34%, 34 percent
    r"\b\d[\d,.]*\s?(?:[kmb])\b",                   # 15k, 2.5M (magnitude suffix)
    r"\b\d+(?:\.\d+)?x\b",                          # 3x, 2.5x multipliers
    r"\b\d{1,3}(?:,\d{3})+\b",                      # 10,000 (comma-grouped)
    r"\b(?:19|20)\d{2}\b",                          # years (fabricated dates ARE claims)
    # Bare counts: "85 actions", "1481 tests", "11 domains". Until 2026-08-10
    # nothing here matched an unadorned integer, so the single most common
    # fabrication in a resume — an invented tool or test count — was never
    # extracted and therefore never checked. Measured on the golden corpus:
    # "931 passing tests" and "277 tests" sailed through a gate reporting the
    # documents clean while the LLM judge named both against the master.
    #
    # Two guards make it safe, and both are load-bearing:
    #   lookahead  — whitespace then a letter, so the integer is counting
    #                something. Without it every resume's contact header
    #                contributed three violations of pure noise.
    #   lookbehind — not preceded by a digit separator, so a trailing phone
    #                group can't qualify just because prose follows it
    #                ("call 305-490-1262 today" would otherwise yield 1262),
    #                and no fragment of an already-matched grouped number
    #                ("1,200 total" -> 200) can re-match.
    r"(?<![-.,\d])\b\d{2,}(?=\s+[A-Za-z])",         # 85 actions, 1481 tests
]
_CLAIM_RE = re.compile("|".join(f"(?:{p})" for p in _CLAIM_PATTERNS), re.IGNORECASE)


def _normalize(text: str) -> str:
    """Canonical form for comparison: lowercase, commas stripped from
    numbers, '34 percent'/'34 %' collapsed to '34%'.

    Deliberately does NOT strip spaces globally — spaces are the word
    boundaries _contains_claim relies on; removing them glues prose onto
    numbers ('34% at' -> '34%at') and breaks boundary checks.
    """
    t = (text or "").lower().replace(",", "")
    t = re.sub(r"(?<=\d)\s*percent\b", "%", t)
    t = re.sub(r"(?<=\d)\s+%", "%", t)
    return t


def extract_claims(text: str) -> list[str]:
    """Return the distinct numeric claims found in *text*, original spelling."""
    seen: dict[str, str] = {}
    for m in _CLAIM_RE.finditer(text or ""):
        token = m.group(0).strip()
        key = _normalize(token)
        if key and key not in seen:
            seen[key] = token
    return list(seen.values())


def _contains_claim(corpus: str, needle: str) -> bool:
    """Boundary-aware containment: is *needle* present as its own number?

    Plain substring is wrong here — '2m' lurks inside '$1.2m' and '34%'
    inside '134%', which would let fabricated claims pass as sourced.
    An occurrence only counts when the character before it is not a digit
    or '.' (so it isn't the tail of a larger number) and the character
    after is not a digit or letter (so it isn't the head of one). '$' is
    an allowed predecessor: source '$500k' legitimately backs a draft's
    bare '500k'.
    """
    start = 0
    while True:
        idx = corpus.find(needle, start)
        if idx == -1:
            return False
        before = corpus[idx - 1] if idx > 0 else ""
        after = corpus[idx + len(needle)] if idx + len(needle) < len(corpus) else ""
        if before not in "0123456789." and not (after.isdigit() or after.isalpha()):
            return True
        start = idx + 1


# ── Years-of-experience claims (Round 2, 2026-08) ───────────────────────────
# "5+ years of agentic AI engineering" was the single surviving fabrication
# class after the master-only-evidence baseline, and human triage confirmed
# the mechanism: the number is mirrored from the JD's *requirement* back as
# the candidate's *experience*. The gate's JD-as-source policy (module
# docstring) is deliberate for every other claim shape — "your team of 12"
# must not false-positive — but for experience durations the JD echo IS the
# failure, so these claims get their own check against master-side sources
# only. Single-digit "N+ years" never matched the numeric patterns above
# (no %, no suffix, under two digits), so this class was entirely ungated.
_YEARS_CLAIM_RE = re.compile(
    r"\b(?:(?:over|more than|at least|under|less than|fewer than)\s+)?"
    r"\d{1,2}(?:\.\d)?\s*\+?\s*years?\b",
    re.IGNORECASE,
)


def _normalize_years(token: str) -> str:
    """Canonical form: '5+years' ≥-flavored, 'under5years' <-flavored, '5years' exact.

    'over 5 years', 'more than 5 years', 'at least 5 years', '5+ years', and
    '5 + years' all claim the same thing; '5 years' claims something stricter
    and is NOT backed by a source saying '5+ years' (nor vice versa — rule 1
    is verbatim, and '5 years'→'5+ years' is precisely the inflation move).

    Under-flavored claims ('under 5 years', 'less than 5 years', 'fewer
    than 5 years') are their own class, distinct from BOTH others: the
    08-31 nightly shipped an invented 'less than 5 years tenure' because
    the old regex saw only the bare '5 years', which an unrelated exact
    '5 years' elsewhere in the master cross-context-backed. An
    under-claim is only backed by an under-claim of the same number.
    """
    t = token.lower().strip()
    if t.startswith(("under", "less than", "fewer than")):
        n = re.search(r"\d{1,2}(?:\.\d)?", t).group(0)
        return f"under{n}years"
    plus = "+" in t or t.startswith(("over", "more than", "at least"))
    n = re.search(r"\d{1,2}(?:\.\d)?", t).group(0)
    return f"{n}+years" if plus else f"{n}years"


def extract_years_claims(text: str) -> list[str]:
    """Distinct years-of-experience claims in *text*, original spelling."""
    seen: dict[str, str] = {}
    for m in _YEARS_CLAIM_RE.finditer(text or ""):
        token = m.group(0).strip()
        key = _normalize_years(token)
        if key not in seen:
            seen[key] = token
    return list(seen.values())


def check_years_claims(draft: str, master_sources: list[str]) -> list[str]:
    """Years-of-experience claims in *draft* not backed by master-side text.

    master_sources is the first-party material only — master resume bundle,
    STAR stories — NEVER the job description. Matching the JD is what this
    check exists to catch.
    """
    allowed = {
        _normalize_years(t)
        for s in master_sources
        for t in extract_years_claims(s or "")
    }
    return [
        t for t in extract_years_claims(draft)
        if _normalize_years(t) not in allowed
    ]


# ── Contact-handle claims (Round 3, 2026-08) ────────────────────────────────
# The LinkedIn-handle mutation (frankvmacbride → frankmacbride) survived every
# prompt-rule round: it recurred 3× in the 2026-08-19 run after vanishing for
# a week. A drifted handle is worse than a fabricated metric — it sends a
# recruiter to a stranger's profile — and it is perfectly mechanical to check:
# any profile handle in the draft must appear verbatim in master-side text.
# Email/phone are deliberately NOT pattern-checked here: their regexes
# false-positive on prose, and the numeric patterns above already cover phone
# digit groups. Handles are the class with an observed failure.
_CONTACT_HANDLE_RES = (
    re.compile(r"linkedin\.com/in/([A-Za-z0-9._-]+)", re.IGNORECASE),
    re.compile(r"github\.com/([A-Za-z0-9._-]+)", re.IGNORECASE),
)


def check_contact_claims(draft: str, master_sources: list[str]) -> list[str]:
    """Profile handles in *draft* that don't match master-side text verbatim."""
    master_text = "\n".join(s for s in master_sources if s)
    violations: list[str] = []
    for pattern in _CONTACT_HANDLE_RES:
        allowed = {m.group(1).lower() for m in pattern.finditer(master_text)}
        for m in pattern.finditer(draft or ""):
            if m.group(1).lower() not in allowed:
                violations.append(m.group(0))
    return violations


# ── Held-title claims (Round 4, 2026-08) ────────────────────────────────────
# Title-ification survived two consecutive nightly runs after the prompt rule
# shipped: job headers and the headline tagline wearing titles the candidate
# never held ("Australian Team Support Lead", "AI Evangelist", a JD's
# "SENIOR DIGITAL EXPERIENCE AI DEVELOPER" as the tagline, an invented "Peer
# Mentor" role). A wrong held title is an identity claim — worse than a
# wrong metric, and perfectly mechanical to check because the .txt format
# spec pins where titles live:
#   job header  : `Title | Company, Location | Month YYYY - Month YYYY`
#   tagline     : `ROLE TITLE | Tech • Stack • Here`
# Project headers (`Name | Tech Stack | Year`) and education (`Degree |
# School | YYYY`) share the pipe shape but end in a BARE year — no month
# name, no "Present" — which is the discriminator: project and degree names
# are legitimately not "held titles" and stay ungated. LEADERSHIP's
# `Role/label: description` lines are deliberately out of scope for now:
# their labels are fuzzy ("Mentor:", "Speaker:") and gating them on verbatim
# master containment would false-positive on honest paraphrase; the two
# shapes gated here are the ones with observed failures.
_TITLE_DATE_RANGE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\bpresent\b|\bcurrent\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d\d\b")


def _normalize_title(text: str) -> str:
    """Canonical form for title comparison: lowercase, every punctuation/
    whitespace run collapsed to a single space. 'Sr. Software Engineer' and
    'sr software engineer' compare equal; word boundaries survive as spaces."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# LEADERSHIP & COMMUNITY's `Role/label: description` lines joined the gate
# on 2026-08-31: v1 scoped them out (fuzzy-label worry), and the invented-
# evangelist class promptly recurred twice in one nightly ("AI Evangelist",
# "AI Tooling Evangelist" — presented as named roles parallel to real ones).
# Scoped strictly to the LEADERSHIP section so skills lines (`Label: value`
# under CORE TECHNICAL SKILLS) and prose colons stay ungated.
_LEADERSHIP_HEADER_RE = re.compile(r"^\s*LEADERSHIP\b[A-Z &]*\s*$")
_ALLCAPS_SECTION_RE = re.compile(r"^\s*[A-Z][A-Z &]{2,}\s*$")
_LEADER_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 .&'/-]{1,60}):\s+\S")


def extract_title_claims(draft: str) -> list[str]:
    """Titles the draft presents as HELD: job-header first segments, every
    headline-tagline title, and LEADERSHIP role labels. Original spelling,
    deduped on normalized form."""
    seen: dict[str, str] = {}

    def _add(title: str) -> None:
        key = _normalize_title(title)
        if key and key not in seen:
            seen[key] = title

    in_leadership = False
    for line in (draft or "").splitlines():
        if _LEADERSHIP_HEADER_RE.match(line):
            in_leadership = True
            continue
        if in_leadership and _ALLCAPS_SECTION_RE.match(line):
            in_leadership = False
        if in_leadership and "|" not in line:
            m = _LEADER_LABEL_RE.match(line.strip())
            if m:
                _add(m.group(1))
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[0]:
            years = _YEAR_RE.findall(parts[2])
            # Job headers span time: two year tokens ("2019 - 2021") or a
            # year plus a month/Present ("Jan 2024 - Present"). Projects and
            # education carry exactly ONE bare year and stay ungated.
            if len(years) >= 2 or (years and _TITLE_DATE_RANGE_RE.search(parts[2])):
                _add(parts[0])
                continue
        # Headline tagline: the •-separated stack is the LAST segment, and
        # every segment before it is a claimed title. v1 only handled the
        # spec's two-part shape and parts[0] — the 08-31 nightly shipped
        # "SOFTWARE ENGINEER | AI PRODUCTIZATION ENGINEER | …• MLflow •…",
        # smuggling the JD's title through the middle segment.
        if len(parts) >= 2 and "•" in parts[-1]:
            for p in parts[:-1]:
                if p:
                    _add(p)
    return list(seen.values())


def check_title_claims(draft: str, master_sources: list[str]) -> list[str]:
    """Held-title claims in *draft* not present in master-side text.

    Containment is word-boundary-aware on the normalized forms, so a master
    'Senior Software Engineer — Level 6' backs a draft 'Senior Software
    Engineer'. Direction matters: a draft title that is a SUBSET of a held
    title passes (under-claiming is honest), while adding seniority or
    inventing a role the master never states is the violation. The JD is
    never a source here — mirroring its title is the failure being caught.
    """
    corpus = " " + _normalize_title("\n".join(s for s in master_sources if s)) + " "
    return [
        t for t in extract_title_claims(draft)
        if _normalize_title(t) and f" {_normalize_title(t)} " not in corpus
    ]


def check_claims(
    draft: str,
    sources: list[str],
    master_sources: "list[str] | None" = None,
) -> list[str]:
    """Return claims in *draft* whose normalized form appears in no source.

    Sources are concatenated and normalized the same way as claims, so
    formatting differences (commas, case, 'percent' vs '%') don't matter.

    When *master_sources* is given, years-of-experience claims are
    additionally checked against it ALONE (see check_years_claims) — the one
    claim shape where the JD is not a valid source. Callers that don't pass
    it keep the pre-Round-2 behavior: years claims unchecked.
    """
    corpus = _normalize("\n".join(s for s in sources if s))
    violations = [
        c for c in extract_claims(draft)
        if not _contains_claim(corpus, _normalize(c))
    ]
    if master_sources is not None:
        violations.extend(check_years_claims(draft, master_sources))
        violations.extend(check_contact_claims(draft, master_sources))
        # Self-describing prefix: title violations carry no numeric shape, so
        # downstream consumers (feedback rule matching, dashboards, the
        # numeric agreement join's extractors) need the class named in the
        # string itself.
        violations.extend(
            f"unheld title: {t}" for t in check_title_claims(draft, master_sources)
        )
    return violations


def format_provenance_line(claims: list[str], violations: list[str]) -> str:
    """One-line human-readable verdict for generation confirmations.

    Single source of truth for how the gate's outcome reads — the agent
    pipeline header and the single-shot confirmation strings must format
    identically so dashboards and clients can match one shape.
    """
    if violations:
        shown = ", ".join(f'"{v}"' for v in violations[:6])
        if len(violations) > 6:
            shown += ", …"
        return f"Provenance: ⚠ {len(violations)} unsourced — {shown}"
    return (
        f"Provenance: ✓ PASS — {len(claims)} claims traced to source, 0 unsourced"
    )


def format_violation_feedback(violations: list[str]) -> str:
    """Render violations as a prompt section instructing their removal.

    Shared by both generation paths so a revision is asked for in the same
    words regardless of which one produced the draft — the agent pipeline's
    revise node and the single-shot correction pass.

    The "do not reword them into surviving" clause is load-bearing: the
    obvious failure mode is a model that keeps the fabricated number and
    hedges the sentence around it ("roughly 40k users"), which reads as
    compliance and still ships the invented figure.
    """
    if not violations:
        return ""
    listed = "\n".join(f"  - {v}" for v in violations)
    text = (
        "PROVENANCE VIOLATIONS (these numbers appear in NO source material — "
        "each one MUST be removed or replaced with a claim that exists in the "
        "master resume or STAR stories; do not reword them into surviving):\n"
        + listed
    )
    # Years-of-experience violations get their own instruction: the number
    # usually DOES appear somewhere — in the JD's requirements — so "appears
    # in no source" would invite the model to point at the JD and keep it.
    if any(_YEARS_CLAIM_RE.fullmatch(v.strip()) for v in violations):
        text += (
            "\nEXPERIENCE-DURATION RULE: a years-of-experience claim may only "
            "restate the master resume's own timeline. The job description's "
            "requirement ('5+ years of X') is NOT evidence of the candidate's "
            "experience — matching it is the violation. State the real "
            "duration from the master resume, or make the claim without a "
            "year count."
        )
    # Contact handles get their own instruction too: "remove" is the wrong fix
    # for a contact line — the fix is copying the master's handle exactly.
    if any(
        p.search(v) for v in violations for p in _CONTACT_HANDLE_RES
    ):
        text += (
            "\nCONTACT-DETAIL RULE: profile URLs and handles must be copied "
            "character-for-character from the master resume's contact block — "
            "do not remove the line; correct it to match the master exactly."
        )
    # Title violations get their own instruction: "remove the claim" is the
    # wrong fix for a job header (the role stays; its NAME is wrong), and the
    # JD is where the invented title usually came from — the model must not
    # point at it as evidence.
    if any(v.startswith("unheld title: ") for v in violations):
        text += (
            "\nHELD-TITLE RULE: job headers and the headline tagline may only "
            "use titles the master resume states the candidate actually held, "
            "copied from the master — never the job description's title, a "
            "self-description, or an activity dressed as a role. The fix is "
            "replacing the invented title with the master's actual title for "
            "that role and period (or the master's own headline); express "
            "target-role fit in the summary or bullets instead. Do not delete "
            "the role entry."
        )
    return text


def record_run(
    *,
    kind: str,
    company: str,
    role: str,
    job_description: str,
    chunk_texts: list[str],
    claims: list[str],
    violations: list[str],
    verdict: str,
    revisions: int,
    db_path=None,
) -> None:
    """Persist one generation's provenance record (partition-scoped DB).

    Never raises — provenance logging must not break generation. The row is
    the demonstrable artifact: a rejected-then-regenerated document shows
    its own history.
    """
    try:
        from lib.db import get_connection

        jd_hash = hashlib.sha256((job_description or "").encode()).hexdigest()[:16]
        chunk_hashes = [
            hashlib.sha256(t.encode()).hexdigest()[:16] for t in chunk_texts
        ]
        with get_connection(path=db_path) as conn:
            conn.execute(
                """INSERT INTO generation_provenance
                   (ts, kind, company, role, jd_hash, chunk_hashes,
                    claims, violations, verdict, revisions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    kind,
                    company,
                    role,
                    jd_hash,
                    json.dumps(chunk_hashes),
                    json.dumps(claims),
                    json.dumps(violations),
                    verdict,
                    revisions,
                ),
            )
        inc("provenance_checks_total", verdict=verdict, kind=kind)
        if violations:
            inc("provenance_violations_total", amount=len(violations), kind=kind)
    except Exception:  # noqa: BLE001 — logging must never break generation
        pass


def latest_run(
    *, company: str = "", role: str = "", db_path=None
) -> dict | None:
    """Most recent generation_provenance row (partition-scoped DB).

    Filters by company/role when given so a concurrent generation for a
    different job can't be mistaken for this one. Returns the row with
    claims/violations decoded, or None when nothing matches — the caller
    (the dashboard's violations modal) treats None as "no gate record".
    """
    from lib.db import get_connection

    where, params = [], []
    if company:
        where.append("company = ?")
        params.append(company)
    if role:
        where.append("role = ?")
        params.append(role)
    sql = (
        "SELECT id, ts, kind, company, role, claims, violations, verdict, "
        "revisions FROM generation_provenance"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY id DESC LIMIT 1"
    )
    with get_connection(path=db_path) as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    keys = ("id", "ts", "kind", "company", "role", "claims", "violations",
            "verdict", "revisions")
    out = dict(zip(keys, row))
    out["claims"] = json.loads(out["claims"] or "[]")
    out["violations"] = json.loads(out["violations"] or "[]")
    return out


def render_durable_metrics(db_path=None) -> str:
    """Prometheus gauge lines computed from the generation_provenance table.

    The in-process counters (provenance_checks_total) die with the serving
    process — pod restarts zeroed the wallboard's provenance stats while the
    durable truth sat in sqlite. Appended to /metrics so dashboards read
    all-time history. On multi-tenant cloud /metrics has no user context, so
    this reads the default (root) DB and may legitimately return nothing —
    per-tenant rows live in partition DBs; the in-process counters still
    cover live activity there.

    Never raises; returns "" on any failure.
    """
    try:
        from lib.db import get_connection

        with get_connection(path=db_path) as conn:
            rows = conn.execute(
                """SELECT verdict, kind, COUNT(*),
                          COALESCE(SUM(json_array_length(violations)), 0)
                   FROM generation_provenance GROUP BY verdict, kind"""
            ).fetchall()
        if not rows:
            return ""
        lines = ["# TYPE provenance_runs_total gauge"]
        viols: dict[str, int] = {}
        for verdict, kind, count, viol_count in rows:
            lines.append(
                f'provenance_runs_total{{verdict="{verdict}",kind="{kind}"}} {count}'
            )
            viols[kind] = viols.get(kind, 0) + int(viol_count or 0)
        lines.append("# TYPE provenance_violations_recorded_total gauge")
        for kind, n in sorted(viols.items()):
            lines.append(
                f'provenance_violations_recorded_total{{kind="{kind}"}} {n}'
            )
        try:
            from lib.db import get_connection as _gc
            with _gc(path=db_path) as c2:
                row = c2.execute(
                    "SELECT COUNT(*) FROM master_resume_edits"
                ).fetchone()
            lines.append("# TYPE master_resume_edits_total gauge")
            lines.append(f"master_resume_edits_total {int(row[0])}")
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 — metrics must never break the endpoint
        return ""


def record_master_edit(old_text: str, new_text: str, db_path=None) -> None:
    """Audit one in-place master resume edit (master_resume_edits, v8).

    The gate checks generated claims against the master resume; this table
    makes edits to that source of truth visible instead of silent. Captures
    the requesting user's oid when request context exists. Never raises.
    """
    try:
        from lib.db import get_connection

        oid = ""
        try:
            from lib.user_context import get_current_user_oid

            oid = get_current_user_oid() or ""
        except Exception:  # noqa: BLE001 — context is optional (stdio/desktop)
            pass
        with get_connection(path=db_path) as conn:
            conn.execute(
                "INSERT INTO master_resume_edits (ts, oid, old_text, new_text) "
                "VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), oid, old_text, new_text),
            )
        inc("master_resume_edits_total")
    except Exception:  # noqa: BLE001 — auditing must never break the edit
        pass
