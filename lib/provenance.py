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
block; the parroting case is exactly what the (future) entailment tier is
for.
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


def check_claims(draft: str, sources: list[str]) -> list[str]:
    """Return claims in *draft* whose normalized form appears in no source.

    Sources are concatenated and normalized the same way as claims, so
    formatting differences (commas, case, 'percent' vs '%') don't matter.
    """
    corpus = _normalize("\n".join(s for s in sources if s))
    return [
        c for c in extract_claims(draft)
        if not _contains_claim(corpus, _normalize(c))
    ]


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
        return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 — metrics must never break the endpoint
        return ""
