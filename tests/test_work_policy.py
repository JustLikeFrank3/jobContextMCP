"""Control plane P2: execution policy as data (lib/work_policy.py).

The property that matters most is the boring one: **every default reproduces
pre-P2 behavior**. A policy engine whose defaults change how work runs is
indistinguishable from a rewrite, and there would be no way to tell a policy
bug from a regression in the work it governs. Most of these tests exist to pin
that, and the rest pin the ceilings actually holding.
"""
from __future__ import annotations

import pytest

import lib.config as cfg
from lib import work, work_policy
from lib.openai_calls import TokenBudgetExceeded


@pytest.fixture()
def work_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_FOLDER", str(tmp_path), raising=False)
    monkeypatch.delenv("WORK_DAILY_TOKEN_QUOTA", raising=False)
    saved = dict(work._KINDS)
    yield tmp_path
    work._KINDS.clear()
    work._KINDS.update(saved)


@pytest.fixture()
def no_rate_gate(monkeypatch):
    """The 12s inter-call spacing is a production concern, not a test one."""
    from lib import openai_calls as oc
    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc, "_LAST_CHAT_CALL", 0.0)


def _call_llm(prompt: int, completion: int, model: str = "m-test") -> None:
    """One model call reporting the given usage, through the real funnel."""
    import types

    from lib.openai_calls import create_chat_completion
    response = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="text"))],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion,
            total_tokens=prompt + completion),
    )
    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **_k: response)))
    create_chat_completion(client, label="unit", model=model, max_tokens=100)


def _policy(**kinds) -> dict:
    return {"work_policy": {"kinds": kinds}}


class TestDefaultsPreserveBehavior:
    def test_unconfigured_kind_is_single_attempt_and_unbounded(self):
        p = work_policy.for_kind("anything", cfg={})
        assert p.max_attempts == 1
        assert p.model == "" and p.fallback_models == ()
        assert p.token_budget == 0 and p.daily_token_quota == 0
        assert p.backoff_for_attempt(1) == 0.0

    def test_malformed_block_degrades_instead_of_raising(self):
        """A typo in a policy file must not be able to stop work from running —
        only to fail to change how it runs."""
        for bad in ({"work_policy": "nope"}, {"work_policy": {"kinds": 7}},
                    {"work_policy": {"kinds": {"k": "not-a-dict"}}}):
            assert work_policy.for_kind("k", cfg=bad).max_attempts == 1

    def test_nonsense_values_fall_back_per_field(self):
        p = work_policy.for_kind("k", cfg=_policy(k={
            "max_attempts": "three", "token_budget": None,
            "backoff_seconds": ["fast", 2], "fallback_models": "gpt-4o",
        }))
        assert p.max_attempts == 1 and p.token_budget == 0
        assert p.backoff_seconds == (2.0,)   # the unparseable entry is dropped
        assert p.fallback_models == ()       # a bare string is not a list


class TestLayering:
    def test_kind_overrides_defaults(self):
        conf = {"work_policy": {"defaults": {"max_attempts": 2, "token_budget": 100},
                                "kinds": {"k": {"max_attempts": 5}}}}
        p = work_policy.for_kind("k", cfg=conf)
        assert p.max_attempts == 5 and p.token_budget == 100

    def test_defaults_apply_to_kinds_with_no_entry(self):
        conf = {"work_policy": {"defaults": {"max_attempts": 3}}}
        assert work_policy.for_kind("other", cfg=conf).max_attempts == 3

    def test_env_quota_overrides_config(self, monkeypatch):
        conf = {"work_policy": {"defaults": {"daily_token_quota": 10}}}
        monkeypatch.setenv("WORK_DAILY_TOKEN_QUOTA", "999")
        assert work_policy.for_kind("k", cfg=conf).daily_token_quota == 999


