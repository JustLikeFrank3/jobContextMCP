# Eval Framework — Three Layers, LLM-as-Judge, CI Gate

The generation pipeline has a regression harness in [`evals/`](../evals/). Three layers, from cheap-and-deterministic to adversarial:

**Layer 1 — functional tool evals.** 24 declarative cases across all 12 domains (`evals/cases.py`) run through `tools.consolidated._run` — the exact dispatch path MCP clients hit — so parameter coercion, missing-parameter errors, and action routing are all under test. Cases are tagged (`smoke`, `read-only`, `write`, `error-handling`, `semantic`, `network`); the report carries pass rate and latency p50/p95, and **a smoke pass rate below 95% blocks release**. Smoke markers are code-emitted literals — exact strings the tools actually print, covering every reachable state (empty workspace, populated workspace, and filtered-empty where one exists) — so a passing gate means the tool answered, not merely that something non-empty came back. A replay test (`tests/test_evals.py`) re-checks every marker against recorded real responses, so a marker typo fails in pytest instead of first surfacing as a blocked deploy.

**Layer 2 — rubrics.** Resume (6 dimensions) and cover-letter (5 dimensions) scoring schemas with hard thresholds (resume: avg ≥ 4.0, no dimension < 3). Applied by a human or by the Layer 3 judge — same schema, and since the anchors are sent to the judge, literally the same text either way.

**Layer 3 — adversarial LLM-as-judge.** A separate model call receives the JD, a master-resume excerpt, and the generated output, with the Layer 2 rubric anchors inlined per dimension and the pass criterion stated outright (average ≥ 4.0, no dimension below 3). The pass/fail verdict is **derived in code** from the parsed scores via the rubric's `passes()` — the model's own verdict is retained separately as `model_verdict`, calibration data for whether the model applies the stated criterion, never a gate. N-run variance analysis computes mean, coefficient of variation, hallucination rate, and verdict flip rate, with alert thresholds sourced from the rubric so they cannot drift from the verdict (mean < 4.0, any per-dimension mean < 3, CoV > 20%, any hallucination, flips > 20%) and baseline delta tracking (keyword score dropping > 0.5 flags a prompt regression). The judge samples at temperature 0, so a verdict flip is the code-derived verdict crossing the rubric boundary between runs — score variance near the threshold; the remedy is investigating the entry, not the sampler.

**Golden dataset.** `evals/golden_dataset.json` commits a 5-entry manifest (JDs recovered verbatim from the application queue); the JD/reference files themselves are personal data resolved from the workspace at run time. Eval-generated documents save under an `EVAL` prefix so artifacts never overwrite real materials.

**Judge calibration.** The judge knows today's date (real dates aren't "future-dated"), sees the full master resume rather than a 6K-char truncation (truncation made the judge flag real-but-unseen claims as hallucinations — the same shared cap now applies on the CLI judge path too), and filters clean-bill notes ("no hallucinations detected") out of the hallucinations array. Flagged claims are persisted in run aggregates so an alert carries its evidence.

**Judge model split.** The judge can run on a different provider/model than the generator: config keys `judge_provider` / `judge_model`, env vars `JUDGE_LLM_PROVIDER` / `JUDGE_LLM_MODEL`. Env wins, per repo convention — including plain `LLM_PROVIDER`, which AKS secrets and CI export: wherever it is set, config `judge_provider` is silently ignored and only the `JUDGE_*` env vars actually split the judge. **Until a judge provider is configured, the judge is the generator's model — it grades its own output.** Results stamp the judge model that actually produced the scores, not the configured promise; the config-derived value appears only when every run errored.

