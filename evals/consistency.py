"""Cross-run agreement eval for run_job_assessment's GAPS / RISKS section.

BUG-3 secondary finding (2026-08-28 WebMCP bug report): four assessment
runs on identical inputs produced divergent gap lists — one run uniquely
surfaced the most decision-relevant gap ("no formal ML model training"),
absent from the other three. The assessment samples at temperature 0.2,
so some divergence is expected; this eval makes it a tracked number
instead of an anecdote.

Method: run ``run_job_assessment`` N times on a fixed company/role/JD
(the committed synthetic Harborline JD by default — same inputs every
run, every checkout), extract the GAPS / RISKS bullets from each run,
cluster them across runs by token overlap (LLMs reword the same gap
freely — exact string match would score honest rephrasing as
divergence), then score agreement over the clustered gap identities:

    mean pairwise overlap  — Jaccard of gap-cluster sets between run
                             pairs; the headline agreement number
    consensus rate         — % of distinct gaps present in every run
    singletons             — gaps surfaced by exactly one run: the
                             BUG-3 signature, each one a finding the
                             other runs would have missed

The bullet-similarity metric is validated against the only real
divergence corpus available: the three surviving Mercedes-Benz USA
assessments recovered from 07-Job-Assessments (the BUG-3 duplicates
themselves, preserved by the very filename collisions the bug was
about). Full-token Jaccard alone scored that corpus 0% agreement with
12 singletons against a hand-labeled 6 clusters — production bullets
carry so much per-run verbiage that whole-set overlap dilutes below any
usable threshold. The composite in `_similarity` reproduces the
hand-labeling exactly; the corpus lives on as a regression test in
tests/test_consistency_eval.py.

Assessments run with ``auto_save=False`` so N eval runs never land in
07-Job-Assessments (or sync). Where the regeneration guard exists
(``force`` param, fix/webmcp-bridge-bugs), it is passed ``True`` —
divergence only matters for deliberate regenerations, which is exactly
what this measures.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# The committed synthetic JD (also the fixture-corpus JD): fully invented
# company, identical bytes on every machine — a fixed measurement basis.
DEFAULT_JD_FILE = "synthetic_jd.txt"
DEFAULT_COMPANY = "Harborline Technologies"
DEFAULT_ROLE = "Senior Backend Engineer, Logistics Platform"

# Two bullets are the same gap when _similarity reaches this. Calibrated
# on the recovered Mercedes BUG-3 corpus (see module docstring): at 0.5
# the composite merges every hand-labeled same-gap pair and none of the
# distinct-gap pairs.
CLUSTER_SIM_THRESHOLD = 0.5
# Mean pairwise overlap below this → gap lists unstable. Design value.
OVERLAP_ALERT_PCT = 60.0

# Glue words and discourse connectives. Negations (no/not/without/lacks)
# are deliberately kept: they carry the meaning of a gap bullet.
_STOPWORDS = frozenset(
    "a an the of to in on for and or with at by as is are be that this "
    "from has have had was were will would rather than while although "
    "though whether however but may might some does do there about "
    "beyond also only more most less".split()
)

# Assessment-boilerplate vocabulary (stemmed): present in gap bullets
# regardless of topic ("no direct experience", "not mentioned in the
# JD", "may limit fit for the role"), so it must never ANCHOR a same-gap
# match — on the Mercedes corpus "no"+"experience" alone tied together
# unrelated gaps. Still counted in the full-set Jaccard, where it is
# diluted honestly; excluded only from the topical-anchor overlap.
_GENERIC = frozenset(
    "no not none experience mention direct explicit evidence limit lack "
    "jd job description role candidate resume require requir strong "
    "appear work fit".split()
)


def _stem(t: str) -> str:
    """Crude suffix strip so plural/tense rewordings share tokens.

    Consistency matters, not linguistic correctness: 'technologies' and
    'technology' need not both become a real word, only the same token
    as each other on both sides of a comparison.
    """
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t

_GAPS_HEADER = re.compile(r"^##\s*GAPS\s*/?\s*RISKS.*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADER = re.compile(r"^##\s", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")


def extract_gaps_section(text: str) -> str | None:
    """The GAPS / RISKS section body, or None when the header is absent."""
    header = _GAPS_HEADER.search(text)
    if header is None:
        return None
    body_start = header.end()
    nxt = _NEXT_HEADER.search(text, body_start)
    return text[body_start:nxt.start() if nxt else len(text)]


def extract_bullets(section: str) -> list[str]:
    """Bullet texts from a section; indented continuation lines join up."""
    bullets: list[str] = []
    for line in section.splitlines():
        m = _BULLET.match(line)
        if m:
            bullets.append(m.group(1))
        elif bullets and line[:1].isspace() and line.strip():
            bullets[-1] += " " + line.strip()
    return bullets


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        stemmed
        for t in re.findall(r"[a-z0-9]+", text.casefold())
        if len(t) > 1 and t not in _STOPWORDS
        for stemmed in (_stem(t),)
        if len(stemmed) > 1
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _topical(bullet_tokens: list[frozenset[str]], n_runs: int) -> frozenset[str]:
    """Tokens that can anchor a same-gap match across this corpus.

    A gap's identity lives in mid-rarity tokens: rare enough not to be
    hedge boilerplate ("no direct experience"), common enough not to be
    one run's idiosyncratic verbiage. df counts bullets containing the
    token; the band is [2, n_runs+1] — a gap every run states once lands
    at df ≈ n_runs, boilerplate at df ≈ bullets-per-run × n_runs.
    """
    df: dict[str, int] = {}
    for toks in bullet_tokens:
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return frozenset(
        t for t, c in df.items() if 2 <= c <= n_runs + 1 and t not in _GENERIC
    )


def _similarity(a: frozenset[str], b: frozenset[str], topical: frozenset[str]) -> float:
    """Same-gap similarity: full-set Jaccard OR topical-anchor overlap.

    Jaccard alone scores real (verbose) rewordings of one gap below any
    usable threshold — unshared verbiage dilutes it. The second component
    ignores everything but the corpus's topical tokens and scores overlap
    against the smaller side, but only when at least two distinct topical
    tokens are shared: one shared keyword ("formal") is coincidence, two
    ("apache"+"technologies", "api"+"versioning") is a shared subject.
    """
    sim = _jaccard(a, b)
    at, bt = a & topical, b & topical
    shared = at & bt
    if len(shared) >= 2:
        sim = max(sim, len(shared) / min(len(at), len(bt)))
    return sim


@dataclass
class GapCluster:
    """One distinct gap identity, with every run's phrasing of it."""

    representative: str
    members: list[tuple[int, str]] = field(default_factory=list)  # (run idx, text)

    @property
    def runs(self) -> set[int]:
        return {i for i, _ in self.members}

    @property
    def support(self) -> int:
        return len(self.runs)

    def to_dict(self, n_runs: int) -> dict:
        return {
            "gap": self.representative,
            "support": f"{self.support}/{n_runs}",
            "runs": sorted(i + 1 for i in self.runs),
            "phrasings": sorted({t for _, t in self.members if t != self.representative}),
        }


