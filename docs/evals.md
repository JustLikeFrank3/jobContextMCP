# Eval Framework — Three Layers, LLM-as-Judge, CI Gate

The generation pipeline has a regression harness in [`evals/`](../evals/). The methodology and alert thresholds come from the July 2026 design doc, committed as [eval-framework.md](eval-framework.md) — its threshold values (CoV > 20%, flip > 20%, keyword delta < −0.5, N=5, smoke < 95% blocks release) are design judgments, not yet validated against data; where that doc and the code disagree, the code and this page are authoritative. Three layers, from cheap-and-deterministic to adversarial:

**Layer 1 — functional tool evals.** 24 declarative cases across all 12 domains (`evals/cases.py`) run through `tools.consolidated._run` — the exact dispatch path MCP clients hit — so parameter coercion, missing-parameter errors, and action routing are all under test. Cases are tagged (`smoke`, `read-only`, `write`, `error-handling`, `semantic`, `network`); the report carries pass rate and latency p50/p95, and **a smoke pass rate below 95% blocks release**. Smoke markers are code-emitted literals — exact strings the tools actually print, covering every reachable state (empty workspace, populated workspace, and filtered-empty where one exists) — so a passing gate means the tool answered, not merely that something non-empty came back. A replay test (`tests/test_evals.py`) re-checks every marker against recorded real responses, so a marker typo fails in pytest instead of first surfacing as a blocked deploy.

**Layer 2 — rubrics.** Resume (6 dimensions) and cover-letter (5 dimensions) scoring schemas with hard thresholds (resume: avg ≥ 4.0, no dimension < 3). Applied by a human or by the Layer 3 judge — same schema, and since the anchors are sent to the judge, literally the same text either way.

**Layer 3 — adversarial LLM-as-judge.** A separate model call receives the JD, a master-resume excerpt, and the generated output, with the Layer 2 rubric anchors inlined per dimension and the pass criterion stated outright (average ≥ 4.0, no dimension below 3). The pass/fail verdict is **derived in code** from the parsed scores via the rubric's `passes()` — the model's own verdict is retained separately as `model_verdict`, calibration data for whether the model applies the stated criterion, never a gate. N-run variance analysis computes mean, coefficient of variation, hallucination rate, and verdict flip rate, with alert thresholds sourced from the rubric so they cannot drift from the verdict (mean < 4.0, any per-dimension mean < 3, CoV > 20%, any hallucination, flips > 20%) and baseline delta tracking (keyword score dropping > 0.5 flags a prompt regression). The judge samples at temperature 0, so a verdict flip is the code-derived verdict crossing the rubric boundary between runs — score variance near the threshold; the remedy is investigating the entry, not the sampler.

**Golden dataset.** `evals/golden_dataset.json` commits a 5-entry manifest (JDs recovered verbatim from the application queue); the JD/reference files themselves are personal data resolved from the workspace at run time. Eval-generated documents save under an `EVAL` prefix so artifacts never overwrite real materials.

**Judge calibration.** The judge knows today's date (real dates aren't "future-dated"), sees the full master resume rather than a 6K-char truncation (truncation made the judge flag real-but-unseen claims as hallucinations — the same shared cap now applies on the CLI judge path too), and filters clean-bill notes ("no hallucinations detected") out of the hallucinations array. Flagged claims are persisted in run aggregates so an alert carries its evidence.

**Judge model split.** The judge can run on a different provider/model than the generator: config keys `judge_provider` / `judge_model`, env vars `JUDGE_LLM_PROVIDER` / `JUDGE_LLM_MODEL`. Env wins, per repo convention — including plain `LLM_PROVIDER`, which AKS secrets and CI export: wherever it is set, config `judge_provider` is silently ignored and only the `JUDGE_*` env vars actually split the judge. A cross-vendor judge carries its own key in `JUDGE_LLM_API_KEY` (falls back to `LLM_API_KEY`; the generator's key can't be shared because foundry prefers an explicit key over workload identity). In AKS all three `JUDGE_*` vars read optional keys from `jcmcp-app-secrets` — flipping the split is a secret edit and a restart, no manifest change, but run a reference-judging pass against the blind labels first so the new judge carries its own calibration table (§ below). **Until a judge provider is configured, the judge is the generator's model — it grades its own output.** Results stamp the judge model that actually produced the scores, not the configured promise; the config-derived value appears only when every run errored.