**Provenance agreement.** Every eval generation runs through the production single-shot path, which writes a `generation_provenance` row — so each run joins the two hallucination checks, restricted to numeric claims, the only territory both cover (the provenance gate's claim regex sees only numbers; the judge sees everything, so its non-numeric findings are out of scope for the comparison, not disagreements). Five buckets per entry, reported as **raw counts** — 5 entries × N runs yields single-digit comparable events, and a percentage would flatter the sample: `both_flagged`, `both_clean`, `judge_only`, `provenance_only`, `no_record`. `no_record` means the comparison never happened — deliberately distinct from `both_clean`, because `record_run` swallows its own write failures. A freshness fence backs it: the provenance row's id is compared against a pre-generation read, so a stale row from an earlier generation of the same company/role can't stand in for this run's verdict, and a failed pre-read makes freshness unprovable — the run lands in `no_record` rather than trusting an unproven row. The buckets surface as the `Prov` column in the CLI dashboard and the `eval_provenance_agreement_count` gauge on the wallboard, where `no_record` gets its own red-at-≥1 stat.

**Synthetic fixtures.** `evals/fixtures/` is a planted-error corpus built on a fully synthetic master resume (invented person, employers, numbers — nothing from real workspace data): one clean control whose every numeric claim is provenance-traceable, plus nine variants that are the control with exactly one surgical corruption each, documented in the manifest's `corruption_note`. `python -m evals fixtures -n 5` judges each fixture N times directly against the synthetic master (no generation involved). A fabrication counts as caught only when the judge's hallucinations array overlaps the planted claim; style classes count on the target dimension scoring below 3; any flag on the clean control is a false positive. Measured catch rates — judge `llama3.1:8b` (Ollama, cross-family from the qwen3 generator), N=5 per fixture, 2026-08-04:

| id | class | signal | result |
|---|---|---|---|
| FX-00 | clean_baseline | clean control | **0/5 false positives** |
| FX-01 | metric_changed (37%→52%) | hallucination | caught 5/5 |
| FX-02 | metric_invented (+$2M savings) | hallucination | caught 0/5 |
| FX-03 | employer_fabricated | hallucination | caught 1/5 |
| FX-04 | title_inflated (Senior→Principal) | hallucination | caught 0/5 |
| FX-05 | date_shifted (2021→2019) | hallucination | caught 5/5 |
| FX-06 | credential_invented (AWS cert) | hallucination | caught 0/5 |
| FX-07 | jd_parrot (JD-only metric) | hallucination | caught 5/5 |
| FX-08 | voice_drift | dimension (impact_language) | caught 5/5 |
| FX-09 | keyword_stuffing | dimension (ats_readiness) | caught 0/5 |

Two findings, reported as measured. First, this judge reliably catches **contradictions** of the master (changed metric, shifted date, parroted JD metric) but almost never catches **unsupported additions** (invented metric, invented credential, inflated title, fabricated employer: 1/20 combined) — additions read as plausible resume content unless they collide with something the master states. Crossed against the provenance gate's per-fixture coverage, that yields a coverage map: the judge's worst miss (invented $2M, 0/5) is provenance's cleanest catch ($2M is numeric and untraceable), while provenance's blind spots are the judge's 5/5s — the JD-parroted metric (provenance is doubly blind there: by policy, the JD legitimately sources its own text, and by regex form, spelled-out magnitudes like "4 billion" don't match the claim pattern) and the shifted date. The harness-wide blind spot is **non-numeric additions**: fabricated employers, inflated titles, and invented credentials pass both detectors. Second, every corrupted fixture still *passed* on aggregate scores (means 4.2–4.8): fabrication shows up in the hallucinations array or not at all, never in the average — which is why the harness alerts on any hallucination rather than on score thresholds alone. Keyword stuffing not moving `ats_readiness` below 3 (0/5) is a known soft spot of this judge model at this rubric. Catch rates are properties of the named judge model on the named date, not of the harness; a judge model change invalidates this table until re-run.

**First split-judge suite run.** Verified live 2026-08-04 (generator `qwen3-jobcontext`, judge `llama3.1:8b` via the env split, N=5): the results payload stamps `judge_model: llama3.1:8b` / `judge_provider: ollama` — the model that scored, not the generator — and `no_record` was 0 across every run. One judge call in 25 (GD-05, run 1) returned prose instead of JSON after both parse attempts; the runner recorded the error string and aggregated the 4 completed runs rather than fabricating a score, so that entry's provenance buckets sum to 4 by design. On the freshly generated outputs, provenance flagged untraceable numeric claims in four of five entries (`provenance_only` per entry: 4, 0, 4, 5, 3) while the judge's accuracy means sat at 4.8–5.0 — the fixture table's addition-blindness, observed live.

**Human-label calibration.** The golden five references carry blind human labels (committed in `golden_dataset.json`: single rater, one sitting, 2026-08-04, scored before any judge output existed for those files). The same judge then scored each reference file directly — the `python -m evals judge` path, same master excerpt and rubric — at N=5 (judge `llama3.1:8b`, 2026-08-04). Raw numbers, human labels vs judge means (kw/rel/acc/imp/ats):

| entry | human labels | judge means | failed judge calls |
|---|---|---|---|
| GD-01 | 5/5/**1**/5/5 | 5.0/4.0/**5.0**/5.0/5.0 | 0/5 |
| GD-02 | 5/5/**2**/5/4 | 4.0/5.0/**5.0**/5.0/5.0 | 0/5 |
| GD-03 | 5/5/**1**/5/4 | 4.0/4.0/**5.0**/4.0/5.0 | 4/5 (means are n=1) |
| GD-04 | 5/5/**1**/5/4 | 4.0/5.0/**5.0**/5.0/5.0 | 0/5 |
| GD-05 | 3/3/4/3/4 | 4.0/5.0/5.0/4.0/5.0 | 0/5 |

Per-dimension MAE (|human label − judge mean|, across entries): keyword_coverage 0.8, relevance 0.8, **accuracy 3.2**, impact_language 0.4, ats_readiness 0.8. On every dimension except accuracy the judge sits within one point of the rater; on accuracy it is anti-correlated with the labels — 5.0 with **zero hallucinations flagged in all 21 successful runs**, against human 1s and 2s grounded in cross-document arithmetic (the references contradict each other on tool and test counts, so at most one can match the master).

