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


def test_parse_judge_json_filters_clean_bill_notes():
    payload = json.loads(_GOOD_JUDGE_JSON)
    payload["hallucinations"] = [
        "No hallucinations detected; claims are traceable.",
        "None.",
        "Invented award claim",
    ]
    score = judge_mod.parse_judge_json(json.dumps(payload))
    assert score.hallucinations == ["Invented award claim"]


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
    assert agg.hallucinations == ["made-up title"]  # the flagged claims persist
    assert agg.to_dict()["hallucinations"] == ["made-up title"]
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
