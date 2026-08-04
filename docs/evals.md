# Eval Framework — Three Layers, LLM-as-Judge, CI Gate

The generation pipeline has a regression harness in [`evals/`](../evals/). Three layers, from cheap-and-deterministic to adversarial:

**Layer 1 — functional tool evals.** 24 declarative cases across all 12 domains (`evals/cases.py`) run through `tools.consolidated._run` — the exact dispatch path MCP clients hit — so parameter coercion, missing-parameter errors, and action routing are all under test. Cases are tagged (`smoke`, `read-only`, `write`, `error-handling`, `semantic`, `network`); the report carries pass rate and latency p50/p95, and **a smoke pass rate below 95% blocks release**. Smoke markers are code-emitted literals — exact strings the tools actually print, covering every reachable state (empty workspace, populated workspace, and filtered-empty where one exists) — so a passing gate means the tool answered, not merely that something non-empty came back. A replay test (`tests/test_evals.py`) re-checks every marker against recorded real responses, so a marker typo fails in pytest instead of first surfacing as a blocked deploy.

**Layer 2 — rubrics.** Resume (6 dimensions) and cover-letter (5 dimensions) scoring schemas with hard thresholds (resume: avg ≥ 4.0, no dimension < 3). Applied by a human or by the Layer 3 judge — same schema, and since the anchors are sent to the judge, literally the same text either way.

**Layer 3 — adversarial LLM-as-judge.** A separate model call receives the JD, a master-resume excerpt, and the generated output, with the Layer 2 rubric anchors inlined per dimension and the pass criterion stated outright (average ≥ 4.0, no dimension below 3). The pass/fail verdict is **derived in code** from the parsed scores via the rubric's `passes()` — the model's own verdict is retained separately as `model_verdict`, calibration data for whether the model applies the stated criterion, never a gate. N-run variance analysis computes mean, coefficient of variation, hallucination rate, and verdict flip rate, with alert thresholds sourced from the rubric so they cannot drift from the verdict (mean < 4.0, any per-dimension mean < 3, CoV > 20%, any hallucination, flips > 20%) and baseline delta tracking (keyword score dropping > 0.5 flags a prompt regression). The judge samples at temperature 0, so a verdict flip is the code-derived verdict crossing the rubric boundary between runs — score variance near the threshold; the remedy is investigating the entry, not the sampler.

**Golden dataset.** `evals/golden_dataset.json` commits a 5-entry manifest (JDs recovered verbatim from the application queue); the JD/reference files themselves are personal data resolved from the workspace at run time. Eval-generated documents save under an `EVAL` prefix so artifacts never overwrite real materials.

**Judge calibration.** The judge knows today's date (real dates aren't "future-dated"), sees the full master resume rather than a 6K-char truncation (truncation made the judge flag real-but-unseen claims as hallucinations — the same shared cap now applies on the CLI judge path too), and filters clean-bill notes ("no hallucinations detected") out of the hallucinations array. Flagged claims are persisted in run aggregates so an alert carries its evidence.

**Judge model split.** The judge can run on a different provider/model than the generator: config keys `judge_provider` / `judge_model`, env vars `JUDGE_LLM_PROVIDER` / `JUDGE_LLM_MODEL`. Env wins, per repo convention — including plain `LLM_PROVIDER`, which AKS secrets and CI export: wherever it is set, config `judge_provider` is silently ignored and only the `JUDGE_*` env vars actually split the judge. **Until a judge provider is configured, the judge is the generator's model — it grades its own output.** Results stamp the judge model that actually produced the scores, not the configured promise; the config-derived value appears only when every run errored.

**Provenance agreement.** Every eval generation runs through the production single-shot path, which writes a `generation_provenance` row — so each run joins the two hallucination checks, restricted to numeric claims, the only territory both cover (the provenance gate's claim regex sees only numbers; the judge sees everything, so its non-numeric findings are out of scope for the comparison, not disagreements). Five buckets per entry, reported as **raw counts** — 5 entries × N runs yields single-digit comparable events, and a percentage would flatter the sample: `both_flagged`, `both_clean`, `judge_only`, `provenance_only`, `no_record`. `no_record` means the comparison never happened — deliberately distinct from `both_clean`, because `record_run` swallows its own write failures. A freshness fence backs it: the provenance row's id is compared against a pre-generation read, so a stale row from an earlier generation of the same company/role can't stand in for this run's verdict, and a failed pre-read makes freshness unprovable — the run lands in `no_record` rather than trusting an unproven row. The buckets surface as the `Prov` column in the CLI dashboard and the `eval_provenance_agreement_count` gauge on the wallboard, where `no_record` gets its own red-at-≥1 stat.

**Synthetic fixtures.** `evals/fixtures/` is a two-entry *scaffold* (FX-01 clean, FX-02 corrupted), not a fixture corpus: no synthetic master resume is committed, nothing asserts catch rates, and nothing wires it into the runner. The planted-error corpus (8–12 error classes, each with its expected catch, reported x/N per class) is open work that needs a live judge — see `docs/evals-audit-2026-08-04.md`, repair 4.

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