def cluster_gaps(
    runs: list[list[str]], threshold: float = CLUSTER_SIM_THRESHOLD
) -> list[GapCluster]:
    """Greedy single-pass clustering of bullets across runs by _similarity.

    A bullet joins the cluster whose best member-similarity clears the
    threshold (highest wins); otherwise it founds a new cluster. Greedy is
    order-dependent in principle but stable in practice at these sizes
    (~5 bullets × ~5 runs), and deterministic for a given transcript —
    which is what a tracked metric needs. A bullet that genuinely spans
    two gaps (the Mercedes corpus had an Apache+EDGE combined bullet)
    joins whichever it matches best — single assignment, documented
    limitation.
    """
    clusters: list[GapCluster] = []
    token_cache: dict[str, frozenset[str]] = {}

    def toks(text: str) -> frozenset[str]:
        if text not in token_cache:
            token_cache[text] = _tokens(text)
        return token_cache[text]

    topical = _topical(
        [toks(b) for bullets in runs for b in bullets], n_runs=len(runs)
    )
    for run_idx, bullets in enumerate(runs):
        for bullet in bullets:
            best, best_sim = None, 0.0
            for cluster in clusters:
                sim = max(
                    _similarity(toks(bullet), toks(t), topical)
                    for _, t in cluster.members
                )
                if sim > best_sim:
                    best, best_sim = cluster, sim
            if best is not None and best_sim >= threshold:
                best.members.append((run_idx, bullet))
            else:
                clusters.append(GapCluster(bullet, [(run_idx, bullet)]))
    return clusters


