"""Tenant eval loop: golden set CRUD, judge preference, triage rulings, screens."""
from __future__ import annotations

import json

import pytest

from evals import tenant


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Point the partition-resolved paths at a temp dir."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    from lib import config

    monkeypatch.setattr(config, "get_active_workspace_folder", lambda: ws)
    # The evals page reads the latest run_evals work item, so the work DB
    # must be hermetic too — never the repo's real data folder.
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_FOLDER", data, raising=False)
    import evals.work as evals_work

    monkeypatch.setattr(evals_work, "_partition_results_dir", lambda: tmp_path / "eval_runs")
    return ws


class TestGoldenCrud:
    def test_no_manifest_means_none_not_empty(self, workspace):
        assert tenant.load_tenant_golden() is None

    def test_upsert_creates_entry_and_jd_file(self, workspace):
        row = tenant.upsert_golden_entry("Acme", "Staff Engineer", "JD text here")
        assert row["id"] == "GD-T01"
        assert row["reference_file"] == ""
        jd = workspace / "evals" / "golden" / "GD-T01-jd.txt"
        assert jd.read_text(encoding="utf-8") == "JD text here"
        entries = tenant.load_tenant_golden()
        assert entries is not None and entries[0].company == "Acme"

    def test_ids_increment_and_update_in_place(self, workspace):
        tenant.upsert_golden_entry("A", "R1", "jd1")
        row2 = tenant.upsert_golden_entry("B", "R2", "jd2")
        assert row2["id"] == "GD-T02"
        updated = tenant.upsert_golden_entry("B2", "R2b", "jd2b", entry_id="GD-T02")
        assert updated["id"] == "GD-T02"
        entries = tenant.list_tenant_entries()
        assert len(entries) == 2
        assert {e["company"] for e in entries} == {"A", "B2"}

    def test_blank_fields_rejected(self, workspace):
        with pytest.raises(ValueError):
            tenant.upsert_golden_entry("", "R", "jd")
        with pytest.raises(ValueError):
            tenant.upsert_golden_entry("C", "R", "jd", output_kind="poem")

    @pytest.mark.parametrize("entry_id", ["../outside", "../../outside", "/tmp/outside",
                                         "C:\\outside", "a/b", "a\\b", "bad\nentry"])
    def test_entry_id_cannot_escape_golden_folder(self, workspace, entry_id):
        with pytest.raises(ValueError, match="entry_id"):
            tenant.upsert_golden_entry("C", "R", "untrusted", entry_id=entry_id)
        with pytest.raises(ValueError, match="entry_id"):
            tenant.delete_golden_entry(entry_id)
        assert not (workspace / "evals").exists()

    def test_entry_symlink_cannot_overwrite_outside_file(self, workspace):
        root = workspace / "evals" / "golden"
        root.mkdir(parents=True)
        outside = workspace / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        try:
            (root / "GD-T01-jd.txt").symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        with pytest.raises(ValueError, match="inside the golden folder"):
            tenant.upsert_golden_entry("C", "R", "overwrite", entry_id="GD-T01")
        assert outside.read_text(encoding="utf-8") == "keep"

    def test_delete_removes_row_and_jd(self, workspace):
        tenant.upsert_golden_entry("A", "R", "jd")
        assert tenant.delete_golden_entry("GD-T01") is True
        assert tenant.delete_golden_entry("GD-T01") is False
        assert tenant.list_tenant_entries() == []
        assert not (workspace / "evals" / "golden" / "GD-T01-jd.txt").exists()

    def test_malformed_row_skipped_not_fatal(self, workspace):
        tenant.upsert_golden_entry("A", "R", "jd")
        path = workspace / "evals" / "golden_dataset.json"
        data = json.loads(path.read_text())
        data["entries"].append({"id": "GD-BAD", "unknown_key": 1})
        path.write_text(json.dumps(data))
        entries = tenant.load_tenant_golden()
        assert [e.id for e in entries] == ["GD-T01"]


