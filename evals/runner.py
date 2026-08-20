"""Layer 3 orchestration — the full eval suite.

For each golden entry: generate the output N times, judge every run,
aggregate variance metrics, and append a version-stamped results row.
Results land in ``evals/results/`` (gitignored) and each run is compared
to the previous one so score drift is visible immediately.

Re-run on any change to: master resume, prompt templates, model version,
or MCP tool logic.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from evals.golden import GoldenEntry, load_golden, resolve_file
from evals.judge import JudgeScore, judge_output
from evals.variance import RunAggregate, aggregate_runs
from lib import provenance as provenance_mod

RESULTS_DIR = Path(__file__).parent / "results"

GenerateFn = Callable[[GoldenEntry, str], str]      # (entry, jd_text) → output text
JudgeFn = Callable[[str, str, str], JudgeScore]      # (jd, master_excerpt, output) → score
CriticFn = Callable[[str, str], dict]                # (master_excerpt, output) → {"model", "findings"}

# no_record is deliberately distinct from both_clean: a missing provenance row
# (record_run swallows its own failures) means the comparison never happened,
# not that both checks came back clean.
AGREEMENT_KEYS: tuple[str, ...] = (
    "both_flagged", "both_clean", "judge_only", "provenance_only", "no_record",
)


def _empty_agreement() -> dict[str, int]:
    return dict.fromkeys(AGREEMENT_KEYS, 0)


@dataclass
class EntryResult:
    entry_id: str
    role: str
    aggregate: RunAggregate | None = None
    error: str = ""
    provenance_agreement: dict[str, int] = field(default_factory=_empty_agreement)
    judge_models: list[str] = field(default_factory=list)  # distinct, as stamped on the scores
    # Phase-1 entailment critic: report-only, one critique of the FIRST
    # generated document per entry (calibration needs coverage, not
    # repetition — a second critique of the same entry buys agreement data,
    # not coverage, at full bundle cost). {"model", "findings"} on success,
    # {"error": ...} on failure, None when no critic ran. Never feeds
    # verdicts, alerts, or gates — the whistle comes after the calibration.
    critic: "dict | None" = None

    def dashboard_row(self) -> dict:
        """One row of the doc's results table."""
        base = {
            "gd_id": self.entry_id,
            "role": self.role,
            "error": self.error,
            "provenance_agreement": dict(self.provenance_agreement),
        }
        if self.aggregate is None:
            return base
        dims = self.aggregate.per_dimension
        return {
            **base,
            "keyword": round(dims["keyword_coverage"]["mean"], 2),
            "relevance": round(dims["relevance"]["mean"], 2),
            "accuracy": round(dims["accuracy"]["mean"], 2),
            "impact": round(dims["impact_language"]["mean"], 2),
            "ats": round(dims["ats_readiness"]["mean"], 2),
            "mean": round(self.aggregate.mean_score, 2),
            "cov_pct": round(self.aggregate.cov_pct, 1),
            "flip_rate_pct": round(self.aggregate.flip_rate_pct, 1),
            "alerts": self.aggregate.alerts,
        }


@dataclass
class SuiteResult:
    n_runs: int
    entries: list[EntryResult] = field(default_factory=list)
    started_at: str = ""
    git_sha: str = ""
    provider: str = ""
    judge_provider: str = ""
    judge_model: str = ""

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "git_sha": self.git_sha,
            "provider": self.provider,
            "judge_provider": self.judge_provider,
            "judge_model": self.judge_model,
            "n_runs": self.n_runs,
            "rows": [e.dashboard_row() for e in self.entries],
            "detail": {
                e.entry_id: (
                    {**e.aggregate.to_dict(), "critic": e.critic}
                    if e.critic is not None else e.aggregate.to_dict()
                )
                for e in self.entries if e.aggregate is not None
            },
        }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).parent, check=False,
        ).stdout.strip()
    except OSError:
        return ""


