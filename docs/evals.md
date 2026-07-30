# Eval Framework — Three Layers, LLM-as-Judge, CI Gate

The generation pipeline has a regression harness in [`evals/`](../evals/). Three layers, from cheap-and-deterministic to adversarial:

**Layer 1 — functional tool evals.** 22 declarative cases (`evals/cases.py`) run through `tools.consolidated._run` — the exact dispatch path MCP clients hit — so parameter coercion, missing-parameter errors, and action routing are all under test. Cases are tagged (`smoke`, `read-only`, `write`, `error-handling`, `semantic`, `network`); the report carries pass rate and latency p50/p95, and **a smoke pass rate below 95% blocks release**.

**Layer 2 — rubrics.** Resume (6 dimensions) and cover-letter (5 dimensions) scoring schemas with hard thresholds (resume: avg ≥ 4.0, no dimension < 3). Applied by a human or by the Layer 3 judge — same schema either way.

**Layer 3 — adversarial LLM-as-judge.** A separate model call receives the JD, the master resume, and the generated output, and is prompted to find weaknesses — hallucinations, weak bullets, missing keywords — not to be generous. Scores five dimensions plus a `hallucinations` list and a pass/fail verdict. N-run variance analysis computes mean, coefficient of variation, hallucination rate, and verdict flip rate, with alert thresholds (mean < 3.8, CoV > 20%, any hallucination, flips > 20%) and baseline delta tracking (keyword score dropping > 0.5 flags a prompt regression).

**Golden dataset.** `evals/golden_dataset.json` commits a 5-entry manifest (JDs recovered verbatim from the application queue); the JD/reference files themselves are personal data resolved from the workspace at run time. Eval-generated documents save under an `EVAL` prefix so artifacts never overwrite real materials.

**Judge calibration.** The judge knows today's date (real dates aren't "future-dated"), sees the full master resume rather than a 6K-char truncation (truncation made the judge flag real-but-unseen claims as hallucinations), and filters clean-bill notes ("no hallucinations detected") out of the hallucinations array. Flagged claims are persisted in run aggregates so an alert carries its evidence.

## Running the evals

```bash
python -m evals layer1 --tags smoke          # functional cases against the active workspace
python -m evals layer1 --verbose             # all non-network, non-write cases
python -m evals judge --jd jd.txt --output resume.txt -n 5
python -m evals suite -n 5 --push            # full golden suite + push results to the server
python -m evals push                         # re-push the newest results file
```

`--push-url` defaults to `$JOBCONTEXT_EVAL_URL`, `--api-key` to `$JOBCONTEXT_API_KEY`. Write-tagged Layer 1 cases are excluded by default — only use `--include-writes` in an isolated namespace, never against live data.

## Server-side runs

The suite also runs inside the server via the control plane (work kind `run_evals`) — partition data and provider credentials already live there:

- `POST /api/evals/run` (`{n?: 1–10, entries?: ["GD-01", …]}`) enqueues a run and returns the work id.
- `EVALS_NIGHTLY_HOUR_UTC=<0–23>` schedules one run per day in the owner's partition from the always-on pod — a fixed-model drift baseline, with workstation runs as a comparison overlay.
- Results history lands under `<partition>/eval_runs/`.

## Metrics & dashboard

Results push into `eval_*` Prometheus gauges (`eval_mean_score`, `eval_cov_pct`, `eval_hallucination_rate_pct`, `eval_verdict_flip_rate_pct`, `eval_dimension_score`, `eval_layer1_pass_rate_pct`, `eval_last_run_timestamp_seconds`, …), restored from stored results at startup so a pod restart doesn't blank the wallboard. A `kiosk-evals` Grafana dashboard renders them; its queries are source-agnostic, so the board keeps showing scores when the workstation is off.

## CI gate

`scripts/ci_smoke_gate.py` runs every non-network Layer 1 case against an isolated throwaway workspace in `deploy.yml`'s test job. Smoke pass rate below 95% exits non-zero — the deploy jobs never run. It validates the tool surface, not live data; the live complement is `python -m evals layer1 --tags smoke` against a real workspace.

The test suite doubles as a drift guard: every eval case must reference a real domain, action, and parameter (`tests/test_evals.py`), so a tool-surface rename fails CI before it fails a live eval.
