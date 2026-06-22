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