class TestRetryClassification:
    @pytest.mark.parametrize("message", [
        "429 Too Many Requests", "Rate limit reached", "request timed out",
        "503 Service Unavailable", "connection reset by peer", "model overloaded",
    ])
    def test_transient_failures_retry(self, message):
        assert work_policy.for_kind("k", cfg={}).is_retryable(RuntimeError(message))

    @pytest.mark.parametrize("exc", [
        KeyError("company"), ValueError("no master resume found"),
        RuntimeError("prompt exceeded context window"),
    ])
    def test_deterministic_failures_do_not_retry(self, exc):
        """These fail identically on attempt two; retrying only doubles the
        cost of a bug."""
        assert not work_policy.for_kind("k", cfg={}).is_retryable(exc)

    def test_status_code_is_read_when_the_message_says_nothing(self):
        class _Exc(Exception):
            response = type("R", (), {"status_code": 503})()

        assert work_policy.for_kind("k", cfg={}).is_retryable(_Exc("upstream said no"))

    def test_ceilings_are_never_retryable(self):
        """Retrying is the exact thing a budget exists to prevent — and a
        hand-written retry_on containing 'exceeded' must not re-enable it."""
        p = work_policy.for_kind("k", cfg=_policy(k={"retry_on": ["exceeded", "quota"]}))
        assert not p.is_retryable(TokenBudgetExceeded("token budget exhausted"))
        assert not p.is_retryable(work_policy.QuotaExceeded("daily token quota reached"))

    def test_custom_retry_on_replaces_the_defaults(self):
        p = work_policy.for_kind("k", cfg=_policy(k={"retry_on": ["flaky"]}))
        assert p.is_retryable(RuntimeError("flaky thing"))
        assert not p.is_retryable(RuntimeError("rate limit"))


class TestModelChain:
    def test_walks_fallbacks_then_stays_on_the_last(self):
        p = work_policy.for_kind("k", cfg=_policy(k={
            "model": "primary", "fallback_models": ["second", "third"]}))
        assert [p.model_for_attempt(n) for n in (1, 2, 3, 4)] == [
            "primary", "second", "third", "third"]

    def test_no_snap_back_to_a_model_that_already_failed(self):
        p = work_policy.for_kind("k", cfg=_policy(k={
            "model": "primary", "fallback_models": ["second"]}))
        assert p.model_for_attempt(9) == "second"

    def test_empty_model_means_whatever_config_resolves(self):
        assert work_policy.for_kind("k", cfg={}).model_for_attempt(1) == ""


class TestBackoff:
    def test_indexes_by_attempt_and_holds_at_the_last(self):
        p = work_policy.for_kind("k", cfg=_policy(k={"backoff_seconds": [1, 4]}))
        assert [p.backoff_for_attempt(n) for n in (1, 2, 3)] == [1.0, 4.0, 4.0]

    def test_absent_means_no_wait(self):
        assert work_policy.for_kind("k", cfg={}).backoff_for_attempt(1) == 0.0


# ── the policy actually driving execution ────────────────────────────────────

def _route_config(monkeypatch, conf: dict) -> None:
    monkeypatch.setattr(cfg, "get_active_config", lambda: conf)


