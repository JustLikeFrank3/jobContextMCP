import types

import pytest

from lib import openai_calls as oc


class _FakeResponse:
    def __init__(self, *, text=None, json_payload=None, headers=None, status_code=None):
        self.text = text
        self._json_payload = json_payload
        self.headers = headers or {}
        self.status_code = status_code

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class _FakeExc(Exception):
    def __init__(self, *, response=None, body=None, msg="err"):
        super().__init__(msg)
        self.response = response
        self.body = body


def test_error_payload_precedence():
    assert oc._error_payload(_FakeExc(response=_FakeResponse(text="raw text"))) == "raw text"
    assert oc._error_payload(_FakeExc(response=_FakeResponse(json_payload={"error": "x"}))) == "{'error': 'x'}"
    assert oc._error_payload(_FakeExc(body={"detail": "bad"})) == "{'detail': 'bad'}"
    assert oc._error_payload(_FakeExc(msg="fallback")) == "fallback"


def test_retry_after_seconds_header_handling():
    exc = _FakeExc(response=_FakeResponse(headers={"Retry-After": "4"}))
    assert oc._retry_after_seconds(exc, 2.0) == 4.0

    exc_bad = _FakeExc(response=_FakeResponse(headers={"retry-after": "nope"}))
    assert oc._retry_after_seconds(exc_bad, 2.0) == 2.0


def test_create_chat_completion_success(monkeypatch):
    fake_usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    fake_response = types.SimpleNamespace(usage=fake_usage)
    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **_kwargs: fake_response)
        )
    )

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc, "_LAST_CHAT_CALL", 0.0)
    monkeypatch.setattr(oc.time, "monotonic", lambda: 100.0)

    result = oc.create_chat_completion(fake_client, label="unit", model="gpt-test", max_tokens=50)
    assert result is fake_response
    assert oc._LAST_CHAT_CALL == 100.0


def test_create_chat_completion_retries_429_then_succeeds(monkeypatch):
    calls = {"n": 0}
    waits = []
    fake_usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    fake_response = types.SimpleNamespace(usage=fake_usage)

    def _create(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeExc(
                response=_FakeResponse(status_code=429, headers={"retry-after": "3"}),
                msg="rate limited",
            )
        return fake_response

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))
    )

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc, "_LAST_CHAT_CALL", 0.0)
    monkeypatch.setattr(oc.time, "monotonic", lambda: 200.0)
    monkeypatch.setattr(oc.time, "sleep", lambda s: waits.append(s))

    result = oc.create_chat_completion(fake_client, label="unit", max_attempts=3, model="gpt")
    assert result is fake_response
    assert calls["n"] == 2
    assert 3.0 in waits


def test_create_chat_completion_non_429_raises(monkeypatch):
    def _create(**_kwargs):
        raise _FakeExc(response=_FakeResponse(status_code=500), msg="boom")

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))
    )
    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oc.time, "monotonic", lambda: 300.0)

    with pytest.raises(_FakeExc):
        oc.create_chat_completion(fake_client, label="unit", max_attempts=3, model="gpt")


# ── provider-rejected sampling params (Claude 4.6+ rejects temperature) ──────

class _Rejecting400:
    """Client whose create() 400s on temperature once, then succeeds."""

    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if "temperature" in kwargs:
            exc = Exception('{"error":{"message":"`temperature` is deprecated for this model.","type":"invalid_request_error"}}')
            exc.body = {"error": {"message": "`temperature` is deprecated for this model."}}
            response = type("R", (), {"status_code": 400, "headers": {}})()
            exc.response = response
            raise exc

        class _Msg:  # minimal response shape
            content = "ok"

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]
            usage = None

        return _Resp()


def test_create_chat_completion_drops_rejected_temperature(monkeypatch):
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _Rejecting400()
    resp = oc.create_chat_completion(
        client, label="test", model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2, max_tokens=5,
    )
    assert resp.choices[0].message.content == "ok"
    assert len(client.calls) == 2
    assert "temperature" in client.calls[0]
    assert "temperature" not in client.calls[1]   # dropped on retry
    assert client.calls[1]["max_tokens"] == 5     # everything else intact


class _EmptyAtCap:
    """First call returns empty content with the cap consumed; retry succeeds."""

    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))

        class _Usage:
            prompt_tokens = 100
            total_tokens = 100 + kwargs.get("max_tokens", 0)
            completion_tokens = kwargs.get("max_tokens", 0)

        content = "" if len(self.calls) == 1 else "REAL ASSESSMENT TEXT"

        class _Msg:
            pass
        _Msg.content = content

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]
            usage = _Usage()

        return _Resp()