def _cleanup_eval_artifacts(output_filename: str) -> None:
    """Delete the workspace files one eval generation left behind.

    Eval outputs are measurements, not application materials: everything the
    suite needs (scores, flagged claims, provenance verdicts) is persisted in
    the results payload before this runs. Leaving the files in place meant
    every nightly run parked five EVAL resumes + PDFs in the user's real
    materials directories, sync mirrored them onto every desktop (and sync has
    no delete propagation, so they never left), and build_index ingested them
    into the RAG corpus. Set EVALS_KEEP_ARTIFACTS=1 to keep the files for a
    debugging session. Never raises — cleanup must not eat a paid run.
    """
    import os  # noqa: PLC0415

    if os.environ.get("EVALS_KEEP_ARTIFACTS", "").strip().lower() in ("1", "true", "yes"):
        return
    from lib import config  # noqa: PLC0415

    try:
        dirs = [
            config.get_active_optimized_resumes_dir(),
            config.get_active_cover_letters_dir(),
            config.get_active_resume_pdfs_dir(),
            config.get_active_cover_letter_pdfs_dir(),
        ]
    except Exception:
        return
    for d in dirs:
        try:
            for path in d.glob(f"{output_filename}.*"):
                path.unlink(missing_ok=True)
        except Exception:
            continue


def default_generate(entry: GoldenEntry, jd_text: str) -> str:
    """Generate through the real production path (tools.generate).

    Outputs are saved under an EVAL-prefixed filename so eval artifacts are
    recognizable and can never overwrite real application materials — and are
    deleted again once read, so the workspace, sync, and the RAG index never
    see them (see _cleanup_eval_artifacts).
    """
    from lib import config  # noqa: PLC0415 — lazy: imports server config + LLM client
    from tools import generate  # noqa: PLC0415

    output_filename = f"EVAL {entry.id} {entry.company} {entry.role}"
    try:
        if entry.output_kind == "cover_letter":
            status = generate.generate_cover_letter(
                entry.company, entry.role, jd_text, output_filename=output_filename
            )
            out_dir = config.get_active_cover_letters_dir()
        else:
            status = generate.generate_resume(
                entry.company, entry.role, jd_text, output_filename=output_filename
            )
            out_dir = config.get_active_optimized_resumes_dir()
        # generate_* returns a status report; the document itself is saved to
        # the workspace. A missing ✓ means generation fell back or errored —
        # fail the run rather than judging a status message.
        if not status.lstrip().startswith("✓"):
            raise RuntimeError(f"generation did not complete: {status[:300]}")
        return (out_dir / f"{output_filename}.txt").read_text(encoding="utf-8")
    finally:
        # Runs on the error path too: a failed generation can still have
        # saved a .txt or exported a PDF before its status went sideways.
        _cleanup_eval_artifacts(output_filename)


# Truncation here is a measurement bug, not a cost control: every char cut is
# a claim the judge will call a hallucination because it never saw the source
# (the 6K-cap incident, then again in 2026-08 when story-sourced claims were
# flagged for weeks). The bundle now includes the STORIES section, so the cap
# must clear master + achievements + feedback + all stories. 200K chars ≈ 50K
# tokens — fine for the hosted judges; a local 40K-context judge model needs
# either a bigger context window or a smaller source library, NOT a lower cap.
def _master_excerpt(max_chars: int = 200_000, master_text: str | None = None) -> str:
    if master_text is not None:
        return master_text[:max_chars]
    from tools import resume  # noqa: PLC0415 — lazy: imports server config

    return resume.read_master_resume()[:max_chars]


def _numeric_provenance_agreement(
    judge_hallucinations: list[str],
    provenance_row: dict | None,
) -> dict[str, int]:
    """Classify a run by whether judge and provenance both flagged numeric claims."""
    buckets = _empty_agreement()
    if provenance_row is None:
        buckets["no_record"] = 1
        return buckets

    def _numeric_and_years(text: str) -> "list[str]":
        # Years-of-experience claims are gated (Round 2) but never matched
        # the numeric patterns — without this union, a years-only run counts
        # as both_clean while the gate's row carries a violation.
        return [
            *provenance_mod.extract_claims(text),
            *provenance_mod.extract_years_claims(text),
        ]

    judge_claims = {
        claim
        for text in judge_hallucinations
        for claim in _numeric_and_years(text)
    }
    prov_claims = {
        claim
        for text in (provenance_row or {}).get("violations", [])
        for claim in _numeric_and_years(text)
    }
    if judge_claims and prov_claims:
        buckets["both_flagged"] = 1
    elif judge_claims:
        buckets["judge_only"] = 1
    elif prov_claims:
        buckets["provenance_only"] = 1
    else:
        buckets["both_clean"] = 1
    return buckets