class TestRetriesInExecution:
    def test_transient_failure_is_retried_and_can_succeed(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"flaky": {"max_attempts": 3}}}})
        calls = {"n": 0}

        def _flaky(inputs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("429 rate limit")
            return {"attempts": calls["n"]}

        work.register_kind("flaky", _flaky)
        item_id = work.enqueue("flaky", {})
        work._execute(None, item_id)

        row = work.get_item(item_id)
        assert row["status"] == "succeeded" and row["artifacts"] == {"attempts": 3}
        assert row["attempt"] == 3

    def test_a_deterministic_failure_is_not_retried_even_with_attempts_left(
        self, work_env, monkeypatch
    ):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"bad": {"max_attempts": 5}}}})
        calls = {"n": 0}

        def _bad(inputs):
            calls["n"] += 1
            raise KeyError("company")

        work.register_kind("bad", _bad)
        item_id = work.enqueue("bad", {})
        work._execute(None, item_id)

        assert calls["n"] == 1
        assert work.get_item(item_id)["status"] == "failed"

    def test_attempts_are_exhausted_then_the_row_fails(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"down": {"max_attempts": 2}}}})
        calls = {"n": 0}

        def _down(inputs):
            calls["n"] += 1
            raise RuntimeError("503 service unavailable")

        work.register_kind("down", _down)
        item_id = work.enqueue("down", {})
        work._execute(None, item_id)

        assert calls["n"] == 2
        row = work.get_item(item_id)
        assert row["status"] == "failed" and row["attempt"] == 2
        assert "503" in row["error"]

    def test_max_attempts_is_stamped_at_enqueue_not_read_at_run(
        self, work_env, monkeypatch
    ):
        """An item that has burned its attempts must not become eligible again
        because someone edited a config file while it sat in the queue."""
        _route_config(monkeypatch, {"work_policy": {"kinds": {"k": {"max_attempts": 1}}}})
        work.register_kind("k", lambda i: {})
        item_id = work.enqueue("k", {})
        _route_config(monkeypatch, {"work_policy": {"kinds": {"k": {"max_attempts": 9}}}})
        assert work.get_item(item_id)["max_attempts"] == 1

    def test_explicit_max_attempts_still_wins(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"k": {"max_attempts": 4}}}})
        work.register_kind("k", lambda i: {})
        item_id = work.enqueue("k", {}, max_attempts=2)
        assert work.get_item(item_id)["max_attempts"] == 2

    def test_retry_spend_accumulates_on_one_row(self, work_env, monkeypatch, no_rate_gate):
        """Two attempts, two model calls, one row: the row's totals are what
        this unit of work cost, not what its last attempt cost."""
        _route_config(monkeypatch, {"work_policy": {"kinds": {"spendy": {"max_attempts": 2}}}})
        calls = {"n": 0}

        def _spendy(inputs):
            calls["n"] += 1
            _call_llm(100, 10)
            if calls["n"] == 1:
                raise RuntimeError("429 rate limit")
            return {"ok": True}

        work.register_kind("spendy", _spendy)
        item_id = work.enqueue("spendy", {})
        work._execute(None, item_id)

        row = work.get_item(item_id)
        assert row["status"] == "succeeded"
        assert row["llm_calls"] == 2 and row["tokens_prompt"] == 200


