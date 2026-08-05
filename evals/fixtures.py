"""Planted-error fixture corpus — judge calibration (audit repair 4).

Fixtures exercise the judge, not the generation pipeline: every corrupted
output under ``fixtures/`` is pre-written (baseline + one surgical edit,
documented in the manifest's ``corruption_note``) and judged directly
against the committed synthetic master + JD. Nothing here goes through
``run_suite`` or generation, and the corpus is fully synthetic — invented
person, employers, and numbers.

A "catch" is class-dependent:
- fabrication classes (``expected_signal == "hallucination"``): some
  hallucination entry overlaps the planted claim, by substring in either
  direction or by numeric-claim intersection via lib.provenance.
- style classes (``expected_signal == "dimension"``): the target
  dimension scores below 3 (the rubric floor).
- the clean baseline (``expected_signal == "clean"``): any hallucination
  flag is a false positive. Per-class catch rates are meaningless without
  this control — a judge that flags the clean file is measuring noise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lib.provenance import check_claims, extract_claims

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_MANIFEST_PATH = _FIXTURES_DIR / "fixture_dataset.json"

# Below the rubric floor (rubrics.THRESHOLDS min_dimension), matching passes().
_DIMENSION_CATCH_BELOW = 3


@dataclass(frozen=True)
class FixtureEntry:
    id: str
    file: str
    fixture_class: str
    expected_signal: str  # "hallucination" | "dimension" | "clean"
    expected_detail: str
    corruption_note: str


def load_fixture_manifest(manifest_path: Path | None = None) -> tuple[str, str, list[FixtureEntry]]:
    """Return (master_file, jd_file, entries) from the fixture manifest."""
    data = json.loads((manifest_path or _FIXTURE_MANIFEST_PATH).read_text(encoding="utf-8"))
    entries = [
        FixtureEntry(
            id=e["id"],
            file=e["file"],
            fixture_class=e["class"],
            expected_signal=e["expected_signal"],
            expected_detail=e["expected_detail"],
            corruption_note=e["corruption_note"],
        )
        for e in data["entries"]
    ]
    return data["master_file"], data["jd_file"], entries


def load_fixture_entries() -> list[FixtureEntry]:
    return load_fixture_manifest()[2]


def claim_caught(hallucinations: list[str], planted: str) -> bool:
    """Did any hallucination entry name the planted claim?

    Substring match in either direction (judges quote whole sentences or
    just the offending token), then numeric-claim intersection so "52%"
    matches "latency by 52%" however the judge phrases it.
    """
    planted_fold = planted.casefold()
    texts = [str(h) for h in hallucinations]
    for h in texts:
        h_fold = h.casefold().strip()
        if len(h_fold) >= 3 and (planted_fold in h_fold or h_fold in planted_fold):
            return True
    planted_claims = extract_claims(planted)
    if planted_claims:
        missing = check_claims(planted, [" ".join(texts)])
        if len(missing) < len(planted_claims):
            return True
    return False


def _run_caught(entry: FixtureEntry, score) -> bool:
    if entry.expected_signal == "hallucination":
        return claim_caught(score.hallucinations, entry.expected_detail)
    if entry.expected_signal == "dimension":
        return score.scores.get(entry.expected_detail, 5) < _DIMENSION_CATCH_BELOW
    # clean baseline: a "catch" is a false positive
    return bool(score.hallucinations)


@dataclass
class FixtureResult:
    entry: FixtureEntry
    catches: int
    n: int
    means: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.entry.id,
            "class": self.entry.fixture_class,
            "expected_signal": self.entry.expected_signal,
            "catches": self.catches,
            "n": self.n,
            "means": [round(m, 2) for m in self.means],
        }


@dataclass
class FixtureReport:
    n: int
    results: list[FixtureResult] = field(default_factory=list)
    judge_models: list[str] = field(default_factory=list)

    @property
    def baseline_false_positives(self) -> int | None:
        for r in self.results:
            if r.entry.expected_signal == "clean":
                return r.catches
        return None

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "judge_models": self.judge_models,
            "baseline_false_positives": self.baseline_false_positives,
            "results": [r.to_dict() for r in self.results],
        }

    def to_text(self) -> str:
        lines = [
            f"Fixture corpus — {len(self.results)} fixtures × N={self.n}, "
            f"judge: {', '.join(self.judge_models) or 'unknown'}",
            "",
            f"{'id':<7}{'class':<22}{'signal':<15}{'catch':<8}mean scores",
        ]
        for r in self.results:
            label = "FP" if r.entry.expected_signal == "clean" else "catch"
            lines.append(
                f"{r.entry.id:<7}{r.entry.fixture_class:<22}{r.entry.expected_signal:<15}"
                f"{label} {r.catches}/{r.n:<4}{' '.join(f'{m:.1f}' for m in r.means)}"
            )
        fp = self.baseline_false_positives
        if fp is not None:
            lines += ["", f"Clean-baseline false positives: {fp}/{self.n} "
                          "(nonzero means the judge flags traceable content — "
                          "read the catch rates accordingly)"]
        return "\n".join(lines)


def run_fixture_suite(n: int = 5, judge_fn=None) -> FixtureReport:
    """Judge every fixture N times against the synthetic master + JD.

    ``judge_fn(jd, master, output)`` defaults to ``evals.judge.judge_output``.
    The synthetic master is passed whole — no ``_master_excerpt``, no
    generation, no workspace access.
    """
    if judge_fn is None:
        from evals.judge import judge_output  # noqa: PLC0415 — lazy: tests inject judge_fn

        judge_fn = judge_output
    master_file, jd_file, entries = load_fixture_manifest()
    master = (_FIXTURES_DIR / master_file).read_text(encoding="utf-8")
    jd = (_FIXTURES_DIR / jd_file).read_text(encoding="utf-8")

    report = FixtureReport(n=n)
    seen_models: dict[str, None] = {}
    for entry in entries:
        output = (_FIXTURES_DIR / entry.file).read_text(encoding="utf-8")
        result = FixtureResult(entry=entry, catches=0, n=n)
        for _ in range(n):
            score = judge_fn(jd, master, output)
            result.means.append(score.mean)
            if getattr(score, "model", ""):
                seen_models.setdefault(score.model)
            if _run_caught(entry, score):
                result.catches += 1
        report.results.append(result)
    report.judge_models = list(seen_models)
    return report
