# jobContext Eval Framework

Three-Layer Evaluation Architecture for the jobContext MCP System

Frank Vladmir MacBride III · July 2026

Prepared following interview with Venky at Accenture (2026-07-29). This
document defines the eval methodology, test cases, and LLM-as-judge rubrics
used to measure and continuously improve the jobContext AI-assisted job
search system.

> **Provenance note (2026-08-05).** This is the methodology document cited
> by `evals/__init__.py` and the threshold comments in `evals/variance.py`,
> `evals/layer1.py`, and `evals/runner.py`. It is committed verbatim from
> the July 2026 original (`jobContext_Eval_Framework.docx`), converted to
> Markdown, in response to the 2026-08-04 audit
> ([evals-audit-2026-08-04.md](evals-audit-2026-08-04.md)) which flagged a
> cited-but-absent source. The implementation has evolved since this was
> written (for example, the variance mean-alert now derives from the Layer 2
> rubric threshold rather than the 3.8 flag level below, and the MCP surface
> is 12 consolidated tools). Where this document and the code disagree, the
> code and [evals.md](evals.md) are authoritative; this file records where
> the numbers came from. The alert thresholds below are design values chosen
> by judgment when the framework was drafted — they had not been validated
> against data at the time of writing.

## Three-Layer Architecture

| Layer | What It Tests | Primary Signal |
|---|---|---|
| Layer 1 — MCP Tool Evals | Individual tool actions: correct responses, edge case handling, error states | Pass / Fail, error rate |
| Layer 2 — Skill Evals | Output quality: resume relevance, cover letter tone, ATS readiness | Rubric score 1–5 per dimension |
| Layer 3 — LLM-as-Judge | Systematic output scoring with golden dataset, multi-dimensional rubric, variance analysis | Mean score, CoV, delta vs. baseline |

## LAYER 1 — MCP Tool Evals

These are functional unit tests. Each test invokes a tool action, inspects
the response, and asserts correctness. They run in CI or on demand before
any release of the jobContext MCP server.

### Tool Inventory

The jobContext MCP exposes 11 tools, each with multiple actions:

| Tool | Key Actions | Eval Focus |
|---|---|---|
| workspace | check, setup | Returns complete status object; no missing fields |
| materials | read_master_resume, list, search | Master resume non-empty; list returns ≥1 file; semantic search returns relevant results |
| documents | generate_resume, generate_cover_letter, diff | Generated output contains candidate name, role keywords, company name; diff detects real changes |
| applications | log, list, update, status | Application persisted; retrievable by company; status updates reflect correctly |
| interviews | log, list, context, prep_context | Debrief saved with all fields; upcoming list sorted by date; context includes process details |
| insights | daily_digest, rejection_log, rejections | Digest non-empty; rejection count increments; funnel analysis runs without error |
| job_search | search, save, list | Results non-empty for known role types; saved jobs retrievable |
| people | add, list, context | Contact persisted; lookup by company returns correct person |
| brand | read, update | Returns tone/brand data; updates persist across calls |
| stories | list, search, add | Stories index non-empty; semantic search returns ≥1 result for common themes (leadership, debugging) |
| wellbeing | log, read | Log persists; read returns history; no error on empty history |

### Test Case Schema

Each Layer 1 test case has the fields: `id`, `tool`, `action`, `inputs`
(dict), `expected_shape` (keys that must be present in the response),
`expected_values` (exact values to assert), `error_scenario` (optional —
inputs that should fail gracefully), and `tags`.

### Example Test Cases

| Test ID | Tool | Input | Expected | Tags |
|---|---|---|---|---|
| TC-001 | workspace | action: check | result contains "✓ Master resume" and "✓ config.json" | smoke, read-only |
| TC-002 | materials | action: read_master_resume | result length > 500 chars; contains candidate name | smoke, read-only |
| TC-003 | materials | action: search, query: "Python distributed systems" | ≥1 result returned; result includes relevant resume bullets | semantic, read-only |
| TC-004 | interviews | action: log, company: TestCo, role: SWE, interview_date: 2026-07-01, interview_type: recruiter | result confirms interview saved; id present | write, idempotency |
| TC-005 | interviews | action: list, company: TestCo | returns ≥1 entry matching TestCo from TC-004 | write, read-after-write |
| TC-006 | insights | action: rejection_log, company: TestCo, role: SWE, stage: phone_screen | rejection count increments; result confirms save | write |
| TC-007 | insights | action: rejections, include_pattern_analysis: true | result contains "funnel" or "pattern" section; no exception | analytics, read-only |
| TC-008 | workspace | action: setup with missing required field (no email) | error returned, not a crash; error message is human-readable | error-handling |

### Running Layer 1 Evals

- Run against the live MCP server using any MCP-compatible test harness
  (e.g. mcp-inspector, a pytest wrapper calling the server over stdio, or
  Claude Code tool calls)
- Tag smoke tests — run these on every deploy. Run write tests in an
  isolated test user namespace.
- Measure: pass rate, error rate, response latency p50/p95
- Alert threshold: <95% pass rate on smoke tests = block release

## LAYER 2 — Skill Performance Evals