class TestModelRouting:
    def test_routed_model_reaches_the_generator(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"gen": {"model": "routed-1"}}}})
        seen = {}
        work.register_kind("gen", lambda i: seen.update(
            model=cfg._resolve_llm_settings(task="")[1]) or {})
        work._execute(None, work.enqueue("gen", {}))
        assert seen["model"] == "routed-1"

    def test_fallback_model_is_used_on_the_retry(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"gen": {
            "model": "primary", "fallback_models": ["backup"], "max_attempts": 2}}}})
        seen = []

        def _gen(inputs):
            seen.append(cfg._resolve_llm_settings(task="")[1])
            if len(seen) == 1:
                raise RuntimeError("503 service unavailable")
            return {}

        work.register_kind("gen", _gen)
        work._execute(None, work.enqueue("gen", {}))
        assert seen == ["primary", "backup"]

    def test_the_eval_judge_is_never_rerouted(self, work_env, monkeypatch):
        """Which model grades the golden suite is a calibrated decision with an
        MAE table behind it. A work policy that could retarget it would
        invalidate that table with nothing saying so."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("JUDGE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("JUDGE_LLM_MODEL", raising=False)
        _route_config(monkeypatch, {
            "llm_provider": "openai", "openai_model": "gpt-4.1-mini",
            "work_policy": {"kinds": {"evals": {"model": "routed-1"}}},
        })
        seen = {}
        work.register_kind("evals", lambda i: seen.update(
            judge=cfg._resolve_llm_settings(task="eval_judge")[1],
            generator=cfg._resolve_llm_settings(task="")[1]) or {})
        work._execute(None, work.enqueue("evals", {}))
        assert seen["generator"] == "routed-1"
        assert seen["judge"] == "gpt-4.1-mini"

    def test_the_route_is_cleared_after_the_item(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"gen": {"model": "routed-1"}}}})
        work.register_kind("gen", lambda i: {})
        work._execute(None, work.enqueue("gen", {}))
        assert cfg._LLM_MODEL_ROUTE_CTX.get() == ""

    def test_route_is_cleared_even_when_the_executor_raises(self, work_env, monkeypatch):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"gen": {"model": "routed-1"}}}})
        work.register_kind("gen", lambda i: (_ for _ in ()).throw(KeyError("x")))
        work._execute(None, work.enqueue("gen", {}))
        assert cfg._LLM_MODEL_ROUTE_CTX.get() == ""


class TestTokenBudget:
    def test_budget_stops_a_runaway_executor(self, work_env, monkeypatch, no_rate_gate):
        _route_config(monkeypatch, {"work_policy": {"kinds": {"loop": {"token_budget": 250}}}})

        def _loop(inputs):
            for _ in range(50):
                _call_llm(100, 10)
            return {"ok": True}

        work.register_kind("loop", _loop)
        item_id = work.enqueue("loop", {})
        work._execute(None, item_id)

        row = work.get_item(item_id)
        assert row["status"] == "failed" and "token budget exhausted" in row["error"]
        # Stop-loss, not a per-call cap: the call that crosses the line still
        # went out, so spend lands just above the ceiling, never far above it.
        assert 250 <= row["tokens_prompt"] + row["tokens_completion"] < 500

    def test_budget_is_not_multiplied_by_retries(self, work_env, monkeypatch, no_rate_gate):
        """Each attempt gets the REMAINDER, not a fresh allowance — otherwise
        max_attempts silently multiplies the ceiling."""
        _route_config(monkeypatch, {"work_policy": {"kinds": {"loop": {
            "token_budget": 300, "max_attempts": 3}}}})

        def _loop(inputs):
            for _ in range(50):
                _call_llm(100, 10)
            return {}

        work.register_kind("loop", _loop)
        item_id = work.enqueue("loop", {})
        work._execute(None, item_id)

        row = work.get_item(item_id)
        assert row["tokens_prompt"] + row["tokens_completion"] < 600

    def test_no_budget_means_no_ceiling(self, work_env, monkeypatch, no_rate_gate):
        _route_config(monkeypatch, {})

        def _five(inputs):
            for _ in range(5):
                _call_llm(1000, 100)
            return {"ok": True}

        work.register_kind("five", _five)
        item_id = work.enqueue("five", {})
        work._execute(None, item_id)
        assert work.get_item(item_id)["status"] == "succeeded"


class TestDailyQuota:
    def test_over_quota_work_fails_without_calling_a_model(
        self, work_env, monkeypatch, no_rate_gate
    ):
        _route_config(monkeypatch, {"work_policy": {"defaults": {"daily_token_quota": 500}}})
        ran = {"n": 0}

        def _spend(inputs):
            ran["n"] += 1
            _call_llm(400, 200)
            return {"ok": True}

        work.register_kind("spend", _spend)
        work._execute(None, work.enqueue("spend", {}))   # 600 tokens, over the line
        blocked = work.enqueue("spend", {})
        work._execute(None, blocked)

        assert ran["n"] == 1, "the blocked item must not reach the executor"
        row = work.get_item(blocked)
        assert row["status"] == "failed" and "daily token quota" in row["error"]
        assert row["llm_calls"] == 0

    def test_a_run_already_in_flight_is_not_interrupted(
        self, work_env, monkeypatch, no_rate_gate
    ):
        """The quota admits or refuses a run; it never kills one mid-flight.
        token_budget is the per-run ceiling — stopping halfway would leave a
        half-written document for a limit something else reached."""
        _route_config(monkeypatch, {"work_policy": {"defaults": {"daily_token_quota": 100}}})

        def _big(inputs):
            _call_llm(5000, 500)
            return {"ok": True}

        work.register_kind("big", _big)
        item_id = work.enqueue("big", {})
        work._execute(None, item_id)
        assert work.get_item(item_id)["status"] == "succeeded"

    def test_quota_counts_failed_runs_too(self, work_env, monkeypatch, no_rate_gate):
        """Spend that produced nothing is still spend."""
        _route_config(monkeypatch, {"work_policy": {"defaults": {"daily_token_quota": 500}}})

        def _burn(inputs):
            _call_llm(400, 200)
            raise KeyError("boom")

        work.register_kind("burn", _burn)
        work._execute(None, work.enqueue("burn", {}))
        assert work_policy.tokens_used_today() == 600
        assert work_policy.quota_status()["exceeded"] is True

    def test_no_quota_configured_reports_unlimited(self, work_env, monkeypatch):
        _route_config(monkeypatch, {})
        status = work_policy.quota_status()
        assert status["daily_token_quota"] == 0
        # None, not 0 — a dashboard must not render "0 left" for an install
        # that has no quota at all.
        assert status["remaining"] is None and status["exceeded"] is False

    def test_tokens_used_today_is_zero_before_any_work(self, work_env):
        assert work_policy.tokens_used_today() == 0
