"""AI provider settings (BYOK).

GET  /desktop/ai-provider — active provider, per-provider readiness
POST /desktop/ai-provider — save provider/key/model to the app-data config

Saves persist to config.json AND refresh the in-memory config so the next
chat/generation call uses the new provider without a restart.  Keys are
write-only: the UI never sees a stored key back, only has_key.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from transport.http.desktop.config_store import (
    _desktop_config_path,
    _read_desktop_config,
    _write_desktop_config,
)

router = APIRouter(tags=["desktop"])

AI_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "key_field": "openai_api_key",
        "model_field": "openai_model",
        "default_model": "gpt-4o-mini",
        "key_prefix": "sk-",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "key_field": "anthropic_api_key",
        "model_field": "anthropic_model",
        "default_model": "claude-sonnet-5",
        "key_prefix": "sk-ant-",
    },
    "ollama": {
        "label": "Ollama (local)",
        "key_field": None,
        "model_field": "ollama_model",
        "default_model": "llama3.1:8b",
        "key_prefix": "",
    },
}


def _ollama_running() -> bool:
    import httpx

    from lib.config import get_config_value

    base = str(get_config_value("ollama_base_url", "http://localhost:11434/v1"))
    root = base.rsplit("/v1", 1)[0]
    try:
        return httpx.get(f"{root}/api/tags", timeout=0.8).status_code == 200
    except Exception:  # noqa: BLE001 — any failure just means "not detected"
        return False


class AiProviderRequest(BaseModel):
    provider: str
    api_key: str = ""    # empty = keep the existing stored key
    model: str = ""      # empty = keep existing / provider default
    clear_key: bool = False


@router.get("/desktop/ai-provider")
async def get_ai_provider() -> dict:
    """Current provider selection + per-provider readiness (keys never echoed)."""
    from lib.config import get_active_config, get_llm_client

    cfg = get_active_config()
    client, model = get_llm_client("chat")
    active = os.environ.get("LLM_PROVIDER", str(cfg.get("llm_provider", "openai"))).lower()
    providers = {}
    for provider_id, spec in AI_PROVIDERS.items():
        providers[provider_id] = {
            "label": spec["label"],
            "has_key": bool(str(cfg.get(spec["key_field"], "") or "").strip()) if spec["key_field"] else True,
            "model": str(cfg.get(spec["model_field"], "") or spec["default_model"]),
        }
    providers["ollama"]["running"] = _ollama_running()
    return {
        "provider": active,
        "model": model or "",
        "configured": client is not None,
        "providers": providers,
    }


@router.post("/desktop/ai-provider")
async def set_ai_provider(request: AiProviderRequest) -> dict:
    """Select a provider and optionally store its key/model.

    Writes the app-data config.json and refreshes the live config, so the
    change applies to the next request without restarting the app.
    """
    spec = AI_PROVIDERS.get(request.provider)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown provider {request.provider!r}; expected one of {sorted(AI_PROVIDERS)}")

    key = request.api_key.strip()
    if key and spec["key_prefix"] and not key.startswith(spec["key_prefix"]):
        raise HTTPException(
            status_code=422,
            detail=f"That doesn't look like a {spec['label']} key (should start with {spec['key_prefix']}…).",
        )

    updates: dict[str, Any] = {"llm_provider": request.provider}
    if spec["key_field"]:
        if request.clear_key:
            updates[spec["key_field"]] = None
        elif key:
            updates[spec["key_field"]] = key
    if request.model.strip():
        updates[spec["model_field"]] = request.model.strip()

    config_path = _desktop_config_path()
    cfg = _read_desktop_config(config_path)
    for field, value in updates.items():
        if value is None:
            cfg.pop(field, None)
        else:
            cfg[field] = value
    try:
        await asyncio.to_thread(_write_desktop_config, config_path, cfg)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write {config_path}: {exc}") from exc

    from lib.config import get_llm_client, update_runtime_config

    update_runtime_config(updates)
    client, model = get_llm_client("chat")
    return {
        "status": "saved",
        "provider": request.provider,
        "model": model or "",
        "configured": client is not None,
    }
