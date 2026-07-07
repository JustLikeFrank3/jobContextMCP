"""Embedded chat endpoints (desktop Phase 5.5).

Mounted by create_app() only in desktop mode for now — single user,
localhost — so there are no tenancy questions in v1. The stream endpoint
speaks SSE over a POST response; the SPA consumes it with fetch + a
ReadableStream reader (EventSource only supports GET).

    POST /api/chat/sessions                → create a conversation
    GET  /api/chat/sessions                → list conversations
    GET  /api/chat/sessions/{id}/messages  → stored history
    POST /api/chat/sessions/{id}/stream    → send a message, stream events
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


class CreateSessionRequest(BaseModel):
    title: str = ""


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)


@router.get("/config")
async def chat_config() -> dict:
    """Which provider/model the chat will actually talk to.

    Derived from get_llm_client() itself (not re-read from config) so the
    indicator in the UI can never disagree with what a send would use.
    """
    from lib.config import get_active_config, get_llm_client
    import os

    client, model = get_llm_client("chat")
    provider = os.environ.get(
        "LLM_PROVIDER", str(get_active_config().get("llm_provider", "openai"))
    ).lower()
    return {
        "configured": client is not None,
        "provider": provider,
        "model": model or "",
    }


@router.post("/sessions")
async def create_session(request: CreateSessionRequest) -> dict:
    session_id = chat_service.create_session(request.title)
    return {"id": session_id}


@router.get("/sessions")
async def list_sessions() -> dict:
    return {"sessions": chat_service.list_sessions()}


@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: int) -> dict:
    if chat_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="unknown chat session")
    return {"messages": chat_service.list_messages(session_id)}


def _sse(event: chat_service.ChatEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"


@router.post("/sessions/{session_id}/stream")
async def stream_turn(session_id: int, request: SendMessageRequest) -> StreamingResponse:
    if chat_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="unknown chat session")

    import server as _server  # late import — tool registry singleton

    async def _events():
        async for event in chat_service.run_chat_turn(
            _server.mcp, session_id, request.message
        ):
            yield _sse(event)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