Layer 2 tests the quality of generated outputs — not whether a tool runs,
but whether what it produces is good. Each eval uses a structured rubric
scored 1–5 per dimension. Rubrics are applied by a human reviewer or by the
Layer 3 LLM judge.

### Resume Generation Rubric

| Dimension | What to Check | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| Keyword Coverage | Key technical terms from the JD appear verbatim or with close synonyms in the resume | None | <25% | 25–50% | 50–75% | >75% |
| Relevance | Bullets emphasize experience most relevant to the target role; irrelevant content is deprioritized or removed | Generic | Slight tilt | Moderate | Strong | Laser-focused |
| Accuracy | Every claim in the output is traceable to the master resume; no hallucinated titles, dates, or achievements | Hallucinations present | Minor issues | Mostly accurate | One small drift | Fully grounded |
| Impact Language | Bullets start with strong action verbs; quantified results where present in source | Passive / weak | Some action verbs | Good | Strong, most quantified | All bullets punchy + quantified |
| ATS Readiness | No tables, graphics, headers/footers that break parsing; keywords in plain text | Multiple issues | 2–3 issues | 1–2 issues | Minor issue | Clean |
| Format Compliance | Correct section order, length (1 page for IC roles), consistent formatting | Wrong format | Major issues | Some issues | Minor issue | Perfect |

### Cover Letter Rubric

| Dimension | What to Check | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| Hook Quality | Opening paragraph grabs attention; does not start with "I am applying" | Boilerplate | Weak | Decent | Good hook | Memorable |
| Company Specificity | Mentions a real detail about the company — product, mission, recent news — not just the company name | None | Name only | One vague mention | Specific + relevant | Deeply researched |
| Voice Match | Tone matches Frank's saved tone samples (direct, confident, not flowery) | Off-brand | Slightly off | Neutral | Good match | Spot on |
| Story Bridge | At least one concrete story connects candidate experience to a role requirement | None | Vague | Present but weak | Clear + relevant | Compelling |
| CTA / Close | Ends with a clear, confident call to action — not "thank you for your consideration" | Weak/generic | Passive | Decent | Confident | Memorable close |

### Passing Thresholds

| Output Type | Min Avg Score | No Dimension Below |
|---|---|---|
| Resume | 4.0 / 5.0 | 3 |
| Cover Letter | 3.8 / 5.0 | 3 |

## LAYER 3 — LLM-as-Judge Framework

Layer 3 is the systematic, repeatable evaluation layer. It uses a golden
dataset of (job description, expected output) pairs, a structured judge
prompt, and statistical analysis to track quality over time and across
model versions.

### Golden Dataset

The golden dataset consists of hand-curated input/output pairs where the
expected output has been reviewed and rated as a 5/5 reference. It is the
ground truth against which new generations are compared.

| ID | Company / Role | JD Archetype | Key Eval Signal | Source File |
|---|---|---|---|---|
| GD-01 | Accenture / AI Native Engineer | Consulting + AI integration, stakeholder communication | Company specificity; AI stack accuracy; consulting tone | Accenture AI Native Engineer Resume.txt |
| GD-02 | Microsoft / SWE II Agent 365 | Large tech, agentic AI, distributed systems | Keyword coverage: agents, LLM, Azure; no hallucinations on MS internals | Microsoft SWE II Agent 365 Resume.txt |
| GD-03 | Home Depot / Sr SWE AI Innovation | Retail tech, full-stack, AI innovation | Retail domain relevance; innovation framing; ATS readiness | Home Depot Sr Software Engineer AI Innovation.txt |
| GD-04 | Delta / Senior Digital Experience AI | Aviation, real-time systems, AI/ML integration | Domain adaptation; safety-conscious framing | Delta Air Lines Senior Digital Experience.txt |
| GD-05 | Sema4.ai / Staff Backend Agent Platform | AI infra, agentic systems, platform engineering | Technical depth; agentic architecture vocabulary | Sema4ai Staff Backend Engineer Agent Platform.txt |

### LLM Judge Prompt

The judge is a separate Claude call that receives: (1) the job description,
(2) the candidate's master resume excerpt, (3) the generated output to
evaluate. It returns a JSON object with per-dimension scores (1–5), a brief
rationale for each, and an overall pass/fail verdict. The judge is
explicitly prompted to be adversarial — to look for hallucinations, weak
bullets, missing keywords, and voice drift — not to be generous.

#### Judge Prompt Template

```
SYSTEM: You are an adversarial resume evaluator. Your job is to find weaknesses, not to be kind.

USER:
JOB DESCRIPTION: {job_description}
MASTER RESUME EXCERPT: {master_resume_excerpt}
GENERATED OUTPUT: {generated_output}

Score the output on each dimension 1–5. Return JSON:
{"keyword_coverage": N, "relevance": N, "accuracy": N, "impact_language": N,
 "ats_readiness": N, "rationale": "...", "hallucinations": [...], "verdict": "pass"|"fail"}
```

### Variance Analysis

Because LLM outputs are non-deterministic, the same input can produce
different quality levels on different runs. Variance analysis quantifies
this risk.