**Provenance agreement.** Every eval generation runs through the production single-shot path, which writes a `generation_provenance` row — so each run joins the two hallucination checks, restricted to numeric claims, the only territory both cover (the provenance gate's claim regex sees only numbers; the judge sees everything, so its non-numeric findings are out of scope for the comparison, not disagreements — but a **numeric** `judge_only` finding is squarely in scope and means the gate missed something, which is how the bare-integer gap below was found). Five buckets per entry, reported as **raw counts** — 5 entries × N runs yields single-digit comparable events, and a percentage would flatter the sample: `both_flagged`, `both_clean`, `judge_only`, `provenance_only`, `no_record`. `no_record` means the comparison never happened — deliberately distinct from `both_clean`, because `record_run` swallows its own write failures. A freshness fence backs it: the provenance row's id is compared against a pre-generation read, so a stale row from an earlier generation of the same company/role can't stand in for this run's verdict, and a failed pre-read makes freshness unprovable — the run lands in `no_record` rather than trusting an unproven row. The buckets surface as the `Prov` column in the CLI dashboard and the `eval_provenance_agreement_count` gauge on the wallboard, where `no_record` gets its own red-at-≥1 stat.

**Gate coverage: bare counts (fixed 2026-08-10).** Until this date the claim regex matched currency, percentages, magnitude suffixes (`15k`), multipliers (`3x`), comma-grouped numbers (`1,491`), and years — and **nothing matched an unadorned integer**. So the single commonest resume fabrication, an invented tool or test count, was never extracted and therefore never checked. Measured on the golden references: the gate reported GD-03, GD-04 and GD-05 completely clean while the judge named `931 passing tests` (master: 1,481), `277 tests`, and `77 MCP tools` (master: 85) in every run. Every one is a bare integer. The pattern `(?<![-.,\d])\b\d{2,}(?=\s+[A-Za-z])` closes it: the lookahead requires the integer to be *counting something*, which excludes contact headers (`305-490-1262` contributed three violations per document without it), and the lookbehind stops a trailing phone group qualifying merely because prose follows it. The clean control still flags zero and all nine pre-existing fixture detections are unchanged.

One class remains uncovered by design, because no regex reaches it: a number that is real, traceable, and *stated about the wrong thing* — GD-01's `sub-$0.10 per query` against a master that says the corpus indexes for under $0.10 in total. Membership testing cannot distinguish scope. That is judge territory, and the judge catches it.

**The suite measures shipped output, not first drafts (from 2026-08-10).** Since the single-shot path gained a correction pass, an eval generation that fabricates a number is re-drafted before it is saved, and the `generation_provenance` row records the verdict on the corrected text. That is the right thing to measure — it is what a real generation would produce — but it does mean `provenance_only` and `both_flagged` no longer report the generator's *raw* fabrication rate. The row's `revisions` column preserves that signal: `revisions=1` marks a run whose first draft was dirty, so raw-vs-shipped is a query rather than a lost measurement. Expect the buckets to shift toward `both_clean` and `judge_only` for reasons that are a fix, not a regression.

**Synthetic fixtures.** `evals/fixtures/` is a planted-error corpus built on a fully synthetic master resume (invented person, employers, numbers — nothing from real workspace data): one clean control whose every numeric claim is provenance-traceable, plus ten variants that are the control with exactly one surgical corruption each, documented in the manifest's `corruption_note`. `python -m evals fixtures -n 5` judges each fixture N times directly against the synthetic master (no generation involved). A fabrication counts as caught only when the judge's hallucinations array overlaps the planted claim; style classes count on the target dimension scoring below 3; any flag on the clean control is a false positive. Measured catch rates — judge `llama3.1:8b` (Ollama, cross-family from the qwen3 generator), N=5 per fixture, 2026-08-04:

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
| FX-10 | claim_double_counted | hallucination | not yet measured (added 2026-08-10) |

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

**Production-candidate judge (`claude-sonnet-5`).** Same reference-judging pass, same labels, same rubric and master excerpt, N=5 per entry, judge `claude-sonnet-5` via Anthropic's OpenAI-compatible endpoint (2026-08-05). **Configuration differs from the two tables above and that difference is load-bearing, not incidental**: this model rejects the `temperature` param outright (400 "deprecated for this model" — dropped, not tuned) and is a thinking model whose `max_tokens` budget covers reasoning before output, so every call in this pass was floored to `max_tokens=8000` rather than the `temperature=0.0` / cap-2000 configuration `llama3.1:8b` and `gpt-4.1-mini` ran under. A mixed-budget first attempt at this pass was discarded before scoring anything, specifically to avoid measuring six calls that reasoned inside 2000 tokens against nineteen that got bumped to 8000 mid-run:

| entry | human labels | judge means | hallucinations flagged |
|---|---|---|---|
| GD-01 | 5/5/**1**/5/5 | 3.2/3.8/**2.0**/4.0/5.0 | 5/5 |
| GD-02 | 5/5/**2**/5/4 | 3.8/4.0/**1.8**/3.8/3.6 | 5/5 |
| GD-03 | 5/5/**1**/5/4 | 3.6/4.0/**4.8**/4.8/3.2 | 1/5 |
| GD-04 | 5/5/**1**/5/4 | 3.6/3.2/**2.8**/4.0/4.0 | 5/5 |
| GD-05 | 3/3/4/3/4 | 2.4/2.0/3.0/2.6/3.6 | 5/5 |

Per-dimension MAE: keyword_coverage 1.28, relevance 1.20, **accuracy 1.56**, impact_language 0.76, ats_readiness 0.32 — accuracy MAE roughly halves versus both prior judges (3.2 for `llama3.1:8b`, 3.0 for `gpt-4.1-mini`).

The improvement is genuine calibration, not coincidental pessimism — `evals/calibrate.py` now persists the actual flagged claim strings (`hallucination_claims`), not just a count, and on GD-01/02/04/05 they consistently name the real conflicting numbers rather than generic complaints: "'931 passing tests' (master resume states 1,481 passing tests)", "'80 MCP tools across domains' ... master resume states 85 actions across 11 consolidated domain tools", "'52 tools' ... contradicts master resume's stated 85 actions", "Honcho long-term memory (technology never mentioned anywhere in master resume)", "'77 MCP tools' ... not 77 tools". These are the same tool-count and test-count conflicts the fixture corpus and the two prior calibration passes already established as real, cross-document contradictions — this judge names them by number on sight, every run, rather than needing them pointed out.

**GD-03 is the exception and it matters.** Hallucinations flagged only 1/5 runs there (a title claim and a project rename), and accuracy landed at 4.8 against a human label of 1 — the worst single-entry miss in this table, on par with the prior judges' blanket 5.0s. One entry out of five failing this way means the anti-correlation problem is reduced, not eliminated — this judge is calibrated on four of five entries in this sample, not proven calibrated in general.

> **Resolved 2026-08-10 — and the sentence above originally dismissed the answer.** It read "…a title claim and a project rename, *neither the real conflict*," on the assumption that GD-03 hid a numeric contradiction like the other four. It does not. Read directly against the master, **every claim in GD-03 is true and traceable**, including the `sub-$0.10` figure that GD-01 and GD-04 get wrong — GD-03 correctly says *indexing cost*, they say *per query*. The deterministic gate agrees: zero untraceable claims.
>
> What is wrong is structural. GD-03 lists the jobContext role under professional experience **and again** as a standalone project entry, restating the same `85 actions` / `1,481 tests` metrics, so one body of work reads as two. The master lists it once, and its projects section contains two other projects, not three. The human label of 1 is defensible; all three judges scored it 5.0 across 15 runs because each verifies claims one at a time and every individual claim passes. Provenance cannot see it either — the duplicated numbers are traceable *because they are real*.
>
> So this was never per-document blindness. It is a fabrication class no check covers and the corpus did not contain, now added as FX-10 (`claim_double_counted`). The dismissed "project rename" flag was the closest any judge got, and it was filed as noise.

Same claim discipline as the two tables above: N=5 per entry, five entries, one day, one rater's labels — evidence for flipping `JUDGE_LLM_PROVIDER` to `anthropic`, not proof the accuracy dimension is solved.

**Replication (2026-08-07).** The `claude-sonnet-5` pass was repeated two days later, same labels, same rubric, same master excerpt, N=5 — this time under the uniform `max_tokens=8000` the judge path now sets unconditionally rather than reaching by mid-run bump, so no call in this pass discovered its budget. 25/25 calls returned parseable JSON.

| entry | human labels | judge means | hallucinations flagged |
|---|---|---|---|
| GD-01 | 5/5/**1**/5/5 | 3.0/3.6/**2.0**/4.0/5.0 | 5/5 |
| GD-02 | 5/5/**2**/5/4 | 3.8/3.8/**2.0**/4.0/3.4 | 5/5 |
| GD-03 | 5/5/**1**/5/4 | 3.2/4.2/**5.0**/4.6/3.2 | 0/5 |
| GD-04 | 5/5/**1**/5/4 | 3.2/3.4/**2.4**/4.0/3.4 | 5/5 |
| GD-05 | 3/3/4/3/4 | 2.8/2.4/**3.0**/3.0/3.2 | 5/5 |

Per-dimension MAE: keyword_coverage 1.40, relevance 1.12, **accuracy 1.48**, impact_language 0.68, ats_readiness 0.56 — against 1.28 / 1.20 / **1.56** / 0.76 / 0.32 on 08-05. The largest single-cell drift across all 25 cells is 0.6 and most are ≤ 0.2; at N=5 one run differing by one point moves a mean by 0.2, so the typical drift is one or two run-points out of five. Two passes days apart put accuracy MAE at 1.56 and 1.48.

**GD-03's miss reproduced and got worse:** accuracy 4.8 → **5.0**, hallucinations 1/5 → **0/5**. The judge is now unanimously and silently wrong on that document. That entry alone contributes 4.0 of the 7.4 accuracy diff total — **54% of the accuracy MAE is one entry**, and excluding it the other four average 0.85. The single-entry failure named above is a stable property of this judge on this file, not sampling noise.

**The MAE conflates offset with disagreement, and only accuracy is disagreement.** On keyword_coverage, relevance, impact_language and ats_readiness every entry's judge mean sits at or below the human label, in both passes — so MAE equals |mean signed error| exactly on those four, which is the signature of a constant offset rather than a dispute. The judge also preserves the rater's ordering there: the rater scored GD-05 lowest on kw/rel/imp and the judge puts GD-05 lowest on all three. Different zero point, same ranking. Accuracy is the only dimension whose per-entry errors change sign (+1.0, 0.0, +4.0, +1.4, −1.0), i.e. the only one where judge and rater disagree about which document is worse — on exactly one of the five.

**GD-05 is a case where the label is the weaker artifact.** The rater gave it accuracy 4, the highest in the set; the judge scored 3.0 and flagged `'77 MCP tools' — master resume specifies 85 actions across 11 consolidated domain tools` in 5/5 runs, the same checkable cross-document contradiction class the fixture corpus established as real. Roughly 1.0 of the 7.4 accuracy total is therefore the judge being charged for a catch the blind rater missed. The label stands as recorded — amending it after seeing judge output would destroy the blind protocol that makes it worth anything — but the number should be read knowing this.

**Reading `hallucination_claims` counts.** `all_hallucinations()` (`evals/calibrate.py:39-46`) deduplicates by exact string, so five runs phrasing the same claim four ways yield four entries. GD-01's twenty strings are roughly five distinct fabrications; GD-02 ≈ 10, GD-04 ≈ 4, GD-05 = 1. The list length is a phrasing count, not a fabrication count.

**Cross-judge confound, resolved (`gpt-4.1-mini` re-run at 8000, 2026-08-07).** The uniform `max_tokens=8000` applies to every judge call now, but the `llama3.1:8b` and `gpt-4.1-mini` tables were both produced beforehand at cap 2000 — so "accuracy MAE roughly halves versus both prior judges" varied model and token budget together. `gpt-4.1-mini` was re-run at 8000 against the same labels to separate them:

| entry | human labels | judge means | hallucinations flagged |
|---|---|---|---|
| GD-01 | 5/5/**1**/5/5 | 5.0/5.0/**5.0**/4.6/5.0 | 0/5 |
| GD-02 | 5/5/**2**/5/4 | 5.0/4.4/**5.0**/4.0/5.0 | 0/5 |
| GD-03 | 5/5/**1**/5/4 | 5.0/5.0/**5.0**/4.0/5.0 | 0/5 |
| GD-04 | 5/5/**1**/5/4 | 5.0/5.0/**5.0**/4.0/5.0 | 0/5 |
| GD-05 | 3/3/4/3/4 | 4.0/4.0/**5.0**/4.0/5.0 | 0/5 |

Per-dimension MAE: keyword_coverage 0.20, relevance 0.32, **accuracy 3.2**, impact_language 0.88, ats_readiness 0.80. **The budget is not the explanation.** At 8000 `gpt-4.1-mini`'s accuracy MAE is 3.2 against 3.0 at cap 2000 — marginally worse, not better. `claude-sonnet-5`'s 1.48/1.56 is therefore a property of the model, and the halving can be quoted as a model comparison.

Two sharper readings follow from the same table. **On accuracy this judge is a constant.** It returns 5.0 on all five entries, so it does not rank them at all — a constant function carries no information, which is a stronger statement than "anti-correlated." Every accuracy error is positive (+4.0, +3.0, +4.0, +4.0, +1.0); it never scores below the rater. And **the one catch that ever existed does not reproduce**: the cap-2000 table credits it with flagging GD-04's tool-count and test-count contradiction in 3/5 runs at accuracy 4, the only cross-document numeric catch by any judge at production document sizes; at 8000 it is accuracy 5.0 unanimously with 0/5 flags, and zero hallucinations flagged across all 25 runs. The "partial, inconsistent detection" softening recorded above for this judge is in doubt on this evidence.

One limit on that last point: the cap-2000 table predates `evals/calibrate.py` and was tabulated by hand from the `python -m evals judge` path, so 2000 → 8000 spans a tooling change as well as a cap change. That is enough to stop the claim "more budget destroyed the catch" being asserted as mechanism. It is not enough to rescue the budget explanation, since under no reading is `gpt-4.1-mini` at 8000 better than at 2000 — which is the only question the re-run was asked to settle.


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