class TestExecutorPrecedence:
    def test_tenant_set_wins_over_committed_manifest(self, workspace, monkeypatch):
        import evals.work as evals_work

        tenant.upsert_golden_entry("Acme", "Staff", "jd")
        captured = {}

        def fake_run_suite(entries=None, n=5, judge_fn=None, results_dir=None, **kw):
            captured["ids"] = [e.id for e in entries]
            captured["judge_fn"] = judge_fn

            class Suite:
                def to_dict(self):
                    return {"rows": []}
                entries = []
            return Suite()

        monkeypatch.setattr("evals.runner.run_suite", fake_run_suite)
        monkeypatch.setattr("evals.ingest.store_results", lambda p: ("evals", 0))
        evals_work.run_evals_executor({"n": 1})
        assert captured["ids"] == ["GD-T01"]
        assert captured["judge_fn"] is None  # no judge prefs stored

    def test_empty_tenant_set_refuses_instead_of_running_owner_files(self, workspace):
        import evals.work as evals_work

        tenant.upsert_golden_entry("A", "R", "jd")
        tenant.delete_golden_entry("GD-T01")  # manifest now exists but is empty
        out = evals_work.run_evals_executor({"n": 1})
        assert out["entries_scored"] == 0
        assert "no golden entries" in out["errors"][0]


class TestJudgePrefs:
    def test_default_is_no_override(self, workspace):
        prefs = tenant.load_judge_prefs()
        assert prefs["provider"] == "" and prefs["has_key"] is False
        assert tenant.build_judge_fn() is None

    def test_key_is_write_only_and_survives_resave(self, workspace):
        tenant.save_judge_prefs("openai", "gpt-4o-mini", api_key="sk-secret")
        prefs = tenant.load_judge_prefs()
        assert prefs["has_key"] is True
        assert "sk-secret" not in json.dumps(prefs)
        # re-save without a key keeps the stored one
        tenant.save_judge_prefs("openai", "gpt-4o")
        raw = json.loads((workspace / "evals" / "judge.json").read_text())
        assert raw["api_key"] == "sk-secret" and raw["model"] == "gpt-4o"

    def test_clearing_provider_clears_everything(self, workspace):
        tenant.save_judge_prefs("openai", "gpt-4o-mini", api_key="sk-secret")
        tenant.save_judge_prefs("")
        assert tenant.load_judge_prefs()["has_key"] is False
        assert tenant.build_judge_fn() is None

    def test_bad_provider_rejected(self, workspace):
        with pytest.raises(ValueError):
            tenant.save_judge_prefs("bard")

    def test_judge_fn_uses_stored_client_and_model(self, workspace, monkeypatch):
        tenant.save_judge_prefs("anthropic", "claude-sonnet-5", api_key="sk-ant")
        captured = {}

        def fake_judge(jd, master, output, client=None, model=""):
            captured["model"] = model
            captured["base_url"] = str(client.base_url)
            return "SCORE"

        monkeypatch.setattr("evals.judge.judge_output", fake_judge)
        fn = tenant.build_judge_fn()
        assert fn("jd", "master", "out") == "SCORE"
        assert captured["model"] == "claude-sonnet-5"
        assert "api.anthropic.com" in captured["base_url"]

    def test_keyed_provider_without_key_disables_override(self, workspace):
        tenant.save_judge_prefs("openai", "gpt-4o-mini")  # no key ever stored
        assert tenant.build_judge_fn() is None

    def test_calibration_labels_state_their_corpus_scope(self):
        # A true measurement rendered in a tenant dashboard silently implies
        # THEIR corpus — every measured label must name what it was measured
        # on (ruled D in review, 2026-08-23).
        sonnet = tenant.judge_calibration_label("claude-sonnet-5")
        assert sonnet.startswith("calibrated")
        assert "platform's reference corpus" in sonnet and "not your documents" in sonnet
        mini = tenant.judge_calibration_label("gpt-4.1-mini")
        assert "NOT recommended" in mini and "platform's reference corpus" in mini
        assert tenant.judge_calibration_label("mystery-9b") == tenant.JUDGE_UNCALIBRATED


