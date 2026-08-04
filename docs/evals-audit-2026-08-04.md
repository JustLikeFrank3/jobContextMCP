# Eval harness — audit, repair plan, and critique (2026-08-04)

Working document. Carries the full context needed to pick up the eval-harness
repairs in a fresh session: what the harness actually does today (audited
against `c482b0d`), the repair plan, and a pressure test of that plan against
the code.

Every claim below is cited `file:line`. Where something does not exist, it
says so explicitly — the absences are the useful part.

---

## Status as of this branch (2026-08-04, post-repair)

The audit body below is the historical record of `c482b0d` and is left as
written. The branch has since landed the repairs:

- **Closed:** repair 2 (rubric anchors sent, pass criterion stated,
  code-derived verdict, `model_verdict` retained), repair 3 (numeric
  provenance agreement with `no_record` + freshness fence, raw counts,
  wallboard panels), repair 5 (CLI truncation routed through the shared
  cap), the Layer 1 hardening from "Missing from the plan entirely" (smoke
  markers are now code-emitted literals over every reachable state, with a
  recorded-response replay test), and the threshold alignment the two-bars
  critique demanded (`MEAN_ALERT` and the dimension floor are sourced from
  the rubric).
- **Configured but not enabled in prod:** repair 1 — judge provider/model
  routing works and is tested per branch, but no `JUDGE_LLM_PROVIDER` is set
  in prod/CI, so **the judge is still the generator's model until Frank
  picks one**.
- **Open:** repair 4 (planted-error corpus — the committed fixtures are a
  2-entry scaffold) and repair 6 (hand-labeled golden five — needs the
  workspace machine).

---

## Status

- **Audited commit:** `c482b0d` (main).
- **Branch:** `claude/eval-harness-audit-jmhl8m` — at audit time, no commits
  beyond main other than this document and no harness code changed; the
  repairs landed afterwards (see "Status as of this branch" above).
- **Baseline:** 7 commits 2026-07-29 → 2026-07-30, +2,848 / −172 across 29
  files; 1,611 lines in `evals/`.

| Hash | Date | Message |
|---|---|---|
| `fb556b0` | 07-29 16:25 | three-layer eval framework — tool evals, rubrics, LLM-as-judge |
| `957bb70` | 07-29 16:47 | CI smoke gate, metrics bridge, and wallboard dashboard |
| `6e1a6f0` | 07-29 17:09 | recover golden JDs from application queue; read back generated docs |
| `d1ccd6d` | 07-29 17:21 | persist the flagged hallucination claims in run aggregates |
| `0545a2c` | 07-29 18:12 | calibrate the judge — date context, full master, clean-bill filter |
| `2aa33e3` | 07-29 19:06 | server-side nightly runs via the control plane |
| `9d2f700` | 07-30 18:42 | honest last-run gauges across restarts + prod-scoped wallboard |

`0776a64` (07-30) later added TC-023/TC-024 alongside the certification tool.

---

## Part 1 — What the harness actually is

### The judge

One model call. `evals/judge.py:138-176`.

- **Model:** `get_llm_client(task="eval_judge")` at `evals/judge.py:158`. The
  `task` argument is accepted at `lib/config.py:395` and **never read** in the
  function body (`:396-478`). It resolves the same provider/model as
  generation (`tools/generate.py:128,137`). In prod both are Azure Foundry
  `gpt-4.1-mini`. **The model grades its own output.**
- **Sampling:** `temperature=0.0` (`evals/judge.py:169`) and nothing else. No
  `max_tokens`, `top_p`, or `seed`. Note `temperature` is in
  `lib/openai_calls.py:62` `_DROPPABLE_PARAMS` — a 400 naming it silently
  retries without it.
- **Scale:** five dimensions, integers 1–5 (`evals/judge.py:21-23`):
  `keyword_coverage`, `relevance`, `accuracy`, `impact_language`,
  `ats_readiness`. The prompt says only "Score the output on each dimension
  1-5" (`:44`) — **no per-point anchors are sent**. The anchors exist at
  `evals/rubrics.py:11-24` and are never imported by production code.
- **Verdict:** requested at `evals/judge.py:48` with **no pass/fail
  criterion**. The model decides what "pass" means.