# Distinct from None ("no row existed yet"): the pre-read itself failed, so
# a post-generation row's freshness cannot be proven against anything.
_PRE_READ_FAILED = object()


def _fenced_provenance_row(entry: GoldenEntry, pre_row_id) -> dict | None:
    """Provenance row written by THIS generation, or None.

    record_run swallows its own failures, so latest_run can return a stale row
    from a previous generation of the same company/role — comparing the id
    against the pre-generation row fences that out. A failed pre-read means
    freshness is unprovable, so no row may pass the fence at all. Never
    raises: a provenance lookup failure must not discard the judge score it
    accompanies.
    """
    if pre_row_id is _PRE_READ_FAILED:
        return None
    try:
        row = provenance_mod.latest_run(company=entry.company, role=entry.role)
    except Exception:
        return None
    if row is not None and pre_row_id is not None and row.get("id") == pre_row_id:
        return None
    return row


def _latest_provenance_id(entry: GoldenEntry):
    try:
        row = provenance_mod.latest_run(company=entry.company, role=entry.role)
    except Exception:
        return _PRE_READ_FAILED
    return row.get("id") if row else None


def default_critic(master: str, output: str) -> dict:
    """Phase-1 entailment critique of one document (evals/critic.py)."""
    from evals.critic import critique_document  # noqa: PLC0415 — lazy: no LLM imports at module load

    return critique_document(master, output)


def run_entry(
    entry: GoldenEntry,
    n: int = 5,
    generate_fn: GenerateFn | None = None,
    judge_fn: JudgeFn | None = None,
    critic_fn: "CriticFn | None" = None,
) -> EntryResult:
    """Generate + judge one golden entry N times (+ one report-only critique)."""
    jd_path = resolve_file(entry.jd_file)
    if jd_path is None:
        return EntryResult(entry.id, entry.role, error=f"JD file not found: {entry.jd_file}")
    jd_text = jd_path.read_text(encoding="utf-8")
    generate = generate_fn or default_generate
    judge = judge_fn or (
        lambda jd, master, output: judge_output(jd, master, output)
    )
    critic = default_critic if critic_fn is None else critic_fn
    master = _master_excerpt()
    scores: list[JudgeScore] = []
    errors: list[str] = []
    provenance_agreement = _empty_agreement()
    critic_result: "dict | None" = None
    for i in range(n):
        pre_row_id = _latest_provenance_id(entry)
        try:
            output = generate(entry, jd_text)
            score = judge(jd_text, master, output)
        except Exception as e:
            errors.append(f"run {i + 1}: {type(e).__name__}: {e}")
            continue
        # Outside the try: a provenance failure must not discard a paid score.
        provenance_row = _fenced_provenance_row(entry, pre_row_id)
        agreement = _numeric_provenance_agreement(score.hallucinations, provenance_row)
        for key in provenance_agreement:
            provenance_agreement[key] += agreement[key]
        scores.append(score)
        # One critique per entry, on the first successfully judged document —
        # coverage over repetition. Report-only: a critic failure is recorded
        # and costs nothing else (the judge scores it accompanies stand).
        if critic_result is None:
            try:
                critic_result = critic(master, output)
            except Exception as e:  # noqa: BLE001 — report-only means fail-soft
                critic_result = {"error": f"{type(e).__name__}: {e}"}
    if not scores:
        return EntryResult(entry.id, entry.role, error="; ".join(errors) or "no runs completed")
    result = EntryResult(
        entry.id,
        entry.role,
        aggregate=aggregate_runs(scores),
        provenance_agreement=provenance_agreement,
        judge_models=list(dict.fromkeys(s.model for s in scores if s.model)),
        critic=critic_result,
    )
    if errors:
        result.error = "; ".join(errors)
    return result