def test_create_chat_completion_retries_empty_content_at_cap(monkeypatch):
    """Thinking models can spend the whole completion budget on reasoning and
    return empty text — the helper must retry with a bigger budget."""
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _EmptyAtCap()
    resp = oc.create_chat_completion(
        client, label="test", model="claude-sonnet-5",
        messages=[{"role": "user", "content": "assess"}],
        max_tokens=1200,
    )
    assert resp.choices[0].message.content == "REAL ASSESSMENT TEXT"
    assert len(client.calls) == 2
    assert client.calls[1]["max_tokens"] == 4800  # 4x bump on retry


# ── per-model quirk memory (discovery cost paid once per process) ────────────

def test_rejected_param_remembered_for_next_call(monkeypatch):
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _Rejecting400()
    kwargs = dict(
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0, max_tokens=5,
    )
    oc.create_chat_completion(client, label="test", **kwargs)
    assert len(client.calls) == 2  # discovery: 400 then retry
    oc.create_chat_completion(client, label="test", **dict(kwargs))
    assert len(client.calls) == 3  # second call: no 400, temperature pre-dropped
    assert "temperature" not in client.calls[2]


def test_learned_cap_floor_applied_to_next_call(monkeypatch):
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _EmptyAtCap()
    kwargs = dict(
        model="claude-sonnet-5",
        messages=[{"role": "user", "content": "assess"}],
        max_tokens=1200,
    )
    oc.create_chat_completion(client, label="test", **kwargs)
    assert client.calls[1]["max_tokens"] == 4800  # discovery bump
    oc.create_chat_completion(client, label="test", **dict(kwargs))
    assert client.calls[2]["max_tokens"] == 4800  # floor applied preemptively
    assert len(client.calls) == 3  # no empty-at-cap retry the second time


def test_model_memory_is_per_model(monkeypatch):
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _Rejecting400()
    oc.create_chat_completion(
        client, label="test", model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0, max_tokens=5,
    )
    with pytest.raises(Exception):
        # A different model gets no inherited memory — its own discovery 400
        # (the fake rejects temperature for every model; one retry succeeds,
        # so reaching create() WITH temperature is the assertion here).
        oc.create_chat_completion(
            client, label="test", model="other-model",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.0, max_tokens=5, max_attempts=1,
        )
    assert "temperature" in client.calls[-1]


class _AlwaysRejects400:
    """400s on every call, temperature dropped or not — the retry never
    actually succeeds because of it (misattributed diagnosis)."""

    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        exc = Exception('{"error":{"message":"`temperature` is deprecated for this model.","type":"invalid_request_error"}}')
        exc.body = {"error": {"message": "`temperature` is deprecated for this model."}}
        response = type("R", (), {"status_code": 400, "headers": {}})()
        exc.response = response
        raise exc


def test_rejected_param_not_remembered_when_retry_never_succeeds(monkeypatch):
    """A 400 diagnosis that turns out wrong (the retry also fails) must not
    permanently drop the param for every future call to this model —
    otherwise one misattributed error silently stops sending it forever."""
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _AlwaysRejects400()
    with pytest.raises(Exception):
        oc.create_chat_completion(
            client, label="test", model="claude-sonnet-5",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.0, max_tokens=5, max_attempts=3,
        )
    assert oc._MODEL_REJECTED_PARAMS.get(
        oc._memory_key(client, {"model": "claude-sonnet-5"}), set()
    ) == set()

    # A later call to the SAME model still sends temperature — nothing was
    # learned from the failed attempt.
    client2 = _Rejecting400()
    oc.create_chat_completion(
        client2, label="test", model="claude-sonnet-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0, max_tokens=5,
    )
    assert "temperature" in client2.calls[0]


class _EmptyBelowFloor:
    """Returns an empty message that consumed the whole cap whenever the cap
    is under 4000 and not yet seen — so a bumped retry succeeds."""

    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self
        self._seen: set[int] = set()

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        cap = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
        empty = cap not in self._seen and cap is not None and cap < 4000
        self._seen.add(cap)
        content = None if empty else "ok"
        return type("R", (), {
            "choices": [type("C", (), {"message": type("M", (), {"content": content})()})()],
            "usage": type("U", (), {
                "prompt_tokens": 1, "completion_tokens": cap, "total_tokens": cap + 1})(),
        })()


def _client_at(url):
    c = _Rejecting400()
    c.base_url = url
    return c


