"""OpenAI call helpers with usage logging and local rate smoothing."""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

_LOG = logging.getLogger(__name__)
_CHAT_LOCK = threading.Lock()
_LAST_CHAT_CALL = 0.0
_MIN_CHAT_INTERVAL_SECONDS = 12.0


def _error_payload(exc: Exception) -> str:
    """Best-effort raw OpenAI error payload for diagnostics."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            text = getattr(response, "text", None)
            if text:
                return str(text)
        except Exception:
            pass
        try:
            return str(response.json())
        except Exception:
            pass
    body = getattr(exc, "body", None)
    if body:
        return str(body)
    return str(exc)


def _retry_after_seconds(exc: Exception, fallback: float) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) if response is not None else {}
    value = None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        value = None
    if value:
        try:
            return max(float(value), fallback)
        except ValueError:
            pass
    return fallback


def create_chat_completion(client: Any, *, label: str = "chat", max_attempts: int = 3, **kwargs: Any) -> Any:
    """Create a chat completion with process-local spacing and usage logging.

    Logs requested max_tokens, actual usage, and raw 429 payloads. The lock is
    deliberately process-wide so dashboard-triggered resume/cover/fitment calls
    do not burst into the same rolling TPM/RPM window.
    """
    global _LAST_CHAT_CALL
    attempt = 0
    while True:
        attempt += 1
        with _CHAT_LOCK:
            elapsed = time.monotonic() - _LAST_CHAT_CALL
            wait = _MIN_CHAT_INTERVAL_SECONDS - elapsed
            if wait > 0:
                _LOG.info(
                    "openai.chat gate_sleep label=%s wait=%.2fs requested_max_tokens=%s",
                    label,
                    wait,
                    kwargs.get("max_tokens"),
                )
                time.sleep(wait)
            started = time.monotonic()
            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:
                _LAST_CHAT_CALL = time.monotonic()
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                payload = _error_payload(exc)
                _LOG.warning(
                    "openai.chat error label=%s attempt=%s status=%s requested_max_tokens=%s payload=%s",
                    label,
                    attempt,
                    status_code,
                    kwargs.get("max_tokens"),
                    payload,
                )
                if status_code == 429 and attempt < max_attempts:
                    backoff = _retry_after_seconds(exc, min(60.0, (2 ** attempt) + random.random()))
                    _LOG.info("openai.chat retry_sleep label=%s wait=%.2fs", label, backoff)
                    time.sleep(backoff)
                    continue
                raise

            _LAST_CHAT_CALL = time.monotonic()
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            _LOG.info(
                "openai.chat usage label=%s attempt=%s elapsed=%.2fs model=%s requested_max_tokens=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                label,
                attempt,
                time.monotonic() - started,
                kwargs.get("model"),
                kwargs.get("max_tokens"),
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            return response