| Metric | How to Calculate | Alert Threshold |
|---|---|---|
| Mean Score | Average judge score across N=5 runs per golden dataset entry | Mean < 3.8 → flag for review |
| Coefficient of Variation (CoV) | Std dev / mean × 100. Measures output consistency. | CoV > 20% → output is unstable; add constraints to prompt |
| Hallucination Rate | % of runs where judge flags ≥1 hallucination | > 0% → immediate review; target 0% |
| Keyword Coverage Delta | Mean keyword score vs. golden reference score | Delta < −0.5 → prompt regression |
| Verdict Flip Rate | % of N runs where verdict switches pass/fail | > 20% → non-deterministic; add temperature constraints |

### Running the Full Eval Suite

1. For each golden dataset entry, call `documents generate_resume` or
   `generate_cover_letter` 5 times (N=5)
2. For each output, run the LLM judge prompt; collect JSON scores
3. Compute mean, std dev, CoV per dimension per golden entry
4. Aggregate to a dashboard row: [GD-ID | Role | Keyword | Relevance |
   Accuracy | Impact | ATS | Mean | CoV | Verdict Flip Rate]
5. Compare to prior run baseline — track delta in a version-stamped log
6. Re-run on any change to: master resume, prompt templates, model version,
   or MCP tool logic

### Sample Eval Results Table

| GD-ID | Role | Keyword | Relev. | Accuracy | Impact | ATS | Mean | CoV% | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| GD-01 | Accenture AI | — | — | — | — | — | — | — | TBD |
| GD-02 | MS Agent 365 | — | — | — | — | — | — | — | TBD |
| GD-03 | Home Depot AI | — | — | — | — | — | — | — | TBD |
| GD-04 | Delta AI | — | — | — | — | — | — | — | TBD |
| GD-05 | Sema4 Platform | — | — | — | — | — | — | — | TBD |

(Table populated after first eval run. Dashes = not yet scored.)

## How to Describe This in an Interview

This section is Frank's quick-reference for explaining the eval framework
to Venky or any technical interviewer at Accenture or elsewhere. It
translates the framework into natural language you can say out loud.

**"What eval framework do you use?"**

I run evals on my jobContext system at three layers. The first layer is
functional unit tests on each MCP tool — I assert that every action returns
the right shape, handles missing inputs gracefully, and persists writes
correctly. The second layer is output quality scoring — I have a rubric
with five dimensions (keyword coverage, relevance, accuracy, impact
language, and ATS readiness) scored 1–5, with a passing threshold of 4.0
average and no dimension below 3. The third layer is an LLM-as-judge setup
where I have a golden dataset of curated job description / resume pairs,
and I run a separate model call as an adversarial judge that scores each
generated output against the rubric and returns structured JSON. I then do
variance analysis across N=5 runs — tracking mean score, coefficient of
variation, and hallucination rate — so I know not just whether quality is
good but whether it's stable.

**"What's your golden dataset?"**

It's a set of five hand-curated job description and reference resume pairs
spanning different role archetypes — consulting/AI at Accenture,
large-scale agentic AI at Microsoft, retail tech at Home Depot, aviation AI
at Delta, and infrastructure/platform at Sema4. Each pair has been reviewed
and rated as a 5/5 reference. When I generate new outputs, I score them
against these pairs and track the delta over time.

**"How do you handle non-determinism?"**

That's what the variance analysis is for. I run the same input five times
and measure the coefficient of variation — std dev over mean — on each
scoring dimension. If CoV exceeds 20%, the output is too unstable for
production and I add tighter constraints to the prompt (lower temperature,
more explicit formatting instructions, chain-of-thought on accuracy). I
also track verdict flip rate — the percentage of runs where the judge
switches from pass to fail — which is the most user-visible form of
non-determinism.

**"How do you detect hallucinations?"**

The judge prompt explicitly asks the model to list any claims in the
generated resume that cannot be traced back to the master resume excerpt I
provide in context. This gives me a hallucination list per run. My hard
requirement is zero hallucination rate — any run flagging even one
hallucinated claim triggers a prompt review. I also do a deterministic
post-check: I extract company names, job titles, and date ranges from the
output and verify each one exists in the master resume using exact-match
lookup before the output is ever saved.

## Next Steps

| # | Action | Priority |
|---|---|---|
| 1 | Run Layer 1 smoke tests against current jobContext MCP server; document pass rate baseline | High — do this week |
| 2 | Run resume generate_resume for all 5 golden dataset entries; score with Layer 2 rubric manually | High — establishes baseline |
| 3 | Set up Layer 3 judge: write the judge prompt as a reusable Claude tool call; automate the N=5 loop | Medium — 1–2 days of work |
| 4 | Add OpenAI API key to workspace config to enable standalone generation mode (removes Copilot dependency) | Medium — unlocks full eval automation |
| 5 | Add two more golden dataset entries from recent application history (e.g. Equifax, Afresh) | Low — improves coverage |
| 6 | Build eval results dashboard as a tracked spreadsheet or HTML artifact; version-stamp each run | Low — nice to have for interviews |

---

jobContext Eval Framework · Frank Vladmir MacBride III · July 2026