def mean_pairwise_overlap_pct(clusters: list[GapCluster], n_runs: int) -> float:
    """Mean Jaccard of gap-cluster sets over all run pairs, as a percent.

    Two runs that both report no gaps agree perfectly (100), matching the
    prompt's "if there are none, say so" being a legitimate stable answer.
    """
    if n_runs < 2:
        return 100.0
    per_run = [
        frozenset(ci for ci, c in enumerate(clusters) if i in c.runs)
        for i in range(n_runs)
    ]
    return statistics.mean(
        _jaccard(per_run[i], per_run[j]) for i, j in combinations(range(n_runs), 2)
    ) * 100


@dataclass
class ConsistencyReport:
    company: str
    role: str
    jd_file: str
    n_requested: int
    threshold: float = CLUSTER_SIM_THRESHOLD
    runs: list[list[str]] = field(default_factory=list)  # bullets per completed run
    errors: list[str] = field(default_factory=list)
    clusters: list[GapCluster] = field(default_factory=list)
    model: str = ""
    master_sha: str = ""

    @property
    def n_ok(self) -> int:
        return len(self.runs)

    @property
    def overlap_pct(self) -> float:
        return mean_pairwise_overlap_pct(self.clusters, self.n_ok)

    @property
    def consensus_pct(self) -> float:
        """% of distinct gaps every completed run surfaced."""
        if not self.clusters:
            return 100.0
        return sum(c.support == self.n_ok for c in self.clusters) / len(self.clusters) * 100

    @property
    def singletons(self) -> list[GapCluster]:
        """Gaps surfaced by exactly one run — the BUG-3 signature."""
        if self.n_ok < 2:
            return []
        return [c for c in self.clusters if c.support == 1]

    @property
    def alerts(self) -> list[str]:
        if self.n_ok < 2:
            return ["fewer than 2 completed runs — agreement not measurable"]
        found = []
        if self.overlap_pct < OVERLAP_ALERT_PCT:
            found.append(
                f"gap-list agreement {self.overlap_pct:.0f}% < {OVERLAP_ALERT_PCT:.0f}%"
                " — assessment unstable across regenerations"
            )
        for c in self.singletons:
            run = min(c.runs) + 1
            found.append(
                f"gap surfaced only in run {run}/{self.n_ok}: {c.representative}"
            )
        return found

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "role": self.role,
            "jd_file": self.jd_file,
            "model": self.model,
            "master_sha": self.master_sha,
            "n_requested": self.n_requested,
            "n_ok": self.n_ok,
            "cluster_sim_threshold": self.threshold,
            "errors": self.errors,
            "gaps_per_run": [len(r) for r in self.runs],
            "overlap_pct": round(self.overlap_pct, 1),
            "consensus_pct": round(self.consensus_pct, 1),
            "singleton_count": len(self.singletons),
            "clusters": [c.to_dict(self.n_ok) for c in self.clusters],
            "runs": self.runs,
            "alerts": self.alerts,
        }

    def to_text(self) -> str:
        lines = [
            f"Assessment consistency — {self.company} / {self.role} "
            f"({self.jd_file}), {self.n_ok}/{self.n_requested} runs"
            + (f", model: {self.model}" if self.model else ""),
        ]
        for err in self.errors:
            lines.append(f"  ✗ {err}")
        if self.n_ok >= 2:
            lines += [
                "",
                f"gap bullets per run:  {' '.join(str(len(r)) for r in self.runs)}",
                f"mean pairwise overlap: {self.overlap_pct:.0f}%   "
                f"consensus: {self.consensus_pct:.0f}%   "
                f"singletons: {len(self.singletons)}",
                "",
                f"{'support':<9}gap",
            ]
            for c in sorted(self.clusters, key=lambda c: (-c.support, c.representative)):
                lines.append(f"{f'{c.support}/{self.n_ok}':<9}{c.representative[:100]}")
        for alert in self.alerts:
            lines.append(f"⚠ {alert}")
        return "\n".join(lines)


