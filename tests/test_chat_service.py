"""Embedded chat agent loop (services/chat_service.py, desktop Phase 5.5).

The fake client mimics the OpenAI chat.completions surface closely enough
for the loop: queued responses, each either a plain message or tool calls.
MCP tool execution runs against the real registry inside isolated_server.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anyio
import pytest

from services import chat_service


# ── fake OpenAI-shaped client ─────────────────────────────────────────────────

def _tool_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _response(content: str | None = None, tool_calls=None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """Pops one queued response per completions call; records requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, model=None, messages=None, tools=None):
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        if not self._responses:
            raise AssertionError("FakeClient exhausted")
        return self._responses.pop(0)


async def _collect(gen):
    return [event async for event in gen]


def _run_turn(mcp, session_id, text, client):
    return anyio.run(
        lambda: _collect(
            chat_service.run_chat_turn(mcp, session_id, text, client=client, model="fake")
        )
    )


@pytest.fixture()
def mcp_instance(isolated_server):
    import server
    return server.mcp


# ── persistence ────────────────────────────────────────────────────────────────

def test_session_crud(isolated_server):
    sid = chat_service.create_session("hello")
    assert chat_service.get_session(sid)["title"] == "hello"
    assert [s["id"] for s in chat_service.list_sessions()] == [sid]
    assert chat_service.list_messages(sid) == []


def test_untitled_session_takes_first_user_message(isolated_server):
    sid = chat_service.create_session()
    chat_service._save_message(sid, "user", "What's my pipeline?")
    assert chat_service.get_session(sid)["title"] == "What's my pipeline?"


# ── agent loop ─────────────────────────────────────────────────────────────────

def test_plain_answer_turn(mcp_instance):
    sid = chat_service.create_session()
    client = FakeClient([_response(content="Hi Frank!")])

    events = _run_turn(mcp_instance, sid, "hello", client)

    assert [e.type for e in events] == ["message", "done"]
    assert events[0].data["content"] == "Hi Frank!"
    rows = chat_service.list_messages(sid)
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "hello"), ("assistant", "Hi Frank!"),
    ]
    # System prompt leads, tools passed through in OpenAI format.
    request = client.requests[0]
    assert request["messages"][0]["role"] == "system"
    names = {t["function"]["name"] for t in request["tools"]}
    assert "applications" in names
    assert names <= set(chat_service.CHAT_TOOL_ALLOWLIST)


def test_tool_call_turn_roundtrip(mcp_instance):
    sid = chat_service.create_session()
    client = FakeClient([
        _response(tool_calls=[_tool_call("c1", "applications", {"action": "status"})]),
        _response(content="You have N active applications."),
    ])

    events = _run_turn(mcp_instance, sid, "how's my pipeline?", client)

    assert [e.type for e in events] == ["tool_call", "tool_result", "message", "done"]
    assert events[0].data["name"] == "applications"
    # Real tool executed against the isolated workspace: non-empty, no error.
    assert events[1].data["content"].strip()
    assert not events[1].data["content"].startswith("[error]")

    # Second model request carries the assistant tool_calls + tool result.
    followup = client.requests[1]["messages"]
    assert followup[-2]["role"] == "assistant"
    assert followup[-2]["tool_calls"][0]["function"]["name"] == "applications"
    assert followup[-1]["role"] == "tool"
    assert followup[-1]["tool_call_id"] == "c1"

    # History persisted in OpenAI-reconstructable shape.
    roles = [r["role"] for r in chat_service.list_messages(sid)]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_disallowed_tool_becomes_error_result(mcp_instance):
    sid = chat_service.create_session()
    client = FakeClient([
        _response(tool_calls=[_tool_call("c1", "write_latex_section", {"x": 1})]),
        _response(content="Sorry, can't."),
    ])

    events = _run_turn(mcp_instance, sid, "hack the latex", client)

    result = next(e for e in events if e.type == "tool_result")
    assert "not available in chat" in result.data["content"]
    assert events[-1].type == "done"


def test_hop_limit_terminates_loop(mcp_instance):
    sid = chat_service.create_session()
    looping = [
        _response(tool_calls=[_tool_call(f"c{i}", "get_job_hunt_status", {})])
        for i in range(chat_service.MAX_TOOL_HOPS + 1)
    ]
    client = FakeClient(looping)

    events = _run_turn(mcp_instance, sid, "loop forever", client)

    assert events[-1].type == "error"
    assert events[-1].data["code"] == "hop_limit"
    assert len(client.requests) == chat_service.MAX_TOOL_HOPS


def test_no_llm_configured(mcp_instance):
    sid = chat_service.create_session()
    events = anyio.run(
        lambda: _collect(
            chat_service.run_chat_turn(mcp_instance, sid, "hi", client=None, model=None)
        )
    )
    assert [e.type for e in events] == ["error"]
    assert events[0].data["code"] == "no_llm"


def test_unknown_session_errors(mcp_instance):
    client = FakeClient([])
    events = _run_turn(mcp_instance, 999_999, "hi", client)
    assert events[0].data["code"] == "no_session"