- **Parsing:** `parse_judge_json` (`:99-135`) strips `<think>` blocks and code
  fences, takes the outermost `{…}`, validates all five dimensions in 1–5
  (`:119-121`) and verdict in `pass`/`fail` (`:122-124`), filters clean-bill
  notes via `_CLEAN_BILL` (`:96,128`).
- **On parse failure:** one retry with **byte-identical messages at
  temperature 0** (`:144,166-175`), then `ValueError`. `evals/runner.py:149-150`
  records the failure per run and aggregates from whatever parsed.

### "Adversarial"

It is one sentence in a system prompt (`evals/judge.py:26-27`). **Not
present:** critic pass, pairwise comparison, injected negative examples,
second model, ensemble, debate. `verdict_flip_rate` (`evals/variance.py:34-39`)
compares the same judge across runs — a repeat measure, not an adversary.

### N-run variance

- **N = 5**, defaulted at `evals/runner.py:130,161`, `evals/__main__.py:131,135`,
  `evals/work.py:45` and `transport/http/routes/evals.py:57` (last two clamped 1–10).
- **Statistic:** sample stdev ÷ mean × 100 over per-run means
  (`evals/variance.py:24-31,105`), plus per-dimension stdev (`:92-98`),
  hallucination rate (`:106`), verdict flip rate (`:107`).
- **Generation temperature is 0.3** (`tools/generate.py:1249,1329`) and
  `evals/runner.py:145-148` regenerates inside the N loop. **The headline CoV
  is dominated by generation variance, not judge variance.**

### Hallucination detection vs. the provenance gate

The eval harness has no detector — it is the judge's self-reported
`hallucinations` list, rate-aggregated at `evals/variance.py:106`, surfaced as
an alert string (`:62-65`) and a gauge. Nothing blocks.

| | provenance gate | eval judge |
|---|---|---|
| Claim types | numeric only — %, $, k/m/b, `Nx`, comma-grouped, years (`lib/provenance.py:35-46`) | any claim, model's discretion (`evals/judge.py:44-46`) |
| Sources | full prompt (single-shot, `tools/generate.py:1188`) or master + stories + JD + RAG chunks (agent, `tools/langgraph_pipeline.py:212-219`) | master truncated to 32,000 chars + JD only (`evals/runner.py:121-124,142`) |
| Method | deterministic regex + normalized set membership | LLM self-report |
| Consequence | blocks in the agent path (`tools/langgraph_pipeline.py:407-436`), records in single-shot (`tools/generate.py:1173-1175`) | alert string + gauge |

Neither is a superset. **The eval suite generates through the single-shot path
(`evals/runner.py:100-109`), so `_provenance_note` writes a
`generation_provenance` row for every eval generation — and the harness reads
none of it.** `evals/runner.py:113-115` checks only that the status starts with
`✓` and ignores the `⚠` provenance marker in the same string.

### Golden set

No labels. `evals/golden_dataset.json` commits a 5-entry manifest;
`GoldenEntry.reference_file`, `.archetype`, `.eval_signal` (`evals/golden.py:22-25`)
are **read by nothing**. The manifest advertises "(JD, 5/5 reference output)
pairs" — the reference-output half is inert. JD and reference files are
personal data resolved from the workspace at run time (`evals/golden.py:1-7,51-60`),
not committed. GD-02 is a condensed JD, not the full posting.

Scores are compared against fixed literals (`evals/variance.py:19-21`) and the
previous run's own scores (`evals/runner.py:192-195,219-233`). Self-referential
drift tracking, no ground truth.

### CI smoke gate

- **Workflow:** `.github/workflows/deploy.yml:57-58`.
- **Triggers:** push to `qa`/`main` only, plus `workflow_dispatch` (`:3-14`).
  **No `pull_request` trigger — it cannot block a merge**, only the deploy of
  an already-merged commit.
- **Blocks:** `build-and-deploy` and `build-and-deploy-qa` both `needs: test`
  (`:145,:203`). Enforcing code is `scripts/ci_smoke_gate.py:66-71`.
- **Subset only:** blocks on smoke-tagged cases, and `smoke_pass_rate()`
  returns `1.0` when no smoke case is present (`evals/layer1.py:49-51`) —
  fail-open.
