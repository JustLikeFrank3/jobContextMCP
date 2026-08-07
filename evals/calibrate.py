"""Reference-judging calibration: the judge scores the committed golden
references, and per-dimension MAE against the blind human labels is
computed by code rather than by hand (the 2026-08-04 audit found the
docs/evals.md tables had no recomputation path).

Methodology matches the two committed passes: same rubric, same master
excerpt (runner default cap), N runs per entry, JSON failures recorded as
errors — never as scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from evals.golden import load_golden, resolve_file
from evals.judge import JUDGE_DIMENSIONS, JudgeScore, judge_output


@dataclass
class EntryCalibration:
    entry_id: str
    labels: dict[str, int]
    scores: list[JudgeScore] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def dimension_mean(self, dim: str) -> float | None:
        vals = [s.scores[dim] for s in self.scores if dim in s.scores]
        return sum(vals) / len(vals) if vals else None

    def hallucination_rate(self) -> str:
        """Fraction of successful runs that flagged at least one hallucination."""
        if not self.scores:
            return "0/0"
        flagged = sum(1 for s in self.scores if s.hallucinations)
        return f"{flagged}/{len(self.scores)}"

    def all_hallucinations(self) -> list[str]:
        """Deduplicated hallucination claims flagged across runs, first-seen order."""
        seen: list[str] = []
        for s in self.scores:
            for h in s.hallucinations:
                if h not in seen:
                    seen.append(h)
        return seen

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "labels": self.labels,
            "judge_means": {
                d: round(m, 2) for d in JUDGE_DIMENSIONS
                if (m := self.dimension_mean(d)) is not None
            },
            "runs_ok": len(self.scores),
            "errors": self.errors,
            "hallucinations_flagged": self.hallucination_rate(),
            "hallucination_claims": self.all_hallucinations(),
        }


@dataclass
class CalibrationReport:
    judge_model: str
    n: int
    entries: list[EntryCalibration] = field(default_factory=list)

    def mae(self) -> dict[str, float | None]:
        """Per-dimension MAE: mean over entries of |label − judge mean|.

        Entries whose every run errored are excluded from that dimension —
        an absent judge opinion is not a 0-error opinion.
        """
        out: dict[str, float | None] = {}
        for dim in JUDGE_DIMENSIONS:
            diffs = [
                abs(e.labels[dim] - m) for e in self.entries
                if dim in e.labels and (m := e.dimension_mean(dim)) is not None
            ]
            out[dim] = round(sum(diffs) / len(diffs), 2) if diffs else None
        return out

    def to_dict(self) -> dict:
        return {
            "judge_model": self.judge_model,
            "n": self.n,
            "mae": self.mae(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_text(self) -> str:
        lines = [f"Calibration — judge {self.judge_model or '?'}, N={self.n} per entry", ""]
        header = f"{'entry':8}" + "".join(f"{d[:12]:>14}" for d in JUDGE_DIMENSIONS) + f"{'runs':>6}"
        lines.append(header)
        for e in self.entries:
            cells = ""
            for d in JUDGE_DIMENSIONS:
                m = e.dimension_mean(d)
                cells += f"{e.labels.get(d, '?')!s:>7}/" + (f"{m:<6.2f}" if m is not None else "  --  ")
            lines.append(f"{e.entry_id:8}" + cells + f"{len(e.scores):>4}/{self.n}"
                         + f"  hallucinations {e.hallucination_rate()}")
            for err in e.errors:
                lines.append(f"         error: {err[:100]}")
        lines.append("")
        mae = self.mae()
        lines.append("MAE:    " + "".join(
            f"{(f'{v:.2f}' if v is not None else '--'):>14}" for v in mae.values()
        ))
        lines.append("(cells are human-label/judge-mean)")
        return "\n".join(lines)


def run_calibration(n: int = 5, entry_ids: "set[str] | None" = None) -> CalibrationReport:
    from evals.runner import _master_excerpt  # noqa: PLC0415
    from tools import resume  # noqa: PLC0415

    master = _master_excerpt(master_text=resume.read_master_resume())
    report = CalibrationReport(judge_model="", n=n)
    for entry in load_golden():
        if entry_ids and entry.id not in entry_ids:
            continue
        if not entry.labels:
            continue
        cal = EntryCalibration(entry_id=entry.id, labels=dict(entry.labels))
        jd_path = resolve_file(entry.jd_file)
        ref_path = resolve_file(entry.reference_file)
        if jd_path is None or ref_path is None:
            missing = entry.jd_file if jd_path is None else entry.reference_file
            cal.errors.append(f"file not found: {missing}")
            report.entries.append(cal)
            continue
        jd = jd_path.read_text(encoding="utf-8")
        reference = ref_path.read_text(encoding="utf-8")
        for _ in range(n):
            try:
                score = judge_output(jd, master, reference)
            except Exception as exc:  # error is data here, never a score
                cal.errors.append(f"{type(exc).__name__}: {exc}")
                continue
            cal.scores.append(score)
            if score.model:
                report.judge_model = score.model
        report.entries.append(cal)
    return report
