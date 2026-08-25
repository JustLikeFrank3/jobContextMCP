"""Phase-1 entailment critic (evals/critic.py) and its runner wiring.

The load-bearing properties: the critic is REPORT-ONLY (its findings can
never move a verdict, an alert, or a gate — the whistle comes after the
calibration); it runs ONCE per entry (coverage over repetition); and its
failure costs nothing but a recorded error string.
"""
from __future__ import annotations

import json

import pytest

from evals import golden as golden_mod
from evals import runner as runner_mod
from evals.critic import build_critic_messages, parse_critic_json
from evals.judge import JUDGE_DIMENSIONS, JudgeScore


# ── parser ──────────────────────────────────────────────────────────────────

def test_parse_valid_findings():
    text = json.dumps({"findings": [
        {"claim": "Azure work under Level 5", "verdict": "contradicted",
         "evidence": "MADM was on-prem until 2025"},
        {"claim": "adept at workshops", "verdict": "UNSUPPORTED", "evidence": "NONE"},
    ]})
    findings = parse_critic_json(text)
    assert [f["verdict"] for f in findings] == ["contradicted", "unsupported"]


def test_parse_tolerates_chatter_and_fences():
    text = "<think>hmm let me check</think>```json\n" + json.dumps(
        {"findings": []}) + "\n```"
    assert parse_critic_json(text) == []


def test_parse_drops_entailed_chatty_entries_and_junk():
    text = json.dumps({"findings": [
        {"claim": "fine claim", "verdict": "entailed"},
        "not a dict",
        {"claim": "real one", "verdict": "contradicted", "evidence": "src"},
    ]})
    findings = parse_critic_json(text)
    assert len(findings) == 1
    assert findings[0]["claim"] == "real one"


def test_parse_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_critic_json("no json here")
    with pytest.raises(ValueError):
        parse_critic_json('{"not_findings": 1}')


def test_messages_carry_master_and_document():
    msgs = build_critic_messages("MASTER-TEXT", "DOC-TEXT")
    assert "MASTER-TEXT" in msgs[1]["content"]
    assert "DOC-TEXT" in msgs[1]["content"]
    assert "CONTRADICTED" in msgs[1]["content"]  # the attribution definition rides along
    assert "wrong place" in msgs[1]["content"]


# ── runner wiring ───────────────────────────────────────────────────────────

def _entry(tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text("We need Python.", encoding="utf-8")
    return golden_mod.GoldenEntry(
        id="GD-T", company="X", role="Y", archetype="", eval_signal="",
        reference_file="ref.txt", jd_file=str(jd),
    )


def _score():
    return JudgeScore(scores=dict.fromkeys(JUDGE_DIMENSIONS, 4), verdict="fail")


def test_critic_runs_once_per_entry_and_lands_in_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda: "MASTER")
    calls: list = []

    def fake_critic(master, output):
        calls.append(output)
        return {"model": "m", "findings": [{"claim": "c", "verdict": "contradicted", "evidence": "e"}]}

    result = runner_mod.run_entry(
        _entry(tmp_path), n=3,
        generate_fn=lambda e, jd: "DOC",
        judge_fn=lambda jd, m, o: _score(),
        critic_fn=fake_critic,
    )
    assert len(calls) == 1                      # once per entry, not per run
    assert result.critic["findings"][0]["claim"] == "c"
    # ...and it rides the suite payload under detail.critic
    suite = runner_mod.SuiteResult(n_runs=3, entries=[result])
    assert suite.to_dict()["detail"]["GD-T"]["critic"]["model"] == "m"


def test_critic_failure_is_recorded_and_costs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda: "MASTER")

    def exploding_critic(master, output):
        raise RuntimeError("critic upstream down")

    result = runner_mod.run_entry(
        _entry(tmp_path), n=2,
        generate_fn=lambda e, jd: "DOC",
        judge_fn=lambda jd, m, o: _score(),
        critic_fn=exploding_critic,
    )
    assert result.aggregate is not None          # judge scores stand
    assert result.error == ""                    # not an entry error
    assert "critic upstream down" in result.critic["error"]


def test_report_only_pin_critic_never_touches_verdicts_or_alerts(tmp_path, monkeypatch):
    """THE phase-1 contract: identical judge scores must yield identical
    verdicts and alerts whether the critic found nothing or everything."""
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda: "MASTER")

    def run(critic_fn):
        return runner_mod.run_entry(
            _entry(tmp_path), n=2,
            generate_fn=lambda e, jd: "DOC",
            judge_fn=lambda jd, m, o: _score(),
            critic_fn=critic_fn,
        )

    quiet = run(lambda m, o: {"model": "m", "findings": []})
    loud = run(lambda m, o: {"model": "m", "findings": [
        {"claim": f"bad {i}", "verdict": "contradicted", "evidence": "e"} for i in range(30)
    ]})
    assert quiet.aggregate.alerts == loud.aggregate.alerts
    assert quiet.aggregate.verdicts == loud.aggregate.verdicts


def test_pre_critic_payloads_have_no_critic_key(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_master_excerpt", lambda: "MASTER")
    result = runner_mod.run_entry(
        _entry(tmp_path), n=1,
        generate_fn=lambda e, jd: "DOC",
        judge_fn=lambda jd, m, o: _score(),
        critic_fn=lambda m, o: (_ for _ in ()).throw(RuntimeError("x")),
    )
    result.critic = None  # simulate a payload written before the critic existed
    suite = runner_mod.SuiteResult(n_runs=1, entries=[result])
    assert "critic" not in suite.to_dict()["detail"]["GD-T"]


# ── Phase 3: enforcement helpers ────────────────────────────────────────────

class TestEnforcement:
    def test_only_contradicted_with_real_evidence_is_enforceable(self):
        from evals.critic import enforceable_findings

        result = {"findings": [
            {"claim": "a", "verdict": "contradicted", "evidence": "the source passage"},
            {"claim": "b", "verdict": "contradicted", "evidence": "NONE"},
            {"claim": "c", "verdict": "contradicted", "evidence": ""},
            {"claim": "d", "verdict": "unsupported", "evidence": "irrelevant"},
        ]}
        assert [f["claim"] for f in enforceable_findings(result)] == ["a"]
        assert enforceable_findings(None) == []
        assert enforceable_findings({"error": "boom"}) == []

    def test_feedback_instructs_relocation_not_deletion(self):
        from evals.critic import format_contradiction_feedback

        text = format_contradiction_feedback([
            {"claim": "Azure under Level 5", "verdict": "contradicted",
             "evidence": "never place Azure cloud work under Level 5"},
        ])
        assert "ENTAILMENT VIOLATIONS" in text
        assert "Do not delete true facts" in text
        assert "never place Azure cloud work under Level 5" in text
        assert format_contradiction_feedback([]) == ""

    def test_kill_switch(self, monkeypatch):
        from evals.critic import enforcement_enabled

        monkeypatch.delenv("CRITIC_ENFORCE", raising=False)
        assert enforcement_enabled() is True          # default ON, deliberately
        monkeypatch.setenv("CRITIC_ENFORCE", "0")
        assert enforcement_enabled() is False
        monkeypatch.setenv("CRITIC_ENFORCE", "1")
        assert enforcement_enabled() is True