- **Runs against fixtures.** Throwaway `tempfile.mkdtemp` workspace
  (`scripts/ci_smoke_gate.py:27-54`), network-tagged case excluded. **No LLM
  call.** The test job has `LLM_PROVIDER`/`FOUNDRY_ENDPOINT` (`deploy.yml:24-27`)
  but **no `LLM_API_KEY` and no `azure/login`** — no credential exists there.
- **~3 seconds, $0 per run.** No retry, no timeout, no flake handling.
- **Has never failed a build.** Every `deploy.yml` run since the gate landed
  (first `30492893567`, 07-29T21:34) is green at that step. The only two failed
  runs (`30722926061`, `30722932656`, 08-01) failed at the `badges` job's
  "Commit badge changes if any" step, with the gate green in both.

### Test coverage

48 tests, all in `tests/test_evals.py` — the only file importing `evals`.
**The judge is mocked everywhere.** `_fake_client` at `:196-206`; conftest's
autouse fixture stubs `lib.config.get_llm_client` to `(None, None)`
(`tests/conftest.py:216`); no `live_llm` markers anywhere in the file.

Uncovered: `evals/runner.py:89-115` `default_generate` (the real generation
path) and `:121-124` `_master_excerpt` — every runner test injects
`generate_fn`/`judge_fn`.

### Has it run for real

Yes, a few manual local runs, evidenced only by commit prose and one screenshot.

- `fb556b0`: judge run N=3 on qwen3 caught a planted hallucination 3/3 (that
  fixture is not in the repo).
- `0545a2c`: the first n=5 run produced **false hallucination flags on every
  golden entry** — three harness defects, fixed the same night.
- `9d2f700`: verified against live Prometheus that **no `eval_*` series existed
  on the pods while the wallboard displayed values**; qa gauges were leaking
  into prod via `max()`.

Not present in the tree: `evals/results/` (gitignored, `.gitignore:106-107`),
any `eval_results.json`, any `eval_runs/`, **any DB table or migration**
(`lib/db.py` contains no `eval`). `eval_*` are in-process gauges only
(`lib/metrics.py:49-58`).

⚠ `docs/images/wallboard/kiosk-evals.png` (committed `a97f892`, 07-30) is the
**pre-fix ghost render** — 80% hallucinations, 40% flips, 5 alerts — and is
linked from `docs/evals.md`. Re-shoot it, caption it, or use it deliberately as
the exhibit.

⚠ A nightly where all five entries fail to find their JD records itself as
**succeeded** — `evals/work.py:52-60` returns errors as artifacts rather than
raising. Green ≠ ran. Check `entries_scored` on a real work row.

---

## Part 2 — Repair plan, with the critique inline

Ordering constraints, which the plan already satisfies:
**2 before 4 and 6** (anchors change what a catch and a label mean) and
**5 before 6** (labels must not be compared against a truncated judge).
The risk is dropping 5 for time because it is only ten lines.

### 1. Split the judge model from the generator

**Plan:** read `task` in `get_llm_client`; add judge provider/deployment keys
falling back to the default client; prefer cross-family over cross-size;
record the judge model id in the results payload.

**Watch for:**

- `tools/fitment.py:259` and `tools/certification.py:637` **already pass**
  `task="assessment"` / `task="certification"`, currently ignored. A generic
  per-task lookup silently changes their provider resolution. Restrict to an
  allowlist or to `eval_judge` only.
- `lib/config.py:372-375` requires `llm_generation_status()` to stay in
  lockstep with `get_llm_client()`. `evals/runner.py:167-169` stamps
  `SuiteResult.provider` from that function — so every results payload will
  report the **generator's** provider. The judge model id must be a **new
  field**; `evals/ingest.py:29-54` and both Grafana dashboards carry no such
  label today.
- Cross-vendor is cheap: `lib/config.py:424-433` already wires Anthropic via
  the OpenAI-compatible endpoint. Config change, not new client code.
- It ships untested unless you add a `live_llm`-marked test — conftest's stub
  (`tests/conftest.py:216`) already accepts `task`, so nothing breaks and
  nothing covers the branch.
- `create_chat_completion` holds a process-wide lock with interval spacing
  (`lib/openai_calls.py:88-102`). A second provider gets no separate rate
  budget; the nightly's 50 calls stay serialized.

### 2. Send the rubric anchors, and define pass/fail

**Plan:** render `RESUME_RUBRIC` anchors inline per dimension; state the
verdict criterion from `THRESHOLDS`; re-run the golden five and record the
before/after.

