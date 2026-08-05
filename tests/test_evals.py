"""Tests for the three-layer eval framework (evals/).

Layer 1 cases run against the isolated workspace; the case registry doubles
as a drift guard — every case must reference a real domain/action, so a
renamed action fails here before it fails in a live eval run.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import cases as case_mod
from evals import fixtures as fixtures_mod
from evals import golden as golden_mod
from evals import judge as judge_mod
from evals import layer1, rubrics, variance
from evals import runner as runner_mod
from evals.cases import CASES, cases_by_tags
from lib import config as config_mod
from tools.consolidated import DOMAINS


# ── case registry ─────────────────────────────────────────────────────────────

def test_case_ids_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_case_targets_a_real_action():
    for c in CASES:
        assert c.tool in DOMAINS, c.id
        assert c.action in DOMAINS[c.tool], f"{c.id}: {c.tool}.{c.action}"


def test_every_case_input_is_a_real_parameter():
    import inspect

    for c in CASES:
        fn = DOMAINS[c.tool][c.action][0]
        params = set(inspect.signature(fn).parameters)
        for key in c.inputs:
            if c.error_ok:
                continue  # error cases may deliberately omit/misuse params
            assert key in params, f"{c.id}: {c.tool}.{c.action} has no param {key!r}"


def test_all_eleven_domains_covered():
    assert {c.tool for c in CASES} == set(DOMAINS)


def test_tag_filtering():
    smoke = cases_by_tags(("smoke",))
    assert smoke and all("smoke" in c.tags for c in smoke)
    assert all("network" not in c.tags for c in cases_by_tags())
    default = cases_by_tags(None, exclude=("network", "write"))
    assert all("write" not in c.tags for c in default)


# ── layer 1 runner ────────────────────────────────────────────────────────────

def test_layer1_full_run_isolated(isolated_server):
    report = layer1.run_cases()  # all non-network cases, writes included
    failed = [(r.case_id, r.detail, r.response_excerpt) for r in report.failed]
    assert not failed, failed
    assert report.pass_rate == 1.0
    assert not report.release_blocked()
    assert report.latency_percentile(95) >= report.latency_percentile(50) >= 0


def test_layer1_detects_traceback_and_exceptions():
    boom_case = case_mod.EvalCase(id="X-1", tool="workspace", action="check")

    def dispatch_traceback(*_a):
        return "Traceback (most recent call last):\n  boom"

    def dispatch_raise(*_a):
        raise RuntimeError("boom")

    assert not layer1.run_case(boom_case, dispatch=dispatch_traceback).ok
    result = layer1.run_case(boom_case, dispatch=dispatch_raise)
    assert not result.ok and "RuntimeError" in result.detail


def test_layer1_check_response_rules():
    case = case_mod.EvalCase(
        id="X-2", tool="workspace", action="check",
        contains_all=("Alpha",), contains_any=("beta", "gamma"), min_length=5,
    )
    assert layer1.check_response(case, "Alpha and beta") == ""
    assert "missing expected" in layer1.check_response(case, "beta only here")
    assert "none of the expected" in layer1.check_response(case, "Alpha alone")
    assert "shorter" in layer1.check_response(case, "Alp")


def test_layer1_verbose_report_shows_invocation_and_checks(isolated_server):
    report = layer1.run_cases(cases=[case_mod.CASES[0]])  # TC-001 workspace.check
    text = report.to_text(verbose=True)
    assert "call:     workspace.check" in text
    assert "expected: " in text and "WORKSPACE STATUS" in text
    assert "response: " in text
    assert "tags:     smoke, read-only" in text
    # non-verbose stays compact
    assert "call:" not in report.to_text()


def test_layer1_report_math():
    report = layer1.Layer1Report(results=[
        layer1.CaseResult("a", True, 10.0, tags=("smoke",)),
        layer1.CaseResult("b", False, 20.0, tags=("smoke",)),
        layer1.CaseResult("c", True, 30.0),
    ])
    assert report.pass_rate == pytest.approx(2 / 3)
    assert report.smoke_pass_rate() == pytest.approx(0.5)
    assert report.release_blocked()
    text = report.to_text()
    assert "RELEASE BLOCKED" in text and "✗ b" in text
    assert report.to_dict()["cases"][1]["ok"] is False


# ── layer 2 rubrics ───────────────────────────────────────────────────────────

def test_rubric_thresholds():
    good = dict.fromkeys(rubrics.RESUME_RUBRIC, 4)
    ok, reason = rubrics.passes(good, "resume")
    assert ok, reason

    low_dim = dict(good, accuracy=2)
    ok, reason = rubrics.passes(low_dim, "resume")
    assert not ok and "accuracy" in reason

    low_avg = dict.fromkeys(rubrics.RESUME_RUBRIC, 3)
    ok, reason = rubrics.passes(low_avg, "resume")
    assert not ok and "average" in reason

    cover = dict.fromkeys(rubrics.COVER_LETTER_RUBRIC, 4)
    ok, _ = rubrics.passes(cover, "cover_letter")
    assert ok  # 4.0 ≥ 3.8


def test_rubric_validation_rejects_garbage():
    with pytest.raises(ValueError):
        rubrics.passes({"not_a_dimension": 5}, "resume")
    with pytest.raises(ValueError):
        rubrics.passes({"accuracy": 9}, "resume")


# ── layer 3 judge parsing ─────────────────────────────────────────────────────

_GOOD_JUDGE_JSON = json.dumps({
    "keyword_coverage": 4, "relevance": 5, "accuracy": 3, "impact_language": 4,
    "ats_readiness": 5, "rationale": "solid", "hallucinations": [], "verdict": "pass",
})


def test_parse_judge_json_clean():
    score = judge_mod.parse_judge_json(_GOOD_JUDGE_JSON)
    assert score.scores["relevance"] == 5
    assert score.verdict == "pass"
    assert score.mean == pytest.approx(4.2)
    assert score.to_dict()["mean"] == 4.2


def test_parse_judge_json_tolerates_think_blocks_and_fences():
    noisy = f"<think>hmm...{{not json}}</think>Sure!\n```json\n{_GOOD_JUDGE_JSON}\n```"
    assert judge_mod.parse_judge_json(noisy).verdict == "pass"


def test_judge_messages_include_todays_date():
    msgs = judge_mod.build_judge_messages("JD", "M", "OUT", today="2026-07-29")
    assert "TODAY'S DATE: 2026-07-29" in msgs[1]["content"]
    # default fills in a real ISO date rather than leaving the slot empty
    auto = judge_mod.build_judge_messages("JD", "M", "OUT")[1]["content"]
    assert "TODAY'S DATE: 20" in auto


def test_judge_messages_include_rubric_anchors_and_thresholds():
    content = judge_mod.build_judge_messages("JD", "M", "OUT", today="2026-07-29")[1]["content"]
    assert "SCORING RUBRIC" in content
    assert "keyword_coverage" in content
    assert "accuracy" in content
    assert "PASS CRITERION" in content
    assert "average of the five dimensions" in content
    assert "4.0" in content


def test_parse_judge_json_uses_thresholds_for_verdict():
    payload = json.loads(_GOOD_JUDGE_JSON)
    payload["verdict"] = "fail"
    score = judge_mod.parse_judge_json(json.dumps(payload))
    assert score.verdict == "pass"


def test_parse_judge_json_filters_clean_bill_notes():
    payload = json.loads(_GOOD_JUDGE_JSON)
    payload["hallucinations"] = [
        "No hallucinations detected; claims are traceable.",
        "None.",
        "Invented award claim",
    ]
    score = judge_mod.parse_judge_json(json.dumps(payload))
    assert score.hallucinations == ["Invented award claim"]


def test_layer1_smoke_cases_assert_meaningful_content():
    case = case_mod.EvalCase(id="X-3", tool="materials", action="read_master_resume",
                            contains_all=("MASTER SOURCE",), min_length=10)
    assert layer1.check_response(case, "Resume - MASTER SOURCE.txt") == ""
    assert "missing expected" in layer1.check_response(case, "Resume content only")


# Recorded real responses, one per reachable state. The empty-state strings are
# what the isolated gate workspace actually returned (2026-08-04 run); the
# populated-state strings are built from the emitting code in tools/. A marker
# typo in cases.py fails HERE, in pytest, instead of first surfacing as a
# blocked deploy — the previous version of this test only compared the strings
# in cases.py against themselves.
_RECORDED_SMOKE_RESPONSES = {
    "TC-002": [
        "[CI MASTER RESUME]\n\n──── ACHIEVEMENTS ────\n"
        "(Peer-written quotes — use exact language in cover letters and fitment assessments)\n"
        "[CI ACHIEVEMENTS CONTENT]\n\n──── PEER FEEDBACK (verbatim) ────\n"
        "(Direct quotes from managers and colleagues — high-value credibility signals)\n"
        "[CI FEEDBACK CONTENT]",
    ],
    "TC-009": [
        "No applications tracked yet. Use update_application() to add one.\n\n"
        "⚠ No check-in logged yet today. Quick check-in: "
        "log_mental_health_checkin(mood='stable', energy=5)",
        "═══ JOB HUNT STATUS ═══\nLast updated: 2026-08-04\n\n■ TestCo — SWE\n  Status:       applied",
    ],
    "TC-010": [
        "No jobs in queue.",
        "═══ JOB QUEUE ═══\n\n■ [PENDING] TestCo — SWE\n  ID:       1\n  Added:    2026-08-04",
    ],
    "TC-013": [
        "No tone samples logged yet.\nUse log_tone_sample() to ingest writing "
        "samples — cover letters, messages, anything you've actually written.",
        "═══ TONE PROFILE (2 samples, 300 total words) ═══\n"
        "Use these samples to calibrate the candidate's voice before writing anything.",
    ],
    "TC-014": [
        "No check-ins logged in the past 14 days.",
        "═══ MENTAL HEALTH LOG (last 14 days) ═══\n\n"
        "2026-08-04  🟩  mood: good          energy: 7/10  productive: ✓\n\n"
        "Average energy over 14 days: 7.0/10",
    ],
    "TC-021": [
        "No interviews logged yet.",
        "No interviews scheduled in the next 14 days.",
        "# Upcoming interviews (next 14 days, 1 total)\n"
        "- 2026-08-05 (in 1d): TestCo / SWE — recruiter_screen",
    ],
    "TC-016": [
        "No LinkedIn posts logged yet. Use log_linkedin_post() to add posts.",
        "═══ LINKEDIN POSTS (1 posts) ═══\n\n"
        "Aggregate: 12 reactions | 1 reposts | 3 comments | 400 impressions",
    ],
    "TC-023": [
        "No certification reports yet. Generate the current week with "
        'certification(action="weekly_report").',
        "═══ CERTIFICATION REPORTS ═══\n"
        "  #1 — week ending 2026-08-01 v1 (GA) · 4 entries · generated 2026-08-02T09:00:00",
    ],
    "TC-024": [
        "═══ CERTIFICATION PROFILE (GA) ═══\n  state: GA\n"
        "  min_activities_per_week: 3\n  week_ends_on: Saturday",
    ],
}


def test_smoke_markers_replay_recorded_responses():
    for case_id, responses in _RECORDED_SMOKE_RESPONSES.items():
        case = next(c for c in CASES if c.id == case_id)
        for response in responses:
            failed = layer1.check_response(case, response)
            assert failed == "", (case_id, failed, response[:80])


def test_parse_judge_json_rejects_bad_output():
    with pytest.raises(ValueError):
        judge_mod.parse_judge_json("no json here")
    with pytest.raises(ValueError):
        judge_mod.parse_judge_json('{"keyword_coverage": 9}')
    # A bad model verdict is no longer a parse failure — the verdict is
    # code-derived; the model's opinion is kept leniently as model_verdict.
    score = judge_mod.parse_judge_json(_GOOD_JUDGE_JSON.replace('"pass"', '"maybe"'))
    assert score.model_verdict == ""
    assert score.verdict == "pass"  # scores 4,5,3,4,5: mean 4.2, floor met


def test_model_verdict_retained_as_calibration_data():
    score = judge_mod.parse_judge_json(_GOOD_JUDGE_JSON)
    assert score.model_verdict == "pass"
    assert score.to_dict()["model_verdict"] == "pass"
    # Model disagreeing with the rubric is recorded, not corrected away.
    dissent = judge_mod.parse_judge_json(_GOOD_JUDGE_JSON.replace('"pass"', '"fail"'))
    assert dissent.model_verdict == "fail"
    assert dissent.verdict == "pass"
    absent = judge_mod.parse_judge_json(_GOOD_JUDGE_JSON.replace(', "verdict": "pass"', ""))
    assert absent.model_verdict == ""
    assert absent.verdict == "pass"


def _fake_client(payloads: list[str]):
    """Chat-completions client returning canned payloads in order."""
    replies = iter(payloads)

    def create(**_kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=next(replies)))],
            usage=None,
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def _no_rate_gate(monkeypatch):
    from lib import openai_calls

    monkeypatch.setattr(openai_calls, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)


def test_judge_output_with_explicit_client():
    score = judge_mod.judge_output("JD", "MASTER", "OUTPUT",
                                   client=_fake_client([_GOOD_JUDGE_JSON]), model="m")
    assert score.verdict == "pass"


def test_judge_output_preserves_model_metadata():
    score = judge_mod.judge_output(
        "JD",
        "MASTER",
        "OUTPUT",
        client=_fake_client([_GOOD_JUDGE_JSON]),
        model="judge-model",
    )
    assert score.model == "judge-model"


def test_judge_output_retries_then_fails_cleanly():
    client = _fake_client(["garbage", "still garbage"])
    with pytest.raises(ValueError, match="unparseable"):
        judge_mod.judge_output("JD", "M", "OUT", client=client, model="m")


def test_judge_call_caps_max_tokens():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=_GOOD_JUDGE_JSON))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    judge_mod.judge_output("JD", "M", "OUT", client=client, model="m")
    assert captured["max_tokens"] == 2000


def test_judge_output_without_provider_raises_runtime_error():
    # conftest's autouse fixture stubs get_llm_client to (None, None)
    with pytest.raises(RuntimeError, match="No LLM provider"):
        judge_mod.judge_output("JD", "M", "OUT")


# ── judge provider/model routing ──────────────────────────────────────────────
# CI exports LLM_PROVIDER=foundry (deploy.yml), so every config-path test must
# clear the env or it passes locally and fails in CI (CLAUDE.md gotcha).

def _clear_llm_env(monkeypatch):
    for var in ("LLM_PROVIDER", "JUDGE_LLM_PROVIDER", "JUDGE_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_judge_model_honored_on_every_provider_branch(monkeypatch):
    _clear_llm_env(monkeypatch)
    for provider in ("ollama", "anthropic", "foundry", "openai"):
        cfg = {"judge_provider": provider, "judge_model": "judge-x"}
        assert config_mod._resolve_llm_settings(task="eval_judge", cfg=cfg) == (provider, "judge-x"), provider


def test_judge_falls_back_to_provider_model_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    cases = {
        "ollama": ({"ollama_model": "qwen3:14b"}, "qwen3:14b"),
        "anthropic": ({}, "claude-sonnet-5"),
        "foundry": ({"azure_foundry_deployment": "gpt-4.1"}, "gpt-4.1"),
        "openai": ({"openai_model": "gpt-4o"}, "gpt-4o"),
    }
    for provider, (extra, expected) in cases.items():
        cfg = {"judge_provider": provider, **extra}
        assert config_mod._resolve_llm_settings(task="eval_judge", cfg=cfg) == (provider, expected), provider


def test_judge_env_provider_beats_config(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "anthropic")
    cfg = {"judge_provider": "ollama", "judge_model": "judge-x"}
    assert config_mod._resolve_llm_settings(task="eval_judge", cfg=cfg) == ("anthropic", "judge-x")


def test_plain_llm_provider_env_beats_config_judge_provider(monkeypatch):
    # Documented precedence: config judge_provider only works where
    # LLM_PROVIDER is unset; prod/CI must use JUDGE_LLM_PROVIDER.
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "foundry")
    cfg = {"judge_provider": "ollama", "azure_foundry_deployment": "gpt-4.1-mini"}
    provider, model = config_mod._resolve_llm_settings(task="eval_judge", cfg=cfg)
    assert provider == "foundry"
    assert model == "gpt-4.1-mini"


def test_judge_model_env_beats_config(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("JUDGE_LLM_MODEL", "env-model")
    cfg = {"judge_provider": "ollama", "judge_model": "cfg-model"}
    assert config_mod._resolve_llm_settings(task="eval_judge", cfg=cfg)[1] == "env-model"


def test_non_judge_tasks_ignore_judge_keys(monkeypatch):
    _clear_llm_env(monkeypatch)
    cfg = {
        "llm_provider": "openai", "openai_model": "gpt-4o-mini",
        "judge_provider": "ollama", "judge_model": "judge-x",
    }
    # "" is generation; assessment/certification pass task strings today
    # (tools/fitment.py, tools/certification.py) and must stay untouched.
    for task in ("", "assessment", "certification"):
        assert config_mod._resolve_llm_settings(task=task, cfg=cfg) == ("openai", "gpt-4o-mini"), task


def _suite_entry(tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text("We need Python.", encoding="utf-8")
    return golden_mod.GoldenEntry(
        id="GD-T1", company="TestCo", role="SWE", archetype="t", eval_signal="t",
        reference_file="ref.txt", jd_file=str(jd),
    )


def test_suite_judge_model_reflects_what_ran(isolated_server, tmp_path):
    def judge(_jd, _m, _o):
        score = _score({})
        score.model = "actual-judge-model"
        return score

    suite = runner_mod.run_suite(
        entries=[_suite_entry(tmp_path)], n=2,
        generate_fn=lambda _e, _jd: "OUT", judge_fn=judge,
        results_dir=tmp_path / "results",
    )
    assert suite.judge_model == "actual-judge-model"
    assert suite.to_dict()["judge_model"] == "actual-judge-model"


def test_suite_judge_model_falls_back_to_config_when_unstamped(isolated_server, tmp_path):
    suite = runner_mod.run_suite(
        entries=[_suite_entry(tmp_path)], n=1,
        generate_fn=lambda _e, _jd: "OUT",
        judge_fn=lambda _jd, _m, _o: _score({}),  # model stays ""
        results_dir=tmp_path / "results",
    )
    assert suite.judge_model == config_mod._resolve_llm_settings(task="eval_judge")[1]


# ── variance analysis ─────────────────────────────────────────────────────────

def _score(values: dict[str, int], verdict="pass", hallucinations=()):
    return judge_mod.JudgeScore(
        scores={d: values.get(d, 4) for d in judge_mod.JUDGE_DIMENSIONS},
        verdict=verdict, hallucinations=list(hallucinations),
    )


def test_variance_stable_runs():
    agg = variance.aggregate_runs([_score({}) for _ in range(5)])
    assert agg.mean_score == 4.0
    assert agg.cov_pct == 0.0
    assert agg.hallucination_rate_pct == 0.0
    assert agg.flip_rate_pct == 0.0
    assert agg.alerts == []


def test_variance_alerts():
    runs = [
        _score({"accuracy": 1, "keyword_coverage": 2}, verdict="fail",
               hallucinations=["made-up title"]),
        _score({}, verdict="pass"),
        _score({"relevance": 2}, verdict="fail"),
    ]
    agg = variance.aggregate_runs(runs)
    assert agg.hallucination_rate_pct == pytest.approx(100 / 3)
    assert agg.flip_rate_pct == pytest.approx(100 / 3)
    assert any("hallucination" in a for a in agg.alerts)
    assert agg.hallucinations == ["made-up title"]  # the flagged claims persist
    assert agg.to_dict()["hallucinations"] == ["made-up title"]
    assert agg.to_dict()["n_runs"] == 3


def test_dimension_floor_alert_fires_despite_strong_mean():
    # The failure mode the harness exists for: fluent, keyword-dense, and
    # fabricating. accuracy=2 with everything else 5 gives mean 4.4 —
    # passes() fails it on the dimension floor, so alerts must fire too.
    agg = variance.aggregate_runs([_score({d: 5 for d in judge_mod.JUDGE_DIMENSIONS} | {"accuracy": 2})])
    assert agg.mean_score > variance.MEAN_ALERT  # mean clause stays silent
    assert any("accuracy" in a and "dimension floor" in a for a in agg.alerts)


def test_dimension_at_floor_raises_no_alert():
    # passes() uses strict <, so a mean exactly at the floor is not a failure.
    agg = variance.aggregate_runs([_score({"accuracy": 3})])
    assert not any("dimension floor" in a for a in agg.alerts)


def test_variance_math_helpers():
    assert variance.cov_percent([4.0]) == 0.0
    assert variance.cov_percent([2.0, 4.0]) == pytest.approx(47.14, abs=0.01)
    assert variance.verdict_flip_rate(["pass", "pass", "fail", "pass"]) == 25.0
    with pytest.raises(ValueError):
        variance.aggregate_runs([])


def test_keyword_delta():
    base = variance.aggregate_runs([_score({"keyword_coverage": 5})])
    curr = variance.aggregate_runs([_score({"keyword_coverage": 4})])
    assert variance.keyword_delta(curr, base) == -1.0


def test_fixture_manifest_loads_and_files_exist():
    master_file, jd_file, entries = fixtures_mod.load_fixture_manifest()
    fixtures_dir = Path(fixtures_mod.__file__).parent / "fixtures"
    assert (fixtures_dir / master_file).exists()
    assert (fixtures_dir / jd_file).exists()
    assert len(entries) >= 9
    for entry in entries:
        assert (fixtures_dir / entry.file).exists(), entry.id
        assert entry.expected_signal in ("hallucination", "dimension", "clean")
        assert entry.corruption_note
    # exactly one clean-baseline control
    assert sum(1 for e in entries if e.expected_signal == "clean") == 1
    # no fixture filename may shadow a golden-dataset jd file (golden.py
    # searches the fixtures dir too)
    assert not any(e.file.startswith("GD-") for e in entries)


def test_fixture_planted_claims_absent_from_synthetic_master():
    # A corrupted fixture whose planted claim is accidentally traceable
    # measures nothing — assert genuine absence, numerically where possible.
    from lib import provenance

    master_file, _jd, entries = fixtures_mod.load_fixture_manifest()
    fixtures_dir = Path(fixtures_mod.__file__).parent / "fixtures"
    master = (fixtures_dir / master_file).read_text(encoding="utf-8")
    for entry in entries:
        if entry.expected_signal != "hallucination":
            continue
        numeric = provenance.extract_claims(entry.expected_detail)
        if numeric:
            untraceable = provenance.check_claims(entry.expected_detail, [master])
            assert untraceable, f"{entry.id}: every numeric claim in planted detail is traceable to the master"
        else:
            assert entry.expected_detail.casefold() not in master.casefold(), \
                f"{entry.id}: planted text appears in the synthetic master"


def test_fixture_baseline_is_fully_traceable():
    from lib import provenance

    master_file, jd_file, entries = fixtures_mod.load_fixture_manifest()
    fixtures_dir = Path(fixtures_mod.__file__).parent / "fixtures"
    master = (fixtures_dir / master_file).read_text(encoding="utf-8")
    baseline = next(e for e in entries if e.expected_signal == "clean")
    text = (fixtures_dir / baseline.file).read_text(encoding="utf-8")
    assert provenance.check_claims(text, [master]) == []


def test_fixture_claim_caught_matching():
    assert fixtures_mod.claim_caught(["Cut p95 order-ingestion latency by 52%"], "latency by 52%")
    assert fixtures_mod.claim_caught(["52%"], "latency by 52%")  # numeric intersection
    assert fixtures_mod.claim_caught(["the resume claims $2M in savings"], "saving $2M in annual integration costs")
    assert fixtures_mod.claim_caught(["Northwind Logistics Group is not in the master"], "Northwind Logistics Group")
    assert not fixtures_mod.claim_caught(["some unrelated 40% claim"], "latency by 52%")
    assert not fixtures_mod.claim_caught([], "latency by 52%")


def _fixture_score(scores=None, hallucinations=(), model="stub-judge"):
    return judge_mod.JudgeScore(
        scores=scores or {d: 5 for d in judge_mod.JUDGE_DIMENSIONS},
        hallucinations=list(hallucinations),
        verdict="pass",
        model=model,
    )


def test_run_fixture_suite_classifies_catches(monkeypatch):
    # Judge stub: flags the planted claim on FX-01 only, tanks
    # impact_language always, never flags anything else.
    def judge_fn(_jd, _master, output):
        halls = ["latency by 52% is unsupported"] if "52%" in output else []
        return _fixture_score(
            scores={**{d: 5 for d in judge_mod.JUDGE_DIMENSIONS}, "impact_language": 2},
            hallucinations=halls,
        )

    report = fixtures_mod.run_fixture_suite(n=2, judge_fn=judge_fn)
    by_id = {r.entry.id: r for r in report.results}
    assert by_id["FX-01"].catches == 2          # hallucination named → caught
    assert by_id["FX-02"].catches == 0          # nothing flagged → missed
    assert by_id["FX-08"].catches == 2          # impact_language 2 < 3 → style catch
    assert report.baseline_false_positives == 0
    assert report.judge_models == ["stub-judge"]
    assert "FX-01" in report.to_text()


def test_run_fixture_suite_counts_baseline_false_positives():
    report = fixtures_mod.run_fixture_suite(
        n=3, judge_fn=lambda *_a: _fixture_score(hallucinations=["everything is fake"]))
    assert report.baseline_false_positives == 3


def test_run_fixture_suite_never_touches_generation(monkeypatch):
    import sys

    class _Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"fixture suite touched tools.generate.{name}")

    monkeypatch.setitem(sys.modules, "tools.generate", _Exploding())
    report = fixtures_mod.run_fixture_suite(n=1, judge_fn=lambda *_a: _fixture_score())
    assert len(report.results) >= 9


def test_format_dashboard_shows_provenance_agreement():
    aggregate = variance.aggregate_runs([_score({})])
    entry = runner_mod.EntryResult(
        "GD-01",
        "Engineer",
        aggregate=aggregate,
        provenance_agreement={
            "both_flagged": 1,
            "both_clean": 0,
            "judge_only": 0,
            "provenance_only": 0,
        },
    )
    text = runner_mod.format_dashboard(runner_mod.SuiteResult(n_runs=1, entries=[entry]))
    assert "prov" in text.lower()
    # Compact per-row counts in AGREEMENT_KEYS order, legend on the footer.
    assert "1/0/0/0/0" in text
    assert "Prov: " + "/".join(runner_mod.AGREEMENT_KEYS) in text


def test_run_entry_tracks_numeric_provenance_agreement(monkeypatch, tmp_path):
    from lib import provenance as provenance_mod

    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("JD text", encoding="utf-8")
    monkeypatch.setattr(runner_mod, "resolve_file", lambda _name: jd_path)
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda *args, **kwargs: "MASTER")
    monkeypatch.setattr(
        provenance_mod,
        "latest_run",
        lambda *, company="", role="", db_path=None: {
            "claims": ["34%"],
            "violations": ["34%"],
        },
    )

    entry = golden_mod.GoldenEntry(
        id="GD-01",
        company="Acme",
        role="Engineer",
        archetype="x",
        eval_signal="y",
        reference_file="ref.txt",
        jd_file="jd.txt",
    )

    judge_score = judge_mod.JudgeScore(
        scores={dim: 4 for dim in judge_mod.JUDGE_DIMENSIONS},
        verdict="pass",
        hallucinations=["invented 34% uplift"],
    )

    result = runner_mod.run_entry(
        entry,
        n=1,
        generate_fn=lambda _entry, _jd: "output",
        judge_fn=lambda _jd, _master, _output: judge_score,
    )

    assert result.provenance_agreement["both_flagged"] == 1
    assert result.provenance_agreement["judge_only"] == 0
    assert result.provenance_agreement["provenance_only"] == 0
    assert result.provenance_agreement["both_clean"] == 0
    assert result.dashboard_row()["provenance_agreement"]["both_flagged"] == 1


def _entry_and_jd(monkeypatch, tmp_path):
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("JD text", encoding="utf-8")
    monkeypatch.setattr(runner_mod, "resolve_file", lambda _name: jd_path)
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda *a, **k: "MASTER")
    return golden_mod.GoldenEntry(
        id="GD-01", company="Acme", role="Engineer", archetype="x",
        eval_signal="y", reference_file="ref.txt", jd_file="jd.txt",
    )


def test_missing_provenance_row_is_no_record_not_both_clean():
    buckets = runner_mod._numeric_provenance_agreement(["invented 34%"], None)
    assert buckets["no_record"] == 1
    assert buckets["both_clean"] == 0 and buckets["judge_only"] == 0


def test_provenance_lookup_failure_cannot_discard_judge_score(monkeypatch, tmp_path):
    from lib import provenance as provenance_mod

    def _boom(*, company="", role="", db_path=None):
        raise RuntimeError("provenance DB unavailable")

    monkeypatch.setattr(provenance_mod, "latest_run", _boom)
    entry = _entry_and_jd(monkeypatch, tmp_path)
    result = runner_mod.run_entry(
        entry, n=1,
        generate_fn=lambda _e, _jd: "output",
        judge_fn=lambda _jd, _m, _o: _score({}),
    )
    assert result.aggregate is not None, result.error  # the score survived
    assert result.error == ""
    assert result.provenance_agreement["no_record"] == 1


def test_stale_provenance_row_is_fenced_out(monkeypatch, tmp_path):
    from lib import provenance as provenance_mod

    # Same row id before and after generation: record_run swallowed its write,
    # so the row predates this run and must not be counted as its verdict.
    stale = {"id": 41, "claims": ["34%"], "violations": ["34%"]}
    monkeypatch.setattr(
        provenance_mod, "latest_run",
        lambda *, company="", role="", db_path=None: dict(stale),
    )
    entry = _entry_and_jd(monkeypatch, tmp_path)
    judge_score = judge_mod.JudgeScore(
        scores={dim: 4 for dim in judge_mod.JUDGE_DIMENSIONS},
        verdict="pass", hallucinations=["invented 34% uplift"],
    )
    result = runner_mod.run_entry(
        entry, n=1,
        generate_fn=lambda _e, _jd: "output",
        judge_fn=lambda _jd, _m, _o: judge_score,
    )
    assert result.provenance_agreement["no_record"] == 1
    assert result.provenance_agreement["both_flagged"] == 0


def test_fresh_provenance_row_passes_the_fence(monkeypatch, tmp_path):
    from lib import provenance as provenance_mod

    rows = iter([
        {"id": 41, "claims": [], "violations": []},        # pre-generation
        {"id": 42, "claims": ["34%"], "violations": ["34%"]},  # written by this run
    ])
    monkeypatch.setattr(
        provenance_mod, "latest_run",
        lambda *, company="", role="", db_path=None: next(rows),
    )
    entry = _entry_and_jd(monkeypatch, tmp_path)
    judge_score = judge_mod.JudgeScore(
        scores={dim: 4 for dim in judge_mod.JUDGE_DIMENSIONS},
        verdict="pass", hallucinations=["invented 34% uplift"],
    )
    result = runner_mod.run_entry(
        entry, n=1,
        generate_fn=lambda _e, _jd: "output",
        judge_fn=lambda _jd, _m, _o: judge_score,
    )
    assert result.provenance_agreement["both_flagged"] == 1
    assert result.provenance_agreement["no_record"] == 0


def test_failed_pre_read_disqualifies_post_row(monkeypatch, tmp_path):
    from lib import provenance as provenance_mod

    # Pre-generation read fails, post-generation read returns a row. With no
    # pre-read baseline the row's freshness is unprovable — it could be stale
    # — so it must land in no_record, not be trusted as this run's verdict.
    calls = {"n": 0}

    def _flaky(*, company="", role="", db_path=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provenance DB briefly unavailable")
        return {"id": 41, "claims": ["34%"], "violations": ["34%"]}

    monkeypatch.setattr(provenance_mod, "latest_run", _flaky)
    entry = _entry_and_jd(monkeypatch, tmp_path)
    judge_score = judge_mod.JudgeScore(
        scores={dim: 4 for dim in judge_mod.JUDGE_DIMENSIONS},
        verdict="pass", hallucinations=["invented 34% uplift"],
    )
    result = runner_mod.run_entry(
        entry, n=1,
        generate_fn=lambda _e, _jd: "output",
        judge_fn=lambda _jd, _m, _o: judge_score,
    )
    assert result.aggregate is not None, result.error
    assert result.provenance_agreement["no_record"] == 1
    assert result.provenance_agreement["both_flagged"] == 0


# ── ingest endpoint + metrics bridge ─────────────────────────────────────────

_SUITE_PAYLOAD = {
    "started_at": "2026-07-29T12:00:00", "git_sha": "abc1234", "provider": "ollama",
    "n_runs": 3,
    "rows": [
        {"gd_id": "GD-01", "role": "AI Native Engineer", "keyword": 4.0,
         "relevance": 5.0, "accuracy": 3.33, "impact": 5.0, "ats": 4.0,
         "mean": 4.27, "cov_pct": 2.7, "flip_rate_pct": 0.0,
         "alerts": ["hallucination rate 100% — immediate review"]},
        {"gd_id": "GD-02", "role": "SWE II", "error": "JD file not found: x.txt"},
    ],
    "detail": {"GD-01": {"hallucination_rate_pct": 100.0}},
}


@pytest.fixture(autouse=True)
def _clean_metrics():
    from lib import metrics

    metrics.reset()
    yield
    metrics.reset()


def test_ingest_suite_sets_gauges_and_persists(http_client_noauth):
    from lib import metrics

    resp = http_client_noauth.post("/api/evals/results", json=_SUITE_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"stored": "suite", "entries_scored": 1}

    text = metrics.render_prometheus()
    assert 'eval_mean_score{gd_id="GD-01"} 4.27' in text
    assert 'eval_hallucination_rate_pct{gd_id="GD-01"} 100' in text
    assert 'eval_dimension_score{dimension="keyword_coverage",gd_id="GD-01"} 4' in text
    assert 'eval_alert_count{gd_id="GD-01"} 1' in text
    assert "GD-02" not in text  # errored entry must not fabricate scores
    assert 'eval_pushes_total{kind="suite"} 1' in text

    stored = http_client_noauth.get("/api/evals/results").json()
    assert stored["suite"]["rows"][0]["gd_id"] == "GD-01"
    assert "updated_at" in stored


def test_ingest_layer1_and_bad_payload(http_client_noauth):
    from lib import metrics

    resp = http_client_noauth.post(
        "/api/evals/results", json={"pass_rate": 1.0, "smoke_pass_rate": 0.9}
    )
    assert resp.status_code == 200
    text = metrics.render_prometheus()
    assert "eval_layer1_pass_rate_pct 100" in text
    assert "eval_layer1_smoke_pass_rate_pct 90" in text

    assert http_client_noauth.post(
        "/api/evals/results", json={"wat": True}
    ).status_code == 422


def test_ingest_requires_auth(http_client_authed):
    resp = http_client_authed.post("/api/evals/results", json=_SUITE_PAYLOAD)
    assert resp.status_code == 401
    ok = http_client_authed.post(
        "/api/evals/results", json=_SUITE_PAYLOAD,
        headers={"Authorization": "Bearer test-key"},
    )
    assert ok.status_code == 200


def test_restore_gauges_after_restart(http_client_noauth):
    from lib import metrics
    from transport.http.routes.evals import restore_gauges

    http_client_noauth.post("/api/evals/results", json=_SUITE_PAYLOAD)
    metrics.reset()  # simulate process restart
    assert "eval_mean_score" not in metrics.render_prometheus()
    restore_gauges()
    assert 'eval_mean_score{gd_id="GD-01"} 4.27' in metrics.render_prometheus()


def test_restore_keeps_run_timestamp_honest(http_client_noauth, monkeypatch):
    """A restart must NOT re-stamp eval_last_run_timestamp_seconds with 'now'
    — that resets the wallboard's 'time since last run' on every deploy and
    masks a stalled schedule. The stamp survives via payload.completed_at."""
    from evals import ingest as ingest_mod
    from lib import metrics

    monkeypatch.setattr(ingest_mod.time, "time", lambda: 1000.0)
    http_client_noauth.post("/api/evals/results", json=_SUITE_PAYLOAD)
    assert 'eval_last_run_timestamp_seconds{kind="suite"} 1000' in metrics.render_prometheus()

    metrics.reset()  # simulate process restart, much later
    monkeypatch.setattr(ingest_mod.time, "time", lambda: 99999.0)
    ingest_mod.restore_gauges()
    text = metrics.render_prometheus()
    assert 'eval_last_run_timestamp_seconds{kind="suite"} 1000' in text  # not 99999


def test_restore_legacy_payload_sets_no_timestamp(isolated_server):
    """A stored payload from before completed_at existed: restoring must not
    invent a run time — an absent gauge is honest, a restart stamp is not."""
    import json as json_mod

    import server as srv
    from evals import ingest as ingest_mod
    from lib import metrics

    legacy = {k: v for k, v in _SUITE_PAYLOAD.items()}  # no completed_at
    srv.EVAL_RESULTS_FILE.write_text(json_mod.dumps({"suite": legacy}), encoding="utf-8")
    ingest_mod.restore_gauges()
    text = metrics.render_prometheus()
    assert 'eval_mean_score{gd_id="GD-01"} 4.27' in text
    assert "eval_last_run_timestamp_seconds" not in text


def test_restore_reads_owner_partition(isolated_server, monkeypatch):
    """Cloud: results are stored in the owner's partition; a restart restore
    that reads the root partition finds nothing and silently drops every
    eval gauge (ghost-series wallboard). restore_gauges must enter the
    owner partition when ENTRA_OWNER_OID points at one."""
    import json as json_mod

    from evals import ingest as ingest_mod
    from lib import config, metrics

    oid = "owner-oid-123"
    partition = config.DATA_FOLDER / "users" / oid
    partition.mkdir(parents=True)
    payload = {**_SUITE_PAYLOAD, "completed_at": 1234.0}
    (partition / "eval_results.json").write_text(
        json_mod.dumps({"suite": payload}), encoding="utf-8"
    )
    monkeypatch.setenv("ENTRA_OWNER_OID", oid)

    ingest_mod.restore_gauges()
    text = metrics.render_prometheus()
    assert 'eval_mean_score{gd_id="GD-01"} 4.27' in text
    assert 'eval_last_run_timestamp_seconds{kind="suite"} 1234' in text


# ── server-side runs (control plane) ─────────────────────────────────────────

def test_run_evals_executor_end_to_end(isolated_server, tmp_path, monkeypatch):
    """enqueue → dispatch → executor runs the (stubbed) suite → results stored,
    gauges set, artifacts on the work row."""
    from evals import runner as runner_mod
    from evals import work as evals_work
    from lib import config, metrics, work
    from lib.io import _load_json

    def fake_run_suite(entries=None, n=5, results_dir=None):
        assert n == 2
        assert [e.id for e in entries] == ["GD-01"]
        suite = runner_mod.SuiteResult(n_runs=n, started_at="2026-07-29T22:00:00")
        suite.entries.append(runner_mod.EntryResult(
            "GD-01", "AI Native Engineer",
            aggregate=variance.aggregate_runs([_score({})]),
        ))
        return suite

    monkeypatch.setattr(runner_mod, "run_suite", fake_run_suite)
    item_id = evals_work.enqueue_run(n=2, entries=["GD-01"], origin="test")
    work._execute(None, item_id)

    item = work.get_item(item_id)
    assert item["status"] == "succeeded", item["error"]
    assert item["artifacts"]["entries_scored"] == 1
    assert item["artifacts"]["rows"][0]["gd_id"] == "GD-01"
    stored = _load_json(config.EVAL_RESULTS_FILE, {})
    assert stored["suite"]["rows"][0]["mean"] == 4.0
    assert 'eval_mean_score{gd_id="GD-01"} 4' in metrics.render_prometheus()


def test_run_evals_executor_reports_failure(isolated_server, monkeypatch):
    from evals import runner as runner_mod
    from evals import work as evals_work
    from lib import work

    def boom(**_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(runner_mod, "run_suite", boom)
    item_id = evals_work.enqueue_run(n=1)
    work._execute(None, item_id)
    item = work.get_item(item_id)
    assert item["status"] == "failed"
    assert "provider exploded" in item["error"]


def test_seconds_until_utc_hour():
    import datetime as dt

    from evals.work import seconds_until_utc_hour

    now = dt.datetime(2026, 7, 29, 6, 30, tzinfo=dt.timezone.utc)
    assert seconds_until_utc_hour(8, now) == 5400  # 1.5h ahead
    assert seconds_until_utc_hour(6, now) == 23.5 * 3600  # already past → tomorrow
    on_the_hour = dt.datetime(2026, 7, 29, 8, 0, tzinfo=dt.timezone.utc)
    assert seconds_until_utc_hour(8, on_the_hour) == 24 * 3600  # never 0


def test_nightly_enqueue_skips_when_pending(isolated_server, monkeypatch):
    from evals import work as evals_work

    monkeypatch.setattr(evals_work, "_owner_partition", lambda: None)
    first = evals_work._enqueue_nightly()
    assert first is not None
    assert evals_work._enqueue_nightly() is None  # one already queued


def test_start_nightly_task_env_gate(monkeypatch):
    from evals.work import start_nightly_task

    monkeypatch.delenv("EVALS_NIGHTLY_HOUR_UTC", raising=False)
    assert start_nightly_task() is None
    monkeypatch.setenv("EVALS_NIGHTLY_HOUR_UTC", "not-an-hour")
    assert start_nightly_task() is None
    monkeypatch.setenv("EVALS_NIGHTLY_HOUR_UTC", "25")
    assert start_nightly_task() is None

    async def _valid():
        monkeypatch.setenv("EVALS_NIGHTLY_HOUR_UTC", "8")
        task = start_nightly_task()
        assert task is not None
        task.cancel()

    import asyncio

    asyncio.run(_valid())


def test_run_route_enqueues(http_client_noauth, monkeypatch):
    from evals import work as evals_work

    seen = {}

    def fake_enqueue(n=5, entries=None, origin="api"):
        seen.update(n=n, entries=entries)
        return 42

    monkeypatch.setattr(evals_work, "enqueue_run", fake_enqueue)
    resp = http_client_noauth.post("/api/evals/run", json={"n": 3, "entries": ["GD-02"]})
    assert resp.status_code == 200
    assert resp.json() == {"work_id": 42, "status_url": "/api/work/42"}
    assert seen == {"n": 3, "entries": ["GD-02"]}

    assert http_client_noauth.post(
        "/api/evals/run", json={"n": "many"}
    ).status_code == 422
    assert http_client_noauth.post(
        "/api/evals/run", json={"entries": "GD-02"}
    ).status_code == 422


# ── push client ───────────────────────────────────────────────────────────────

def test_push_results_posts_json(monkeypatch):
    from evals import push as push_mod

    captured = {}

    class FakeResponse:
        def read(self):
            return b'{"stored": "suite", "entries_scored": 1}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(push_mod.urllib.request, "urlopen", fake_urlopen)
    result = push_mod.push_results(
        {"rows": []}, url="http://127.0.0.1:9999/", api_key="sekret"
    )
    assert result == {"stored": "suite", "entries_scored": 1}
    assert captured["url"] == "http://127.0.0.1:9999/api/evals/results"
    assert captured["auth"] == "Bearer sekret"
    assert captured["body"] == {"rows": []}


def test_push_results_requires_url():
    from evals.push import push_results

    with pytest.raises(ValueError, match="no server URL"):
        push_results({"rows": []}, url="")


def test_cli_push_uses_latest_results(monkeypatch, tmp_path, capsys):
    from evals import __main__ as cli
    from evals import runner as runner_mod

    results = tmp_path / "results"
    results.mkdir()
    (results / "results-20260729-120000.json").write_text('{"rows": []}', encoding="utf-8")
    monkeypatch.setattr(runner_mod, "RESULTS_DIR", results)
    monkeypatch.setattr(
        "evals.push.push_results",
        lambda payload, url, api_key: {"stored": "suite", "entries_scored": 0},
    )
    rc = cli.main(["push", "--push-url", "http://x"])
    assert rc == 0
    assert "pushed" in capsys.readouterr().out


def test_cli_push_no_results_fails_cleanly(monkeypatch, tmp_path, capsys):
    from evals import __main__ as cli
    from evals import runner as runner_mod

    monkeypatch.setattr(runner_mod, "RESULTS_DIR", tmp_path / "empty")
    assert cli.main(["push", "--push-url", "http://x"]) == 1
    assert "run the suite first" in capsys.readouterr().err


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_layer1_writes_json_report(isolated_server, tmp_path, capsys):
    from evals.__main__ import main

    out = tmp_path / "report.json"
    rc = main(["layer1", "--include-writes", "--json", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["pass_rate"] == 1.0
    assert "LAYER 1 EVAL REPORT" in capsys.readouterr().out


def test_cli_layer1_smoke_tag_filter(isolated_server, capsys):
    from evals.__main__ import main

    assert main(["layer1", "--tags", "smoke"]) == 0
    out = capsys.readouterr().out
    assert "TC-001" in out and "TC-004" not in out  # write case excluded by default


def test_cli_judge_stability_run(monkeypatch, tmp_path, capsys):
    from evals import __main__ as cli

    jd = tmp_path / "jd.txt"
    output = tmp_path / "out.txt"
    master = tmp_path / "master.txt"
    for f in (jd, output, master):
        f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "evals.judge.judge_output", lambda *_a, **_k: _score({}), raising=True
    )
    rc = cli.main([
        "judge", "--jd", str(jd), "--output", str(output),
        "--master", str(master), "-n", "2",
    ])
    assert rc == 0
    assert '"n_runs": 2' in capsys.readouterr().out


def test_cli_suite_entry_filter(monkeypatch, tmp_path, capsys):
    from evals import __main__ as cli
    from evals.runner import SuiteResult

    seen = {}

    def fake_run_suite(entries=None, n=5):
        seen["ids"] = [e.id for e in entries]
        seen["n"] = n
        return SuiteResult(n_runs=n, entries=[])

    monkeypatch.setattr("evals.runner.run_suite", fake_run_suite, raising=True)
    assert cli.main(["suite", "-n", "2", "--entries", "GD-01,GD-03"]) == 0
    assert seen == {"ids": ["GD-01", "GD-03"], "n": 2}
    assert "GD-ID" in capsys.readouterr().out


# ── golden dataset + suite runner ─────────────────────────────────────────────

def test_golden_manifest_loads():
    entries = golden_mod.load_golden()
    assert [e.id for e in entries] == ["GD-01", "GD-02", "GD-03", "GD-04", "GD-05"]
    assert all(e.output_kind == "resume" for e in entries)


def test_resolve_file_literal_and_missing(tmp_path):
    real = tmp_path / "jd.txt"
    real.write_text("x", encoding="utf-8")
    assert golden_mod.resolve_file(str(real)) == real
    assert golden_mod.resolve_file(str(tmp_path / "nope.txt")) is None
    assert golden_mod.resolve_file("definitely-not-anywhere.txt") is None


def test_suite_runner_with_stubbed_generation(isolated_server, tmp_path):
    from evals import runner as runner_mod
    from evals.golden import GoldenEntry

    jd = tmp_path / "jd.txt"
    jd.write_text("We need Python and Kubernetes.", encoding="utf-8")
    entry = GoldenEntry(
        id="GD-T1", company="TestCo", role="SWE", archetype="t", eval_signal="t",
        reference_file="ref.txt", jd_file=str(jd),
    )
    missing = GoldenEntry(
        id="GD-T2", company="TestCo", role="SWE", archetype="t", eval_signal="t",
        reference_file="ref.txt", jd_file="does-not-exist.txt",
    )
    suite = runner_mod.run_suite(
        entries=[entry, missing], n=3,
        generate_fn=lambda _e, _jd: "GENERATED RESUME",
        judge_fn=lambda _jd, _m, _o: _score({}),
        results_dir=tmp_path / "results",
    )
    rows = [e.dashboard_row() for e in suite.entries]
    assert rows[0]["mean"] == 4.0 and rows[0]["gd_id"] == "GD-T1"
    assert "not found" in rows[1]["error"]
    assert "GD-T1" in runner_mod.format_dashboard(suite)

    # results were persisted; a second run picks up the first as baseline
    files = list((tmp_path / "results").glob("results-*.json"))
    assert len(files) == 1
    suite2 = runner_mod.run_suite(
        entries=[entry], n=2,
        generate_fn=lambda _e, _jd: "GENERATED RESUME",
        judge_fn=lambda _jd, _m, _o: _score({"keyword_coverage": 3}),
        results_dir=tmp_path / "results",
    )
    assert suite2.entries[0].aggregate is not None
    latest = runner_mod.latest_results(tmp_path / "results")
    assert latest is not None
    payload = latest[1]
    assert "baseline_delta" in payload
    assert payload["baseline_delta"]["GD-T1"]["keyword"] == -1.0
    assert payload["baseline_delta"]["GD-T1"]["keyword_regression"] is True