def test_provider_exception_surfaces_as_error(mcp_instance):
    sid = chat_service.create_session()

    class ExplodingClient(FakeClient):
        def _create(self, **_kwargs):
            raise RuntimeError("rate limited")

    events = _run_turn(mcp_instance, sid, "hi", ExplodingClient([]))
    assert events[-1].type == "error"
    assert events[-1].data["code"] == "provider"


def test_history_replays_into_next_turn(mcp_instance):
    sid = chat_service.create_session()
    _run_turn(mcp_instance, sid, "hello", FakeClient([_response(content="Hi!")]))

    client = FakeClient([_response(content="Again!")])
    _run_turn(mcp_instance, sid, "and again", client)

    sent = client.requests[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "hello"
    assert sent[2]["content"] == "Hi!"


def test_dangling_tool_calls_get_synthesized_results(mcp_instance):
    """A turn that died between saving the assistant tool_calls row and its
    tool results permanently poisoned the session: every later replay was a
    provider 400 ('tool_call_ids did not have response messages'). The repair
    synthesizes interruption results so the session stays usable."""
    sid = chat_service.create_session()
    chat_service._save_message(sid, "user", "run something")
    chat_service._save_message(
        sid, "assistant", "",
        tool_calls=[{"id": "toolu_dead", "type": "function",
                     "function": {"name": "applications", "arguments": "{}"}}],
    )
    # no tool result row — the crash

    client = FakeClient([_response(content="Recovered.")])
    events = _run_turn(mcp_instance, sid, "Hello?", client)

    assert any(e.type == "message" for e in events)
    sent = client.requests[0]["messages"]
    idx = next(i for i, m in enumerate(sent) if m["role"] == "assistant" and m.get("tool_calls"))
    follow = sent[idx + 1]
    assert follow["role"] == "tool" and follow["tool_call_id"] == "toolu_dead"
    assert "interrupted" in follow["content"]


def test_orphaned_tool_results_are_dropped():
    """Tool results whose calls were capped away (or saved out of order) are
    removed anywhere in history, not only at the head."""
    messages = [
        {"role": "tool", "tool_call_id": "gone", "content": "stale"},
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "also-gone", "content": "stale"},
        {"role": "assistant", "content": "hello"},
    ]
    repaired = chat_service._repair_tool_pairing(messages)
    assert [m["role"] for m in repaired] == ["user", "assistant"]


def test_well_formed_history_passes_through_unchanged():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "a", "type": "function",
                         "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "done"},
        {"role": "assistant", "content": "all set"},
    ]
    assert chat_service._repair_tool_pairing(list(messages)) == messages


# ── HTTP endpoints (desktop-gated) ─────────────────────────────────────────────

def test_chat_routes_absent_outside_desktop_mode(http_client_noauth):
    assert http_client_noauth.get("/api/chat/sessions").status_code in (404, 405)


@pytest.fixture()
def desktop_client(monkeypatch, isolated_server):
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    monkeypatch.delenv("API_KEY", raising=False)
    reset_settings_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_settings_cache()


def test_chat_http_session_lifecycle(desktop_client):
    created = desktop_client.post("/api/chat/sessions", json={"title": "t"})
    assert created.status_code == 200
    sid = created.json()["id"]

    listed = desktop_client.get("/api/chat/sessions").json()["sessions"]
    assert [s["id"] for s in listed] == [sid]

    messages = desktop_client.get(f"/api/chat/sessions/{sid}/messages")
    assert messages.status_code == 200
    assert messages.json() == {"messages": []}

    assert desktop_client.get("/api/chat/sessions/424242/messages").status_code == 404


def test_chat_config_endpoint(desktop_client, monkeypatch):
    # Offline conftest stub: get_llm_client → (None, None) ⇒ unconfigured.
    # Ambient LLM_PROVIDER (e.g. foundry in the deploy pipeline's test job)
    # overrides config in the endpoint — clear it so the assert sees config.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = desktop_client.get("/api/chat/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["provider"] == "openai"


@pytest.mark.live_llm  # opts out of the autouse get_llm_client stub; no network involved
def test_anthropic_provider_branch(monkeypatch):
    import lib.config as config_module

    monkeypatch.setattr(
        config_module, "get_active_config",
        lambda: {"llm_provider": "anthropic", "anthropic_api_key": "sk-ant-test"},
    )
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    client, model = config_module.get_llm_client("chat")
    assert client is not None
    assert "api.anthropic.com" in str(client.base_url)
    assert model == "claude-sonnet-5"

    # No key → graceful degrade, same as the openai branch.
    monkeypatch.setattr(
        config_module, "get_active_config", lambda: {"llm_provider": "anthropic"}
    )
    client, model = config_module.get_llm_client("chat")
    assert client is None


def test_chat_http_stream_no_llm(desktop_client):
    """End-to-end SSE: with no key configured the stream yields one error event."""
    sid = desktop_client.post("/api/chat/sessions", json={}).json()["id"]
    resp = desktop_client.post(f"/api/chat/sessions/{sid}/stream", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: error" in resp.text
    assert "no_llm" in resp.text
