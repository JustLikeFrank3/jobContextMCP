"""Tests for the three-layer eval framework (evals/).

Layer 1 cases run against the isolated workspace; the case registry doubles
as a drift guard — every case must reference a real domain/action, so a
renamed action fails here before it fails in a live eval run.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evals import cases as case_mod
from evals import golden as golden_mod
from evals import judge as judge_mod
from evals import layer1, rubrics, variance
from evals.cases import CASES, cases_by_tags
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


def test_parse_judge_json_rejects_bad_output():
    with pytest.raises(ValueError):
        judge_mod.parse_judge_json("no json here")
    with pytest.raises(ValueError):
        judge_mod.parse_judge_json('{"keyword_coverage": 9}')
    with pytest.raises(ValueError):
        judge_mod.parse_judge_json(_GOOD_JUDGE_JSON.replace('"pass"', '"maybe"'))


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


def test_judge_output_retries_then_fails_cleanly():
    client = _fake_client(["garbage", "still garbage"])
    with pytest.raises(ValueError, match="unparseable"):
        judge_mod.judge_output("JD", "M", "OUT", client=client, model="m")


def test_judge_output_without_provider_raises_runtime_error():
    # conftest's autouse fixture stubs get_llm_client to (None, None)
    with pytest.raises(RuntimeError, match="No LLM provider"):
        judge_mod.judge_output("JD", "M", "OUT")


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
    assert agg.to_dict()["n_runs"] == 3


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