**Watch for:**

- `RESUME_RUBRIC` has six dimensions, `JUDGE_DIMENSIONS` has five —
  `format_compliance` is excluded on purpose (`evals/judge.py:19-20`). Filter,
  or you request a score `parse_judge_json` discards.
- **Two pass bars.** `THRESHOLDS["resume"].min_avg = 4.0`
  (`evals/rubrics.py:47`) vs `MEAN_ALERT = 3.8` (`evals/variance.py:19`). Put
  4.0 in the prompt and a 3.9 document is `verdict: "fail"` with no mean alert
  — the wallboard's two panels disagree by construction. Pick one or state why
  they differ. Today nobody has to defend the gap because the verdict is
  undefined; defining it creates the contradiction.
- **Stronger option:** derive the verdict in code from the parsed scores.
  Otherwise `verdict_flip_rate` measures the model's ability to average five
  integers.
- "Re-run the golden five" only works on the machine holding the workspace
  (`evals/golden.py:1-7`), and against whatever provider is configured there.
  Name the judge model that produced any before/after number.

### 3. Join the provenance verdict into the eval results

**Plan:** capture the provenance verdict per run onto `EntryResult`; compute
agreement (both flagged / both clean / judge-only / provenance-only); emit as a
gauge.

**Watch for:**

- Mechanics are fine: `lib.provenance.latest_run(company=..., role=...)`
  (`:178-180`) filters by company/role, `ORDER BY id DESC LIMIT 1`, and
  `run_entry` already holds both (`evals/runner.py:99-109`). Call it right
  after each generation.
- **Two silent-degradation paths.** `_provenance_note` swallows every
  exception and returns `"Provenance: ⚠ check skipped — …"`
  (`tools/generate.py:1200-1201`); `record_run` swallows everything with a bare
  `except: pass` (`lib/provenance.py:173-174`). Distinguish "both clean" from
  "no provenance record" or the agreement rate covers an unstated subset.
- **The judge-only cell is misread in the plan.** Its dominant population will
  be **non-numeric** claims — fabricated titles, employers, degrees — which
  `_CLAIM_RE` (`lib/provenance.py:35-46`) cannot see by design. Those are not
  disagreements, they are out of scope. **Restrict the comparison to numeric
  claims**: run `provenance.extract_claims()` over the judge's flagged strings
  and compare only the subset yielding a numeric token. That is the only place
  the two checks answer the same question.
- Power: 5 entries × N=5 = 25 document-runs, then the numeric subset of that.
  Expect single-digit comparable events. **Report raw counts, not a
  percentage.**

### 4. Commit a planted-error fixture set

**Plan:** 8–12 corrupted outputs covering fabricated metric, fabricated
employer/title, date drift, voice drift, keyword stuffing, RAG-only claim; each
carrying its expected catch; report catch rate per class.

**Watch for:**

- **The corpus is the work.** Fixtures cannot be derived from the golden five
  — those outputs are personal data and absent from the repo. You need a
  synthetic master resume, JD, and clean baseline **committed first**, or the
  judge has no source to check traceability against and every fixture flags.