def test_quirk_memory_is_not_shared_across_endpoints(monkeypatch):
    """The same model name behind two providers must not share learned
    quirks -- the judge split routinely does exactly this, and the two
    endpoints do not accept the same params. A model-only cache key let one
    provider's 400 silently strip a param from the other's requests."""
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    first = _client_at("https://api.anthropic.com/v1/")
    oc.create_chat_completion(
        first, label="test", model="shared-name",
        messages=[{"role": "user", "content": "hi"}], temperature=0.0, max_tokens=5,
    )
    # Learned there, and applied there: a second call skips the discovery 400.
    oc.create_chat_completion(
        first, label="test", model="shared-name",
        messages=[{"role": "user", "content": "hi"}], temperature=0.0, max_tokens=5,
    )
    assert "temperature" not in first.calls[-1]

    # Same model name, different endpoint: nothing inherited, so it still
    # sends temperature and pays its own discovery cost.
    other = _client_at("https://other.example/v1/")
    oc.create_chat_completion(
        other, label="test", model="shared-name",
        messages=[{"role": "user", "content": "hi"}], temperature=0.0, max_tokens=5,
    )
    assert "temperature" in other.calls[0]


def test_min_cap_floor_is_per_label(monkeypatch):
    """The empty-at-cap floor is a property of the prompt as much as the
    model: a judge call reasoning over a 30KB master needs a big budget, a
    short call does not. Keying the floor by model alone let one call site
    quietly multiply every other call site's token budget."""
    import lib.openai_calls as oc

    monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
    client = _EmptyBelowFloor()
    client.base_url = "https://api.example/v1/"
    oc.create_chat_completion(
        client, label="eval_judge", model="thinky",
        messages=[{"role": "user", "content": "hi"}], max_tokens=2000,
    )
    assert client.calls[-1]["max_tokens"] == 8000  # discovered the floor

    # Same label reuses it without re-discovering.
    oc.create_chat_completion(
        client, label="eval_judge", model="thinky",
        messages=[{"role": "user", "content": "hi"}], max_tokens=2000,
    )
    assert client.calls[-1]["max_tokens"] == 8000
    judge_calls = len(client.calls)

    # A different call site is unaffected -- it asks for what it asked for.
    oc.create_chat_completion(
        client, label="summarize", model="thinky",
        messages=[{"role": "user", "content": "hi"}], max_tokens=6000,
    )
    assert client.calls[judge_calls]["max_tokens"] == 6000


class TestCollectUsage:
    """Per-unit-of-work token attribution (control plane P2). The sink exists
    because `llm_tokens_total` is cumulative across a process's whole life —
    useful for rates, useless for "what did this job cost"."""

    def _client(self, prompt=7, completion=3):
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
            usage=types.SimpleNamespace(
                prompt_tokens=prompt, completion_tokens=completion,
                total_tokens=prompt + completion),
        )
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_k: response)))

    def test_collects_each_call(self, monkeypatch):
        monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
        client = self._client()
        with oc.collect_usage() as usage:
            oc.create_chat_completion(client, label="a", model="m1", max_tokens=10)
            oc.create_chat_completion(client, label="b", model="m2", max_tokens=10)
        assert usage == [
            {"model": "m1", "prompt": 7, "completion": 3},
            {"model": "m2", "prompt": 7, "completion": 3},
        ]

    def test_sink_is_cleared_on_exit(self, monkeypatch):
        monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
        with oc.collect_usage():
            pass
        assert oc._USAGE_SINK.get() is None

    def test_nested_blocks_attribute_to_the_inner_unit(self, monkeypatch):
        """One work item spawning another: the inner item's calls belong to the
        inner row, and the outer resumes collecting afterwards."""
        monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
        client = self._client()
        with oc.collect_usage() as outer:
            oc.create_chat_completion(client, label="outer", model="m1", max_tokens=10)
            with oc.collect_usage() as inner:
                oc.create_chat_completion(client, label="inner", model="m2", max_tokens=10)
            oc.create_chat_completion(client, label="outer", model="m3", max_tokens=10)
        assert [u["model"] for u in inner] == ["m2"]
        assert [u["model"] for u in outer] == ["m1", "m3"]

    def test_failed_call_contributes_nothing(self, monkeypatch):
        """No usage is reported for a request that never completed; the row's
        `error` is where that shows up, not a phantom zero-token entry."""
        monkeypatch.setattr(oc, "_MIN_CHAT_INTERVAL_SECONDS", 0.0)
        bad = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                create=lambda **_k: (_ for _ in ()).throw(_FakeExc(msg="down")))))
        with oc.collect_usage() as usage:
            with pytest.raises(Exception):
                oc.create_chat_completion(bad, label="x", model="m", max_tokens=10)
        assert usage == []