def run_suite(
    entries: list[GoldenEntry] | None = None,
    n: int = 5,
    generate_fn: GenerateFn | None = None,
    judge_fn: JudgeFn | None = None,
    critic_fn: "CriticFn | None" = None,
    results_dir: Path | None = None,
) -> SuiteResult:
    """Run the full suite and persist a version-stamped results file."""
    from lib import config as config_mod  # noqa: PLC0415
    from lib.config import llm_generation_status  # noqa: PLC0415

    provider, _ready = llm_generation_status()
    judge_provider, judge_model = config_mod._resolve_llm_settings(task="eval_judge")
    suite = SuiteResult(
        n_runs=n,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        git_sha=_git_sha(),
        provider=provider,
        judge_provider=judge_provider,
        judge_model=judge_model,
    )
    for entry in entries if entries is not None else load_golden():
        suite.entries.append(run_entry(
            entry, n=n, generate_fn=generate_fn, judge_fn=judge_fn, critic_fn=critic_fn,
        ))
    # Report the judge model that actually ran, not the config's promise;
    # the config-derived value stands only when no score carries a model.
    ran_models = list(dict.fromkeys(m for e in suite.entries for m in e.judge_models))
    if ran_models:
        suite.judge_model = ", ".join(ran_models)
    save_results(suite, results_dir)
    return suite


def save_results(suite: SuiteResult, results_dir: Path | None = None) -> Path:
    out_dir = results_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = suite.started_at.replace(":", "").replace("-", "").replace("T", "-") or "unstamped"
    path = out_dir / f"results-{stamp}.json"
    suffix = 2
    while path.exists():  # two runs in the same second must not clobber each other
        path = out_dir / f"results-{stamp}-{suffix}.json"
        suffix += 1
    payload = suite.to_dict()
    previous = latest_results(out_dir, before=path)
    if previous is not None:
        payload["baseline"] = str(previous[0].name)
        payload["baseline_delta"] = _delta(payload, previous[1])
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def latest_results(
    results_dir: Path | None = None, before: Path | None = None
) -> tuple[Path, dict] | None:
    out_dir = results_dir or RESULTS_DIR
    if not out_dir.exists():
        return None
    files = sorted(
        (p for p in out_dir.glob("results-*.json") if p != before),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return None
    newest = files[-1]
    try:
        return newest, json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _delta(current: dict, baseline: dict) -> dict:
    """Per-entry mean/keyword deltas vs. the previous run."""
    base_rows = {r.get("gd_id"): r for r in baseline.get("rows", [])}
    deltas: dict[str, dict] = {}
    for row in current.get("rows", []):
        base = base_rows.get(row.get("gd_id"))
        if not base or "mean" not in row or "mean" not in base:
            continue
        keyword_delta = round(row["keyword"] - base["keyword"], 2)
        deltas[row["gd_id"]] = {
            "mean": round(row["mean"] - base["mean"], 2),
            "keyword": keyword_delta,
            # −0.5 flag level from docs/eval-framework.md (variance-analysis
            # table); a design value, not yet validated against data.
            "keyword_regression": keyword_delta < -0.5,
        }
    return deltas


def format_dashboard(suite: SuiteResult) -> str:
    """The doc's sample results table, as fixed-width text."""
    header = (
        f"{'GD-ID':6} {'Role':28} {'Keyword':>7} {'Relev.':>6} {'Accur.':>6} "
        f"{'Impact':>6} {'ATS':>5} {'Mean':>5} {'CoV%':>5} {'Flip%':>5} {'Prov':>11}"
    )
    lines = [header, "─" * len(header)]
    for e in suite.entries:
        row = e.dashboard_row()
        if "error" in row and "mean" not in row:
            lines.append(f"{row['gd_id']:6} {row['role'][:28]:28} ERROR: {row['error']}")
            continue
        agreement = row.get("provenance_agreement", {})
        prov_text = "/".join(str(agreement.get(k, 0)) for k in AGREEMENT_KEYS)
        lines.append(
            f"{row['gd_id']:6} {row['role'][:28]:28} {row['keyword']:>7} "
            f"{row['relevance']:>6} {row['accuracy']:>6} {row['impact']:>6} "
            f"{row['ats']:>5} {row['mean']:>5} {row['cov_pct']:>5} {row['flip_rate_pct']:>5} {prov_text:>11}"
        )
        for alert in row.get("alerts", []):
            lines.append(f"       ⚠ {alert}")
    lines.append("Prov: " + "/".join(AGREEMENT_KEYS))
    return "\n".join(lines)