A prediction was pre-registered before these numbers existed (PR #204): the judge should flag the number conflicts and land accuracy "in the 2–3 range, directionally with the owner's 1s but softer," with the explicit falsification clause that accuracy 4–5 would mean "something else is wrong." **The prediction missed on its own falsification clause.** The suspected cause — the master excerpt cap hiding the contradicted numbers — is ruled out: the cap is 32,000 chars, the master is 29,831, and the contradicted claims ("80 MCP tools") are verbatim in the judged context. What actually differs from the fixture corpus is scale: fixtures pit ~3KB outputs against a 6,345-char synthetic master (contradictions caught 5/5); the references are 8–9KB documents against the ~30KB real master (contradictions caught 0/21). Stated as measured: **this judge's contradiction-catching does not survive production-scale documents** — the fixture catch rates are ceiling numbers, and at real document sizes numeric-hallucination detection is effectively provenance-only. Master size and output size are confounded here; separating them needs a scaled fixture series, not attempted in this pass.

Two further calibration notes. GD-03 lost 4 of 5 judge calls to prose-instead-of-JSON with an *identical* opening sentence each time — JSON non-compliance is content-dependent, not random (the suite's overall rate was 1/25), so per-entry failure counts belong next to any mean derived from the survivors. And the claim discipline for all of the above: these labels calibrate the judge — they do not validate suite scores on newly generated outputs; they are a single rater's blind pass, and at five entries any pattern beyond the accuracy split is consistent with expectation at a sample size that cannot distinguish it from chance. All numbers above are properties of `llama3.1:8b` on 2026-08-04.

**Production-candidate judge (`gpt-4.1-mini`).** The same reference-judging pass, same labels, same rubric and master excerpt, N=5 per entry, judge `gpt-4.1-mini` via Azure AI Foundry (2026-08-04) — run before any decision to point `JUDGE_LLM_PROVIDER` at it, so the production candidate carries its own table rather than inheriting `llama3.1:8b`'s calibration:

| entry | human labels | judge means | failed judge calls |
|---|---|---|---|
| GD-01 | 5/5/**1**/5/5 | 5.0/5.0/**5.0**/4.0/5.0 | 0/5 |
| GD-02 | 5/5/**2**/5/4 | 5.0/4.0/**5.0**/4.0/5.0 | 0/5 |
| GD-03 | 5/5/**1**/5/4 | 5.0/5.0/**5.0**/4.0/5.0 | 0/5 |
| GD-04 | 5/5/**1**/5/4 | 5.0/5.0/**4.0**/4.0/5.0 | 0/5 |
| GD-05 | 3/3/4/3/4 | 4.2/4.0/5.0/4.0/5.0 | 0/5 |

Per-dimension MAE: keyword_coverage 0.24, relevance 0.4, **accuracy 3.0**, impact_language 1.0, ats_readiness 0.8. Three differences from `llama3.1:8b` are real and one non-difference matters:

- **JSON compliance: 25/25.** Zero prose failures, including on GD-03 where `llama3.1:8b` failed 4/5 with an identical opening. The content-dependent non-compliance is a property of the local model, not of the rubric prompt.
- **It caught the genuine cross-document contradiction — partially.** On GD-04, `gpt-4.1-mini` flagged the "80+ MCP tools … 931 passing tests" claim against the master's 85 actions / 1,481 tests as a hallucination in 3/5 runs and scored accuracy 4 in 5/5. That is the first cross-document numeric catch by any judge at production document sizes (0/21 for `llama3.1:8b`). The scale finding softens from "effectively provenance-only" to "partial, inconsistent detection" for this judge.
- **Determinism.** Per-entry score vectors were identical across all 5 runs for GD-01 through GD-04 (GD-05 varied on one dimension in one run). N-run variance against this judge measures generator drift, not judge noise.
- **The accuracy anti-correlation stands.** MAE 3.0 vs 3.2 — the catch shows up as one docked point on one entry, while the labels say 1s and 2s across four entries. GD-01, GD-02, GD-03 contain the same class of conflict and scored accuracy 5.0 with zero flags in 15/15 runs. A judge that finds the identical contradiction on one document and misses it on three others is not calibrated on this dimension; it is merely no longer blind.

Same claim discipline: N=5 per entry, five entries, one day, one rater's labels. These numbers earn `gpt-4.1-mini` consideration as the judge split target, not a conclusion that accuracy scoring is solved.


## Running the evals

```bash
python -m evals layer1 --tags smoke          # functional cases against the active workspace
python -m evals layer1 --verbose             # all non-network, non-write cases
python -m evals judge --jd jd.txt --output resume.txt -n 5
python -m evals fixtures -n 5                # planted-error corpus against the synthetic master
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