- **Two classes will not work against the asserted mechanism.** The judge's
  `hallucinations` list is scoped to untraceable claims
  (`evals/judge.py:44-46`). Voice drift and keyword stuffing surface, if at
  all, as low `impact_language` / `ats_readiness`. Assert per-signal: hard
  assertion for the four fabrication classes, reported-only for the two style
  classes (which need repair 6's baseline to mean anything).
- **It cannot run in the existing CI gate** — no `LLM_API_KEY`, no Azure login
  in the test job (`deploy.yml:32-58`). Adding them takes the gate from
  $0 / 3s to real cost on every push to qa and main. Treat catch rate as a
  nightly/manual artifact.
- One run per fixture is noise. Run each N times, report x/N per class.
- Wiring fixtures into the nightly needs a second work-item shape or an
  `inputs` flag — `run_evals_executor` calls `run_suite(load_golden())`
  (`evals/work.py:41-50`).

### 5. Fix the CLI truncation

**Plan:** route `evals/__main__.py:43,47` through `_master_excerpt`; revisit
`max_chars = 32000`.

**Watch for:** not a straight substitution — `_master_excerpt`
(`evals/runner.py:121-124`) takes no file argument while `__main__` supports
`--master FILE`. Apply the shared cap on both branches. `max_chars=32000` has a
default no caller overrides, and its comment (`:118-120`) justifies it against
qwen3's 40K context while prod judges on `gpt-4.1-mini` — re-derive it or call
it a floor.

**This is a hard dependency of repair 6**, not optional cleanup.

### 6. Label the golden five

**Plan:** hand-score the five reference outputs on all five dimensions using
the repair-2 anchors, before looking at judge output; store in the manifest;
report per-dimension MAE.

**Watch for:**

- **The labels do not validate the wallboard.** They attach to
  `reference_file`; the suite judges *newly generated* outputs
  (`evals/runner.py:145-148`). Claimable: "I calibrated the judge against five
  hand-scored documents." Not claimable: "I validated the eval scores."
- **The pre-registered expectation is a trap.** Predicting disagreement on
  `impact_language`/`relevance` and agreement on `keyword_coverage` is good
  practice to write down; reporting it as confirmed at 5 points per dimension
  with the direction predicted in advance is not defensible. The honest line is
  "consistent with what I expected, at a sample size that cannot distinguish
  that from chance."
- Single rater, unblinded, and the rater wrote the prompt and the rubric. No
  inter-rater reliability is computable. Volunteer that.

### Deliberately not doing

- **Re-deriving `3.8` / `20.0` / `20.0` / `0.95` / `-0.5`.** All trace to
  `jobContext_Eval_Framework (July 2026)`, cited at `evals/__init__.py:13` and
  **absent from the repo**. A cited-but-missing doc is worse than an uncited
  number — the citation implies a derivation nobody can check. Commit the doc,
  or restate the numbers as provisional. Do not invent post-hoc derivations.
- **Isolating judge variance from generation variance.** Arguably the more
  useful measurement for a document pipeline. But fix
  `evals/variance.py:9-10`, which prescribes "add temperature constraints" for
  a judge already at temperature 0.
- **The nightly golden-file gap** (see Part 1). Verify against live Prometheus,
  not the wallboard.
- **Dead code cleanup** — `format_compliance`, `COVER_LETTER_RUBRIC`,
  `keyword_delta` (`evals/variance.py:113-118`, duplicated inline at
  `runner.py:227`), `EvalCase.notes`, `EvalCase.error_ok` (which affects only
  the verbose string at `evals/layer1.py:126`). Repair 2 revives most of
  `rubrics.py` anyway.

### Missing from the plan entirely

The Layer 1 gate is the only component that blocks anything, and **11 of its 23
non-network cases assert nothing but a length floor of 3–20 chars and absence
of a traceback** — TC-002, TC-007, TC-009, TC-010, TC-013, TC-014, TC-015,
TC-016, TC-018, TC-021, TC-023 (`evals/cases.py`). Seven are smoke-tagged, so
they are load-bearing for the deploy gate. Swapping a length floor for a known
substring on those seven is the cheapest available repair and the only one that
hardens something already in the blocking path.

---

## Part 3 — Cannot currently be defended

Code exists; no rationale exists anywhere in the repo, commits, or comments.

1. `MEAN_ALERT = 3.8`, `COV_ALERT_PCT = 20.0`, `FLIP_ALERT_PCT = 20.0` — `evals/variance.py:19-21`.
2. `release_blocked(threshold=0.95)` — `evals/layer1.py:53`. Gates every AKS deploy.
3. `keyword_delta < -0.5` — `evals/runner.py:231`.
4. `min_avg=4.0` / `3.8`, `min_dimension=3` — `evals/rubrics.py:47-48`, for a module no production code imports.
5. `N = 5` — no power analysis; the CoV it feeds is dominated by generation temperature 0.3.
6. `max_chars = 32000` — `evals/runner.py:121`, justified against qwen3 while prod judges on `gpt-4.1-mini`.
7. `max_attempts = 2` — `evals/judge.py:144`; the retry cannot change the outcome at temperature 0 with identical messages.
8. The word "adversarial" — `evals/judge.py:1,26`, `evals/__init__.py:8`, `docs/evals.md:9`, `README.md:218`, and the Grafana dashboard title.
9. The 1–5 scale — anchors exist at `evals/rubrics.py:11-24` and are never sent (`evals/judge.py:44`).
10. `verdict` as a stability metric — criterion never stated to the model (`evals/judge.py:48`), yet `verdict_flip_rate` is a wallboard panel.
11. `reference_file` / "5/5 reference output" — `evals/golden_dataset.json:2`, `evals/golden.py:24`; read by nothing.
12. Two hallucination checks over the same document, never compared — `evals/runner.py:100-115` vs `tools/generate.py:1271,1365`.
13. `evals/__main__.py:43,47` `[:6000]` — the truncation `0545a2c` diagnosed as a defect, left in the CLI judge path.

---

## Part 4 — Working locally

```bash
git fetch origin
git checkout claude/eval-harness-audit-jmhl8m

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # Windows: .venv\Scripts\pip
```

Python 3.12 (matches the Dockerfile and CI). **Do not `pip install -U`** —
`requirements.txt` pins `mcp[cli]<2` because 2.0.0 removed
`mcp.server.fastmcp`.

Verify the machine, cheapest first:

```bash
# 48 harness tests, all mocked, no network
.venv/bin/pytest tests/test_evals.py -q

# Reproduces the CI gate exactly: isolated tmp workspace, no LLM, ~3s
.venv/bin/python scripts/ci_smoke_gate.py

# Do the golden JDs resolve on THIS machine? (exercises evals/golden.py:51-60)
.venv/bin/python -c "from evals.golden import load_golden, resolve_file; [print(e.id, resolve_file(e.jd_file)) for e in load_golden()]"
```

Five paths → repairs 2 and 6 can run here. Five `None`s → wrong machine, and
that is also what the cloud nightly is likely doing while recording success.

The live loop (25 generations + 25 judge calls, real cost):

```bash
.venv/bin/python -m evals suite -n 5
```

Provider resolves from `config.json` (`llm_provider`, `azure_foundry_*`,
`ollama_model`) or the `LLM_PROVIDER` / `LLM_API_KEY` env overrides
(`lib/config.py:413-415`). Point at Foundry, not Ollama, if the numbers are
meant to describe what runs nightly.

**No CI runs on a feature branch.** `deploy.yml` triggers only on push to `qa`
and `main` (`:3-14`); `feat/*` and `fix/*` fire Desktop CI only, which does not
touch this. Run `pytest` and `ci_smoke_gate.py` locally before pushing or there
is no signal until the merge to qa.

Nothing in `evals/` is platform-specific — no `sys.platform`, `os.name`,
`platform.*`, or `shell=True` in `evals/` or `scripts/ci_smoke_gate.py`. The
one cross-platform pain in this repo, `weasyprint` (`tools/export.py:30`,
`lib/template_loader.py:33`), does not affect the evals: `export_resume_pdf` is
imported lazily inside a `try` (`tools/generate.py:1258`) and the `✓` prefix
that `evals/runner.py:113` gates on is the first line of the return regardless.

---

## Part 5 — What is claimable

After repairs 1–4:

- A judge scoring against explicit per-point anchors, running a different model
  than the generator, with a stated pass criterion — **provided the 4.0 / 3.8
  conflict is resolved.**
- A committed set of planted-error fixtures, plus the catch rates actually run,
  with N and the judge model named. Not continuous — it is not in CI.
- Two independent hallucination checks over the same document with a measured
  agreement rate, restricted to numeric claims, reported as raw counts.
- A CI gate that blocks AKS deploys on tool-level smoke failures at 95% —
  stated with its limits: it never runs on a PR so it cannot block a merge, it
  blocks on the smoke subset only and fails open when that subset is empty, and
  it has never failed a build.

Two things already true and worth leading with:

- **The first n=5 run was all false positives** — three harness defects,
  diagnosed and fixed the same night (`0545a2c`). The first thing a new eval
  measures is its own brokenness.
- **The wallboard was lying** — checked against live Prometheus, found no
  `eval_*` series on the pods while the dashboard showed values, traced to qa
  gauges leaking into prod via `max()`, fixed (`9d2f700`). Caught the dashboard
  fabricating numbers about the hallucination detector. That is the answer to
  "how do you know your evals are trustworthy."

On "adversarial": give it up before anyone asks. It is a critical-stance
prompt, not an adversarial architecture. Planted-error fixtures are a test set,
not an architecture either — they measure sensitivity. The accurate framing is
that an unfalsifiable adjective was replaced with a measurable number.