def default_assess(company: str, role: str, jd_text: str) -> str:
    """One real assessment through the production path (tools.fitment).

    auto_save=False keeps N eval runs out of 07-Job-Assessments and sync;
    force=True (where the regeneration guard exists) makes each call a real
    regeneration — the only case where divergence still matters.
    """
    import inspect  # noqa: PLC0415
    from tools import fitment  # noqa: PLC0415 — lazy: imports server config + LLM client

    kwargs: dict = {"auto_save": False}
    if "force" in inspect.signature(fitment.run_job_assessment).parameters:
        kwargs["force"] = True
    result = fitment.run_job_assessment(company, role, jd_text, **kwargs)
    # Anything but ✓ is the no-client context-pack fallback or an API error —
    # neither has a GAPS section worth scoring; fail the run instead.
    if not result.lstrip().startswith("✓"):
        raise RuntimeError(f"assessment did not complete: {result[:300]}")
    return result


def _resolve_jd(jd_file: str) -> Path | None:
    if not jd_file:
        return _FIXTURES_DIR / DEFAULT_JD_FILE
    from evals.golden import resolve_file  # noqa: PLC0415

    return resolve_file(jd_file)


def run_consistency(
    n: int = 5,
    company: str = DEFAULT_COMPANY,
    role: str = DEFAULT_ROLE,
    jd_file: str = "",
    assess_fn=None,
    threshold: float = CLUSTER_SIM_THRESHOLD,
) -> ConsistencyReport:
    """Run the assessment N times on one fixed input and score gap agreement."""
    report = ConsistencyReport(
        company=company,
        role=role,
        jd_file=jd_file or DEFAULT_JD_FILE,
        n_requested=n,
        threshold=threshold,
    )
    jd_path = _resolve_jd(jd_file)
    if jd_path is None or not jd_path.exists():
        report.errors.append(f"JD file not found: {jd_file or DEFAULT_JD_FILE}")
        return report
    jd_text = jd_path.read_text(encoding="utf-8")

    assess = assess_fn or default_assess
    for i in range(n):
        try:
            output = assess(company, role, jd_text)
            section = extract_gaps_section(output)
            if section is None:
                raise RuntimeError("no GAPS / RISKS section in assessment output")
            report.runs.append(extract_bullets(section))
        except Exception as e:  # noqa: BLE001 — one failed run must not eat the paid rest
            report.errors.append(f"run {i + 1}: {type(e).__name__}: {e}")
    report.clusters = cluster_gaps(report.runs, threshold=threshold)

    # Measurement-basis stamps, fail-soft (a stamp must never abort a run):
    # the model that ran and the master the assessments read.
    try:
        from lib.config import _resolve_llm_settings  # noqa: PLC0415

        report.model = _resolve_llm_settings(task="assessment")[1]
    except Exception:  # noqa: BLE001
        pass
    try:
        from lib.io import _load_master_context  # noqa: PLC0415

        report.master_sha = hashlib.sha256(
            _load_master_context().encode("utf-8")
        ).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        pass
    return report