class TestJudgeKeyAtRest:
    def test_key_encrypted_on_disk_when_app_key_set(self, workspace, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        tenant.save_judge_prefs("anthropic", "claude-sonnet-5", api_key="sk-ant-verysecret")
        raw = (workspace / "evals" / "judge.json").read_text()
        assert "sk-ant-verysecret" not in raw
        assert "enc:v1:" in raw
        # ... and decrypts on use
        captured = {}

        def fake_judge(jd, master, output, client=None, model=""):
            captured["key"] = client.api_key
            return "S"

        monkeypatch.setattr("evals.judge.judge_output", fake_judge)
        tenant.build_judge_fn()("jd", "m", "o")
        assert captured["key"] == "sk-ant-verysecret"

    def test_no_app_key_degrades_to_cleartext_and_says_so(self, workspace, monkeypatch):
        monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr("lib.crypto._load_key", lambda: "")
        tenant.save_judge_prefs("openai", "gpt-4o-mini", api_key="sk-clear")
        raw = (workspace / "evals" / "judge.json").read_text()
        assert "sk-clear" in raw  # documented degradation, same as lib.crypto
        prefs = tenant.load_judge_prefs()
        assert prefs["has_key"] is True
        # a tenant-supplied key in cleartext is surfaced, never silent
        assert prefs["key_plaintext_at_rest"] is True

    def test_encrypted_key_not_reported_as_plaintext(self, workspace, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        tenant.save_judge_prefs("openai", "gpt-4o-mini", api_key="sk-x")
        assert tenant.load_judge_prefs()["key_plaintext_at_rest"] is False


class TestHistoryAndVisuals:
    def _write_run(self, results_dir, stamp, mean, flags, accuracy=4.0, n_runs=5,
                   master_sha=None):
        results_dir.mkdir(parents=True, exist_ok=True)
        detail = {"GD-T01": {"per_dimension": {
            "accuracy": {"mean": accuracy}, "keyword_coverage": {"mean": 3.0}}}}
        if flags is not None:
            detail["GD-T01"]["hallucination_flags"] = flags
        payload = {"started_at": stamp, "rows": [{"gd_id": "GD-T01", "mean": mean}],
                   "detail": detail}
        if n_runs is not None:
            payload["n_runs"] = n_runs
        if master_sha is not None:
            payload["master_sha"] = master_sha
        (results_dir / f"results-{stamp}.json").write_text(json.dumps(payload))

    def test_history_oldest_first_with_absent_flags_as_none(self, workspace, tmp_path):
        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260820-080000", 3.2, None)  # pre-count payload
        self._write_run(rd, "20260822-080000", 3.5, 26)
        self._write_run(rd, "20260823-080000", 3.66, 8)
        hist = tenant.results_history()
        assert [round(r["mean"], 2) for r in hist] == [3.2, 3.5, 3.66]
        assert [r["flags"] for r in hist] == [None, 26, 8]
        assert [r["n_runs"] for r in hist] == [5, 5, 5]
        assert hist[-1]["dimensions"]["accuracy"] == 4.0

    def test_history_skips_malformed_files(self, workspace, tmp_path):
        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260823-080000", 3.66, 8)
        (rd / "results-bad.json").write_text("{not json")
        assert len(tenant.results_history()) == 1

    def test_svg_panels_render_and_respect_absent(self, workspace, tmp_path):
        import transport.http.routes.dashboard.evals_lab as lab

        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260822-080000", 3.5, None)
        self._write_run(rd, "20260823-080000", 3.66, 8)
        hist = tenant.results_history()
        trend = lab._svg_trend(hist)
        assert "<svg" in trend and "3.66" in trend
        assert trend.count("<rect") == 1  # absent flags = gap, not a zero bar
        dims = lab._svg_dimensions(hist[-1]["dimensions"])
        assert "accuracy" in dims and "4.00" in dims
        assert lab._svg_trend(hist[:1]) == ""  # one point is not a trend

    def test_trend_bars_normalize_by_n(self, workspace, tmp_path):
        # 8 flags at N=5 and 2 flags at N=1 are the SAME rate — equal bars,
        # each tooltip naming its N. Raw totals across mixed N would ship the
        # specificity bug this product exists to catch.
        import re

        import transport.http.routes.dashboard.evals_lab as lab

        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260822-080000", 3.5, 8, n_runs=5)
        self._write_run(rd, "20260823-080000", 3.6, 2, n_runs=1)
        trend = lab._svg_trend(tenant.results_history())
        assert "8 flags across N=5 (1.6/run)" in trend
        assert "2 flags across N=1 (2.0/run)" in trend
        heights = [float(m) for m in re.findall(r"height='([\d.]+)'", trend)]
        assert len(heights) == 2
        assert heights[1] > heights[0]  # 2.0/run beats 1.6/run despite 8 > 2 raw

    def test_history_carries_master_sha(self, workspace, tmp_path):
        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260822-080000", 3.5, 8)  # pre-stamp payload
        self._write_run(rd, "20260823-080000", 3.6, 2, master_sha="abc123def456")
        hist = tenant.results_history()
        assert [r["master_sha"] for r in hist] == ["", "abc123def456"]

    def test_trend_marks_master_changes_and_never_guesses(self, workspace, tmp_path):
        # Amber marker ONLY between points whose shas are known and differ.
        # unknown→known and known→same draw nothing: absence of evidence is
        # not a change.
        import transport.http.routes.dashboard.evals_lab as lab

        rd = tmp_path / "eval_runs"
        self._write_run(rd, "20260820-080000", 3.2, 26)                          # unknown
        self._write_run(rd, "20260821-080000", 3.4, 20, master_sha="aaa111")     # unknown→known: no marker
        self._write_run(rd, "20260822-080000", 3.5, 12, master_sha="aaa111")     # same: no marker
        self._write_run(rd, "20260823-080000", 3.9, 4, master_sha="bbb222")      # changed: marker
        trend = lab._svg_trend(tenant.results_history())
        assert trend.count("master changed here") == 1
        assert "aaa111 → bbb222" in trend


class TestTriage:
    def test_ruling_roundtrip_and_clear(self, workspace):
        rec = tenant.save_ruling("GD-T01", "claims 5+ years", "D", "actually true, document it")
        key = tenant.claim_key("GD-T01", "claims 5+ years")
        assert tenant.load_triage()[key]["ruling"] == "D"
        assert rec["note"] == "actually true, document it"
        tenant.save_ruling("GD-T01", "claims 5+ years", "")
        assert key not in tenant.load_triage()

    def test_same_claim_same_key_across_runs(self, workspace):
        assert tenant.claim_key("GD-1", "x") == "6c36cfdb95ec4c52"
        assert tenant.claim_key("GD-1", "x") != tenant.claim_key("GD-2", "x")

    def test_bad_ruling_rejected(self, workspace):
        with pytest.raises(ValueError):
            tenant.save_ruling("GD-1", "claim", "E")


class TestScreens:
    @pytest.fixture
    def client(self, workspace, monkeypatch, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import transport.http.routes.dashboard.evals_lab as lab

        results = {"updated_at": "2026-08-23T04:29:30", "suite": {
            "judge_model": "claude-sonnet-5", "n_runs": 5,
            "rows": [{"gd_id": "GD-T01", "role": "Staff", "mean": 3.5, "accuracy": 4.0,
                      "cov_pct": 4.0, "flip_rate_pct": 0.0, "alerts": ["mean 3.50 < 4.0"]}],
            "detail": {"GD-T01": {"hallucination_flags": 2,
                                  "hallucinations": ["<b>claims X</b>"],
                                  "critic": {"findings": [
                                      {"claim": "misplaced Y", "verdict": "contradicted",
                                       "evidence": "source says Z"}]}}},
        }}
        monkeypatch.setattr(lab, "_payload", lambda: results)
        app = FastAPI()
        app.include_router(lab.router, prefix="/dashboard")
        return TestClient(app)

    def test_page_renders_results_triage_and_escapes(self, client):
        page = client.get("/dashboard/evals")
        assert page.status_code == 200
        text = page.text
        assert "claude-sonnet-5" in text and "calibrated" in text
        assert "&lt;b&gt;claims X&lt;/b&gt;" in text  # LLM output escaped
        assert "<b>claims X</b>" not in text
        assert "misplaced Y" in text  # critic findings triageable too

    def test_page_empty_state(self, client, monkeypatch):
        import transport.http.routes.dashboard.evals_lab as lab

        monkeypatch.setattr(lab, "_payload", lambda: {})
        page = client.get("/dashboard/evals")
        assert "No eval run stored yet" in page.text

    def test_stored_timestamp_cannot_inject_script(self, client, monkeypatch):
        import transport.http.routes.dashboard.evals_lab as lab

        attack = "</script><script>alert('injected')</script>"
        monkeypatch.setattr(lab, "_payload", lambda: {"updated_at": attack})
        page = client.get("/dashboard/evals")
        assert page.status_code == 200
        assert attack not in page.text
        assert "window.__run_inflight = false" in page.text

    def test_claim_data_roundtrips_as_html_attribute_not_script(self, client, monkeypatch):
        from html.parser import HTMLParser
        import transport.http.routes.dashboard.evals_lab as lab

        class ClaimParser(HTMLParser):
            claims = None
            calibration = None

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if attributes.get("id") == "claim-data":
                    self.claims = json.loads(attributes["data-claims"])
                if attributes.get("id") == "judge-data":
                    self.calibration = json.loads(attributes["data-calibration"])

        attack = "</script><script>alert('injected')</script>\" & <!--"
        from lib import config

        monkeypatch.setattr(config, "_resolve_llm_settings", lambda **kwargs: ("openai", attack))
        monkeypatch.setattr(lab, "_payload", lambda: {"suite": {
            "rows": [{"gd_id": "GD-T01", "mean": 3.0}],
            "detail": {"GD-T01": {"hallucinations": [attack]}},
        }})
        page = client.get("/dashboard/evals")
        assert page.status_code == 200
        parser = ClaimParser()
        parser.feed(page.text)
        assert parser.claims[0]["claim"] == attack
        assert attack in parser.calibration["install_default"]
        assert "<script>alert('injected')" not in page.text
        assert "window.__claims" not in page.text
        assert "window.__cal" not in page.text

    def test_invalid_golden_path_returns_validation_error(self, client):
        for route in ("/dashboard/evals/golden", "/dashboard/evals/golden/delete"):
            result = client.post(route, json={"entry_id": "../outside", "company": "C",
                                             "role": "R", "jd_text": "malicious"})
            assert result.status_code == 422

    def test_all_stored_result_text_stays_inert_in_html(self, client, monkeypatch):
        from html.parser import HTMLParser
        import transport.http.routes.dashboard.evals_lab as lab

        class InjectionParser(HTMLParser):
            injected = False

            def handle_starttag(self, tag, attrs):
                if tag == "jc-injected" or any(name == "data-injected" for name, _ in attrs):
                    self.injected = True

        attack = '</script><jc-injected data-injected="yes">&\'</jc-injected><script>'
        monkeypatch.setattr(lab, "_payload", lambda: {
            "updated_at": attack, "suite": {
                "judge_model": attack, "master_sha": attack,
                "rows": [{"gd_id": attack, "role": attack, "mean": 3.0,
                          "accuracy": attack, "cov_pct": attack,
                          "flip_rate_pct": attack, "alerts": [attack]},
                         {"gd_id": "error-row", "error": attack}],
                "detail": {attack: {"hallucination_flags": 1,
                                   "hallucinations": [attack],
                                   "critic": {"findings": [{"claim": attack, "verdict": attack}]}}},
            },
        })
        monkeypatch.setattr(tenant, "load_triage", lambda: {
            tenant.claim_key(attack, attack): {"ruling": "D", "note": attack},
        })
        page = client.get("/dashboard/evals")
        assert page.status_code == 200
        parser = InjectionParser()
        parser.feed(page.text)
        assert not parser.injected
        assert attack not in page.text
        assert "&lt;jc-injected" in page.text

    def test_rejection_logs_do_not_include_user_supplied_lines(self, client, caplog):
        attack = "injected\r\nFAKE LOG ENTRY"
        client.post("/dashboard/evals/golden", json={
            "company": attack, "role": attack, "jd_text": ""})
        client.post("/dashboard/evals/triage", json={
            "gd_id": attack, "claim": "claim", "ruling": attack})
        assert "golden-set write rejected" in caplog.text
        assert "triage ruling rejected" in caplog.text
        assert "FAKE LOG ENTRY" not in caplog.text

    def test_triage_post_persists(self, client):
        out = client.post("/dashboard/evals/triage", json={
            "gd_id": "GD-T01", "claim": "claims X", "ruling": "B", "note": "wrong place"})
        assert out.status_code == 200
        assert out.json()["stored"]["ruling"] == "B"
        assert client.post("/dashboard/evals/triage", json={
            "gd_id": "GD-T01", "claim": "claims X", "ruling": "Q"}).status_code == 422

    def test_golden_post_and_delete(self, client):
        out = client.post("/dashboard/evals/golden", json={
            "company": "Acme", "role": "Staff", "jd_text": "the jd"})
        assert out.json()["entry"]["id"] == "GD-T01"
        assert client.post("/dashboard/evals/golden", json={
            "company": "", "role": "", "jd_text": ""}).status_code == 422
        assert client.post("/dashboard/evals/golden/delete",
                           json={"entry_id": "GD-T01"}).json()["deleted"] is True

    def test_rejected_golden_write_leaves_a_log_line(self, client, caplog):
        # 2026-08-24 report, acceptance criteria: "A server-side log line
        # exists for every rejected or dropped golden set write."
        import logging

        with caplog.at_level(logging.WARNING, logger="transport.http.routes.dashboard.evals_lab"):
            out = client.post("/dashboard/evals/golden", json={
                "company": "", "role": "Staff", "jd_text": "jd"})
        assert out.status_code == 422
        assert any("golden-set write rejected" in r.getMessage() for r in caplog.records)

    def test_saved_golden_write_leaves_a_log_line(self, client, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="transport.http.routes.dashboard.evals_lab"):
            out = client.post("/dashboard/evals/golden", json={
                "company": "Acme", "role": "Staff", "jd_text": "the jd"})
        assert out.status_code == 200
        assert any("golden-set entry saved" in r.getMessage() for r in caplog.records)

    def test_rejected_triage_ruling_leaves_a_log_line(self, client, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="transport.http.routes.dashboard.evals_lab"):
            out = client.post("/dashboard/evals/triage", json={
                "gd_id": "GD-T01", "claim": "claims X", "ruling": "Q"})
        assert out.status_code == 422
        assert any("triage ruling rejected" in r.getMessage() for r in caplog.records)

    def test_judge_post_never_echoes_key(self, client):
        out = client.post("/dashboard/evals/judge", json={
            "provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-supersecret"})
        assert out.status_code == 200
        assert "sk-supersecret" not in out.text
        assert out.json()["prefs"]["has_key"] is True
        page = client.get("/dashboard/evals")
        assert "sk-supersecret" not in page.text

    def test_run_post_enqueues_in_partition(self, client, monkeypatch):
        import evals.work as evals_work

        tenant.upsert_golden_entry("Acme", "Staff", "jd")  # guard needs a runnable set
        captured = {}
        def fake_enqueue(n=5, entries=None, origin="api"):
            captured["n"] = n
            return 77

        monkeypatch.setattr(evals_work, "enqueue_run", fake_enqueue)
        out = client.post("/dashboard/evals/run", json={"n": 3})
        assert out.json() == {"work_id": 77, "n": 3, "entries": 1}
        assert captured["n"] == 3

    def test_run_reports_fallback_entry_count(self, client, monkeypatch):
        # No tenant manifest → committed fallback; the count reflects only
        # the JDs actually resolvable in this partition, because that is
        # what the executor will actually run.
        import evals.golden as golden
        import evals.work as evals_work

        monkeypatch.setattr(evals_work, "enqueue_run",
                            lambda n=5, entries=None, origin="api": 78)
        fake = [type("E", (), {"jd_file": f"jd{i}.txt"})() for i in range(3)]
        monkeypatch.setattr(golden, "load_golden", lambda: fake)
        monkeypatch.setattr(golden, "resolve_file",
                            lambda name: None if name == "jd1.txt" else f"/x/{name}")
        out = client.post("/dashboard/evals/run", json={"n": 2})
        assert out.json() == {"work_id": 78, "n": 2, "entries": 2}

    def test_run_refuses_empty_golden_set_with_a_sentence(self, client):
        tenant.upsert_golden_entry("A", "R", "jd")
        tenant.delete_golden_entry("GD-T01")  # manifest exists, empty
        out = client.post("/dashboard/evals/run", json={"n": 5})
        assert out.status_code == 422
        assert "golden set is empty" in out.json()["error"]

    def test_run_refuses_when_no_set_and_fallback_files_absent(self, client, monkeypatch):
        # Brand-new tenant: no manifest, and the committed fallback's JD files
        # don't exist in their partition — refuse before enqueuing a doomed run.
        monkeypatch.setattr("evals.golden.resolve_file", lambda name: None)
        out = client.post("/dashboard/evals/run", json={"n": 5})
        assert out.status_code == 422
        assert "add 3" in out.json()["error"].lower() or "No golden set" in out.json()["error"]

    def test_no_run_triage_state_never_claims_passing(self, client, monkeypatch):
        import transport.http.routes.dashboard.evals_lab as lab

        monkeypatch.setattr(lab, "_payload", lambda: {})
        page = client.get("/dashboard/evals").text
        assert "No run yet, so nothing to triage" in page
        assert "goal state" not in page  # that sentence is earned by a clean RUN

    def test_clean_run_triage_state_says_goal_state(self, client, monkeypatch):
        import transport.http.routes.dashboard.evals_lab as lab

        clean = {"updated_at": "2026-08-23", "suite": {
            "judge_model": "claude-sonnet-5", "n_runs": 5,
            "rows": [{"gd_id": "GD-T01", "role": "Staff", "mean": 4.5, "accuracy": 4.5,
                      "cov_pct": 2.0, "flip_rate_pct": 0.0, "alerts": []}],
            "detail": {"GD-T01": {"hallucination_flags": 0, "hallucinations": [],
                                  "critic": {"findings": []}}}}}
        monkeypatch.setattr(lab, "_payload", lambda: clean)
        page = client.get("/dashboard/evals").text
        assert "goal state" in page

    def test_stamp_endpoint(self, client):
        assert client.get("/dashboard/evals/stamp").json()["updated_at"] == "2026-08-23T04:29:30"

    def test_data_endpoint_default_judge_resolved_not_asserted(self, client, monkeypatch):
        # A BYOK desktop's default judge is the user's own model — the label
        # must resolve reality, never assert "calibrated" for a config this
        # install may not have.
        monkeypatch.setattr("lib.config._resolve_llm_settings",
                            lambda task="", cfg=None: ("ollama", "llama3.1:8b"))
        data = client.get("/dashboard/evals/data").json()
        dj = data["default_judge"]
        assert dj["model"] == "llama3.1:8b"
        assert "MAE 3.2" in dj["calibration"]
        assert "llama3.1:8b" in data["judge"]["calibration"]
        assert "calibrated configuration the platform runs" not in str(data)

    def test_data_endpoint_feeds_the_spa(self, client):
        tenant.save_ruling("GD-T01", "<b>claims X</b>", "B", "wrong place")
        data = client.get("/dashboard/evals/data").json()
        assert data["stamp"] == "2026-08-23T04:29:30"
        assert data["summary"]["total_flags"] == 2
        assert "platform's reference corpus" in data["summary"]["judge_calibration"]
        row = data["rows"][0]
        assert row["gd_id"] == "GD-T01" and row["flags"] == 2
        claims = {c["claim"]: c for c in data["claims"]}
        assert claims["<b>claims X</b>"]["ruling"] == "B"  # ruling joined in
        assert claims["misplaced Y"]["source"] == "critic:contradicted"
        assert "sk-" not in str(data["judge"])  # key never in the payload
        assert data["calibration_map"]["claude-sonnet-5"]
        assert data["triage_meanings"]["D"].startswith("True but undocumented")


class TestRunVisibility:
    """A launched run always resolves to a state the user can see.

    The 2026-08-24 report: a deploy killed an in-flight run; the startup
    sweep dutifully marked the work row failed, but nothing on the evals
    page read work state — so the run 'vanished' and the page said
    'No eval run stored yet', indistinguishable from never having run."""

    @pytest.fixture
    def client(self, workspace, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import transport.http.routes.dashboard.evals_lab as lab

        monkeypatch.setattr(lab, "_payload", lambda: {})
        app = FastAPI()
        app.include_router(lab.router, prefix="/dashboard")
        return TestClient(app)

    @staticmethod
    def _mark_abandoned(work_id):
        from lib.db import get_connection

        with get_connection() as con:
            con.execute(
                "UPDATE work_items SET status='failed', "
                "error='abandoned: attempts exhausted (process restart)', "
                "finished_at=datetime('now') WHERE id=?", (work_id,))
            con.commit()

    def test_latest_run_status_none_without_items(self, workspace):
        import evals.work as evals_work

        assert evals_work.latest_run_status() is None

    def test_latest_run_status_reports_queued_run(self, workspace):
        import evals.work as evals_work

        wid = evals_work.enqueue_run(n=3)
        st = evals_work.latest_run_status()
        assert st["work_id"] == wid and st["status"] == "queued" and st["n"] == 3

    def test_abandoned_error_translated_for_users(self, workspace):
        # The sweep's operator-facing reason becomes what the user needs to
        # know: no results, no resume, provider calls may have been billed.
        import evals.work as evals_work

        self._mark_abandoned(evals_work.enqueue_run(n=1))
        st = evals_work.latest_run_status()
        assert st["status"] == "failed"
        assert "interrupted by a server restart" in st["error"]
        assert "billed" in st["error"]
        assert "abandoned:" not in st["error"]

    def test_data_and_status_endpoints_carry_run_state(self, client):
        import evals.work as evals_work

        assert client.get("/dashboard/evals/data").json()["run"] is None
        assert client.get("/dashboard/evals/run/status").json() == {}
        wid = evals_work.enqueue_run(n=5)
        assert client.get("/dashboard/evals/data").json()["run"]["work_id"] == wid
        s = client.get("/dashboard/evals/run/status").json()
        assert s["status"] == "queued" and s["work_id"] == wid

    def test_page_renders_failed_run_state(self, client):
        import evals.work as evals_work

        wid = evals_work.enqueue_run(n=1)
        self._mark_abandoned(wid)
        page = client.get("/dashboard/evals").text
        assert f"run #{wid} failed" in page
        assert "interrupted by a server restart" in page
        assert "window.__run_inflight = false" in page

    def test_page_renders_inflight_run_and_arms_poll(self, client):
        import evals.work as evals_work

        wid = evals_work.enqueue_run(n=5)
        page = client.get("/dashboard/evals").text
        assert f"work #{wid}" in page
        assert "window.__run_inflight = true" in page


class TestMasterVersioning:
    """Ground-truth identity: stored scores must say WHICH master they
    measured, and the page must compare that against the live master instead
    of letting the user reconstruct it from deploy timestamps (run 363)."""

    @pytest.fixture
    def client(self, workspace, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import transport.http.routes.dashboard.evals_lab as lab

        self._payload = {"updated_at": "2026-08-23T04:29:30", "suite": {
            "judge_model": "claude-sonnet-5", "n_runs": 5, "master_sha": "aaa111bbb222",
            "rows": [{"gd_id": "GD-T01", "role": "Staff", "mean": 4.5}],
            "detail": {},
        }}
        monkeypatch.setattr(lab, "_payload", lambda: self._payload)
        app = FastAPI()
        app.include_router(lab.router, prefix="/dashboard")
        return TestClient(app)

    def test_data_reports_master_changed(self, client, monkeypatch):
        monkeypatch.setattr("evals.runner.master_bundle_sha", lambda: "ccc333ddd444")
        m = client.get("/dashboard/evals/data").json()["master"]
        assert m == {"current_sha": "ccc333ddd444", "run_sha": "aaa111bbb222",
                     "changed": True}

    def test_data_reports_master_unchanged(self, client, monkeypatch):
        monkeypatch.setattr("evals.runner.master_bundle_sha", lambda: "aaa111bbb222")
        m = client.get("/dashboard/evals/data").json()["master"]
        assert m["changed"] is False

    def test_prestamp_run_reports_unknown_not_a_verdict(self, client, monkeypatch):
        monkeypatch.setattr("evals.runner.master_bundle_sha", lambda: "ccc333ddd444")
        del self._payload["suite"]["master_sha"]
        m = client.get("/dashboard/evals/data").json()["master"]
        assert m["changed"] is None and m["run_sha"] == ""

    def test_unreadable_live_master_reports_unknown(self, client, monkeypatch):
        def boom():
            raise OSError("no master here")
        monkeypatch.setattr("evals.runner.master_bundle_sha", boom)
        m = client.get("/dashboard/evals/data").json()["master"]
        assert m["changed"] is None and m["current_sha"] == ""

    def test_page_warns_when_master_changed(self, client, monkeypatch):
        monkeypatch.setattr("evals.runner.master_bundle_sha", lambda: "ccc333ddd444")
        page = client.get("/dashboard/evals").text
        assert "master resume has changed since this run" in page
        assert "aaa111bbb222" in page and "ccc333ddd444" in page

    def test_page_silent_when_master_unchanged(self, client, monkeypatch):
        monkeypatch.setattr("evals.runner.master_bundle_sha", lambda: "aaa111bbb222")
        page = client.get("/dashboard/evals").text
        assert "master resume has changed" not in page
