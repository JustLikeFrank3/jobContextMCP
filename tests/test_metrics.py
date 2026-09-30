"""Telemetry P0 (lib/metrics.py + instrumentation + exposition).

Covers the registry itself, the Prometheus text rendering, the HTTP
middleware labels (route templates, not raw paths), work-dispatcher
instrumentation, and the /api/work/stats aggregate surface.
"""
from __future__ import annotations

import pytest

from lib import metrics


@pytest.fixture(autouse=True)
def clean_registry():
    metrics.reset()
    yield
    metrics.reset()


def test_gauges_last_write_wins_and_render():
    metrics.set_gauge("eval_mean_score", 4.2, gd_id="GD-01")
    metrics.set_gauge("eval_mean_score", 3.9, gd_id="GD-01")  # overwrite, not accumulate
    metrics.set_gauge("eval_mean_score", 4.5, gd_id="GD-02")
    text = metrics.render_prometheus()
    assert "# TYPE eval_mean_score gauge" in text
    assert 'eval_mean_score{gd_id="GD-01"} 3.9' in text
    assert 'eval_mean_score{gd_id="GD-02"} 4.5' in text
    snap = metrics.snapshot()
    assert {"name": "eval_mean_score", "labels": {"gd_id": "GD-01"}, "value": 3.9} in snap["gauges"]
    metrics.reset()
    assert metrics.snapshot()["gauges"] == []


def test_gauge_rendering_is_lossless_for_timestamps():
    """A unix timestamp must survive exposition intact.

    ``{:g}`` capped at 6 significant digits, quantizing the stamp to the
    nearest 10,000s — "time since last suite run" read up to ~1.4h off, and
    negative right after a run whose stamp rounded up into the future.
    """
    metrics.set_gauge("eval_last_run_timestamp_seconds", 1785571200.0, kind="suite")
    metrics.set_gauge("t_fractional_seconds", 1785571200.25)
    text = metrics.render_prometheus()
    assert 'eval_last_run_timestamp_seconds{kind="suite"} 1785571200\n' in text
    assert "t_fractional_seconds 1785571200.25\n" in text
    assert "e+09" not in text  # no 6-sig-digit exponent form


def test_integral_values_render_without_a_decimal_point():
    """Counters stay bare integers — 2, not 2.0."""
    metrics.inc("widgets_total", 2)
    metrics.set_gauge("score", 5.0)
    metrics.set_gauge("rate_pct", 4.84)
    text = metrics.render_prometheus()
    assert "widgets_total 2\n" in text
    assert "score 5\n" in text
    assert "rate_pct 4.84\n" in text


def test_counters_accumulate_by_label_set():
    metrics.inc("jobs_total", kind="a", status="ok")
    metrics.inc("jobs_total", kind="a", status="ok")
    metrics.inc("jobs_total", kind="b", status="failed")
    text = metrics.render_prometheus()
    assert 'jobs_total{kind="a",status="ok"} 2' in text
    assert 'jobs_total{kind="b",status="failed"} 1' in text
    assert "# TYPE jobs_total counter" in text


def test_summaries_render_count_and_sum():
    metrics.observe("x_seconds", 1.5, op="scan")
    metrics.observe("x_seconds", 2.5, op="scan")
    text = metrics.render_prometheus()
    assert 'x_seconds_count{op="scan"} 2' in text
    assert 'x_seconds_sum{op="scan"} 4' in text
    assert "# TYPE x_seconds summary" in text


def test_timed_records_outcome_label():
    with metrics.timed("op_seconds", kind="k"):
        pass
    with pytest.raises(ValueError):  # noqa: PT012
        with metrics.timed("op_seconds", kind="k"):
            raise ValueError("boom")
    text = metrics.render_prometheus()
    assert 'op_seconds_count{kind="k",outcome="ok"} 1' in text
    assert 'op_seconds_count{kind="k",outcome="error"} 1' in text


def test_label_values_escaped():
    metrics.inc("weird_total", path='say "hi"\nthere')
    text = metrics.render_prometheus()
    assert 'weird_total{path="say \\"hi\\"\\nthere"} 1' in text


def test_work_execution_is_instrumented(tmp_path, monkeypatch):
    import lib.config as cfg
    from lib import work

    monkeypatch.setattr(cfg, "DATA_FOLDER", str(tmp_path), raising=False)
    saved = dict(work._KINDS)
    try:
        work.register_kind("noop", lambda i: {})
        work.register_kind("bad", lambda i: (_ for _ in ()).throw(RuntimeError("x")))
        ok_id = work.enqueue("noop", {})
        bad_id = work.enqueue("bad", {})
        work._execute(None, ok_id)
        work._execute(None, bad_id)
    finally:
        work._KINDS.clear()
        work._KINDS.update(saved)
    text = metrics.render_prometheus()
    assert 'work_items_total{kind="noop",status="succeeded"} 1' in text
    assert 'work_items_total{kind="bad",status="failed"} 1' in text
    assert 'work_item_seconds_count{kind="noop",outcome="ok"} 1' in text


# ── HTTP surface ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [(float("nan"), "NaN"),
                                           (float("inf"), "+Inf"),
                                           (float("-inf"), "-Inf")])
def test_nonfinite_prometheus_samples(value, expected):
    metrics.set_gauge("nonfinite_sample", value)
    assert f"nonfinite_sample {expected}" in metrics.render_prometheus()


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    import lib.config as cfg_mod
    from lib.user_provisioning import provision_user_data

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cfg_mod, "DATA_FOLDER", str(root), raising=False)
    provision_user_data(root)
    monkeypatch.delenv("API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    reset_settings_cache()
    with TestClient(create_app()) as client:
        yield client
    reset_settings_cache()


def test_metrics_endpoint_exposes_request_series(app_client):
    app_client.get("/api/work")           # counted, route template label
    app_client.get("/api/work/424242")    # 404s also counted
    text = app_client.get("/metrics").text
    assert "# TYPE http_requests_total counter" in text
    assert 'route="/api/work"' in text
    # route template, never the raw path (cardinality + privacy)
    assert 'route="/api/work/{item_id}"' in text
    assert "424242" not in text
    assert "process_uptime_seconds" in text


def test_metrics_endpoint_does_not_count_itself(app_client):
    app_client.get("/metrics")
    text = app_client.get("/metrics").text
    assert 'route="/metrics"' not in text


def test_work_stats_aggregates(app_client, monkeypatch):
    import time

    from lib import work

    monkeypatch.setitem(work._KINDS, "capture_url", lambda inputs: {})
    ok = app_client.post("/api/capture", json={"url": "https://jobs.example.com/1"})
    deadline = time.time() + 5
    while time.time() < deadline:
        item = app_client.get(f"/api/work/{ok.json()['work_id']}").json()
        if item["status"] == "succeeded":
            break
        time.sleep(0.05)
    monkeypatch.setitem(
        work._KINDS, "capture_url",
        lambda inputs: (_ for _ in ()).throw(RuntimeError("scrape wall")),
    )
    bad = app_client.post("/api/capture", json={"url": "https://jobs.example.com/2"})
    deadline = time.time() + 5
    while time.time() < deadline:
        item = app_client.get(f"/api/work/{bad.json()['work_id']}").json()
        if item["status"] == "failed":
            break
        time.sleep(0.05)

    stats = app_client.get("/api/work/stats").json()
    rows = {(r["kind"], r["status"]): r["count"] for r in stats["by_kind_status"]}
    assert rows[("capture_url", "succeeded")] == 1
    assert rows[("capture_url", "failed")] == 1
    assert stats["recent_failures"][0]["error_head"].startswith("scrape wall")
