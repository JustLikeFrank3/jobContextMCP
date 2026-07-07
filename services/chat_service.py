"""Embedded chat: an agent loop over the MCP tool registry (desktop Phase 5.5).

Drives a tool-calling conversation against the configured LLM
(lib.config.get_llm_client — OpenAI / Azure / Ollama / Anthropic-compat):

    user message → model → [tool calls → results → model]* → assistant reply

Design constraints:
  - Curated tool surface: CHAT_TOOL_ALLOWLIST, not all 85 registered tools —
    one context window can't carry 85 schemas, and chat shouldn't reach
    admin/export-ish tools anyway. Overridable per-config via "chat_tools".
  - Tool schemas come straight from the FastMCP registry (list_tools), so
    chat stays in lockstep with tool signatures with zero re-declaration.
  - Hop cap + per-result truncation keep a confused model from spinning or
    flooding the context.
  - Events stream out as an async generator (session/delta-free MVP: whole
    messages, tool activity, done/error) — the HTTP layer turns them into
    SSE lines; tests consume the generator directly.

Persistence: chat_sessions / chat_messages via lib.db migrations v6-v7.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import anyio

from lib.db import get_connection

_log = logging.getLogger(__name__)

# Tools the chat model may call. Curated: onboarding, job-hunt state, queue,
# people, interviews, digests, generation. Nothing export-ish or admin-ish.
CHAT_TOOL_ALLOWLIST: tuple[str, ...] = (
    "check_workspace",
    "setup_workspace",
    "get_job_hunt_status",
    "get_job_queue",
    "queue_job",
    "evaluate_queued_job",
    "assess_job_fitment",
    "decide_job",
    "update_application",
    "log_application_event",
    "get_daily_digest",
    "weekly_summary",
    "search_jobs",
    "scrape_job_url",
    "get_interviews",
    "get_upcoming_interviews",
    "log_interview",
    "get_people",
    "get_person",
    "log_person",
    "get_rejections",
    "log_rejection",
    "get_compensation_comparison",
)

MAX_TOOL_HOPS = 8
MAX_TOOL_RESULT_CHARS = 8_000
MAX_HISTORY_MESSAGES = 30

_SYSTEM_PROMPT = """\
You are jobContext's built-in assistant, embedded in a local-first job search
app. You have tools that read and update the user's real job hunt data
(applications, queue, interviews, contacts, digests). Prefer calling a tool
over guessing; never invent data. Be concise and concrete. When you change
data (queue a job, log an event), confirm exactly what changed.
For a new or empty workspace, check_workspace reports what's missing and
setup_workspace fills it in from details the user gives you (contact info,
master resume content).\
"""


@dataclass
class ChatEvent:
    """One streamed event. `type` is the SSE event name."""
    type: str  # session | message | tool_call | tool_result | done | error
    data: dict[str, Any] = field(default_factory=dict)


# ── persistence ────────────────────────────────────────────────────────────────

def create_session(title: str = "") -> int:
    with get_connection() as con:
        cur = con.execute(
            "INSERT INTO chat_sessions (title) VALUES (?)", (title.strip()[:120],)
        )
        return int(cur.lastrowid)


def list_sessions() -> list[dict]:
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    with get_connection() as con:
        row = con.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def list_messages(session_id: int) -> list[dict]:
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, role, content, tool_calls, tool_call_id, tool_name, created_at "
            "FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _save_message(
    session_id: int,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    with get_connection() as con:
        con.execute(
            "INSERT INTO chat_messages (session_id, role, content, tool_calls, tool_call_id, tool_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                tool_name,
            ),
        )
        con.execute(
            "UPDATE chat_sessions SET updated_at = datetime('now'), "
            "title = CASE WHEN title = '' AND ? = 'user' THEN ? ELSE title END "
            "WHERE id = ?",
            (role, content.strip()[:120], session_id),
        )


def _history_as_openai_messages(session_id: int) -> list[dict]:
    """Rebuild the OpenAI-shaped message list from stored rows (capped)."""
    rows = list_messages(session_id)[-MAX_HISTORY_MESSAGES:]
    # Never start history with orphaned tool results (their assistant row was
    # capped away) — providers reject tool messages with no matching call.
    while rows and rows[0]["role"] == "tool":
        rows.pop(0)
    messages: list[dict] = []
    for row in rows:
        if row["role"] == "assistant" and row["tool_calls"]:
            messages.append(
                {
                    "role": "assistant",
                    "content": row["content"] or None,
                    "tool_calls": json.loads(row["tool_calls"]),
                }
            )
        elif row["role"] == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": row["tool_call_id"],
                    "content": row["content"],
                }
            )
        else:
            messages.append({"role": row["role"], "content": row["content"]})
    return messages


# ── tool surface ───────────────────────────────────────────────────────────────

def get_allowed_tool_names() -> tuple[str, ...]:
    from lib.config import get_config_value

    configured = get_config_value("chat_tools", []) or []
    if configured and isinstance(configured, list):
        return tuple(str(t) for t in configured)
    return CHAT_TOOL_ALLOWLIST


async def get_chat_tool_schemas(mcp) -> list[dict]:
    """Allowlisted MCP tools in OpenAI function-calling format."""
    allowed = set(get_allowed_tool_names())
    schemas = []
    for tool in await mcp.list_tools():
        if tool.name not in allowed:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (tool.description or "")[:1024],
                    "parameters": tool.inputSchema
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return schemas


async def _execute_tool(mcp, name: str, arguments_json: str) -> str:
    """Run one tool call; any failure comes back as text for the model."""
    if name not in set(get_allowed_tool_names()):
        return f"[error] tool {name!r} is not available in chat"
    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
    except ValueError as exc:
        return f"[error] unparseable tool arguments: {exc}"
    try:
        result = await mcp.call_tool(name, arguments)
    except Exception as exc:  # noqa: BLE001 — model must see failures, not crash the stream
        _log.warning("chat tool %s failed: %s", name, exc)
        return f"[error] {name} failed: {exc}"
    # FastMCP returns (content_blocks, structured) or just content blocks.
    blocks = result[0] if isinstance(result, tuple) else result
    parts = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    text = "\n".join(parts) or "[no output]"
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n[…truncated]"
    return text


# ── the agent loop ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    from lib.config import get_contact_name

    name = get_contact_name()
    suffix = f"\nThe user's name is {name}." if name else ""
    return _SYSTEM_PROMPT + suffix


async def run_chat_turn(
    mcp,
    session_id: int,
    user_message: str,
    client=None,
    model: str | None = None,
) -> AsyncGenerator[ChatEvent, None]:
    """Process one user message; yield events as the turn unfolds.

    `client`/`model` default to lib.config.get_llm_client() — injectable for
    tests and for a future per-request provider choice.
    """
    if client is None:
        from lib.config import get_llm_client

        client, model = get_llm_client("chat")
    if client is None:
        yield ChatEvent(
            "error",
            {
                "message": "No AI provider configured. Add an API key (or Ollama) in Settings.",
                "code": "no_llm",
            },
        )
        return

    if get_session(session_id) is None:
        yield ChatEvent("error", {"message": f"unknown chat session {session_id}", "code": "no_session"})
        return

    tools = await get_chat_tool_schemas(mcp)
    messages = [{"role": "system", "content": _build_system_prompt()}]
    messages.extend(_history_as_openai_messages(session_id))
    messages.append({"role": "user", "content": user_message})
    _save_message(session_id, "user", user_message)

    for _hop in range(MAX_TOOL_HOPS):
        try:
            response = await anyio.to_thread.run_sync(
                lambda: client.chat.completions.create(
                    model=model, messages=messages, tools=tools
                )
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors to the UI
            _log.warning("chat completion failed: %s", exc)
            yield ChatEvent("error", {"message": f"AI provider error: {exc}", "code": "provider"})
            return

        reply = response.choices[0].message

        if not reply.tool_calls:
            content = reply.content or ""
            _save_message(session_id, "assistant", content)
            yield ChatEvent("message", {"content": content})
            yield ChatEvent("done", {})
            return

        # Tool hop: persist the assistant's calls, execute each, feed back.
        calls_json = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in reply.tool_calls
        ]
        _save_message(session_id, "assistant", reply.content or "", tool_calls=calls_json)
        messages.append(
            {"role": "assistant", "content": reply.content or None, "tool_calls": calls_json}
        )

        for tc in reply.tool_calls:
            yield ChatEvent(
                "tool_call",
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments},
            )
            result_text = await _execute_tool(mcp, tc.function.name, tc.function.arguments)
            _save_message(
                session_id, "tool", result_text,
                tool_call_id=tc.id, tool_name=tc.function.name,
            )
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_text}
            )
            yield ChatEvent(
                "tool_result",
                {"id": tc.id, "name": tc.function.name, "content": result_text[:2000]},
            )

    yield ChatEvent(
        "error",
        {"message": f"Stopped after {MAX_TOOL_HOPS} tool rounds without a final answer.", "code": "hop_limit"},
    )
