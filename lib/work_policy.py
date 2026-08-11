"""Control plane P2: execution policy as data, not as code.

Which model a kind runs on, how many times it retries and how long it waits
between attempts, what it may spend on one run, and what the tenant may spend
in a day — all of it resolved from configuration at execution time rather than
hardcoded at each call site.

The design rule is that **every default reproduces today's behavior exactly**:
one attempt, no backoff, no model override, no budget, no quota. A policy block
is opt-in, so an install that never writes one behaves as it did before P2.
That matters more than it sounds: a policy engine whose defaults change
behavior is indistinguishable from a rewrite, and there would be no way to tell
a policy bug from a regression in the work it governs.

Configuration lives in the active config (per-tenant `config.json` in that
partition, falling back to the base config), under `work_policy`::

    "work_policy": {
      "defaults": {"max_attempts": 2, "backoff_seconds": [2, 8],
                   "daily_token_quota": 2000000},
      "kinds": {
        "generate.resume": {"model": "gpt-4.1",
                            "fallback_models": ["gpt-4o-mini"],
                            "token_budget": 60000}
      }
    }

Env overrides exist only for the cloud knobs that must be settable without
editing a tenant file: `WORK_DAILY_TOKEN_QUOTA`.

Two things are deliberately NOT policy:

*Provider.* `model` reroutes the model name; it cannot reroute the vendor.
Swapping providers swaps which credential is required (foundry prefers an
explicit key over workload identity, anthropic reads another) and which vendor
receives the prompt. That is a deployment change and should look like one, not
a line in a JSON file that a tenant can edit.

*The eval judge.* `lib.config._resolve_llm_settings` ignores routing for
`task="eval_judge"`. Which model grades the golden suite is a calibrated choice
backed by an MAE table against blind human labels; letting a work policy
retarget it would invalidate that table with nothing saying so.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Substrings that mark a failure as worth another attempt. Transient by nature:
# provider throttling, timeouts, upstream 5xx, dropped connections. Anything
# else — a bad prompt, a missing file, a KeyError in an executor — will fail the
# same way on attempt two, and retrying it only doubles the cost of a bug.
_DEFAULT_RETRY_ON = (
    "429", "rate limit", "rate_limit", "too many requests",
    "timeout", "timed out",
    "502", "503", "504", "bad gateway", "service unavailable",
    "overloaded", "connection reset", "connection error", "temporarily",
)


@dataclass(frozen=True)
class Policy:
    kind: str = ""
    model: str = ""
    fallback_models: tuple[str, ...] = ()
    max_attempts: int = 1
    backoff_seconds: tuple[float, ...] = ()
    retry_on: tuple[str, ...] = _DEFAULT_RETRY_ON
    token_budget: int = 0
    daily_token_quota: int = 0

    def model_for_attempt(self, attempt: int) -> str:
        """Model to use on 1-based *attempt*, walking the fallback list.

        Attempt 1 gets `model` (empty = whatever config resolves), attempt 2
        the first fallback, and so on; past the end of the list the last
        fallback repeats rather than snapping back to the primary — a model
        that has already failed twice is not the one to try again.
        """
        chain = [self.model, *self.fallback_models]
        return chain[min(max(attempt, 1), len(chain)) - 1]

    def is_retryable(self, exc: BaseException) -> bool:
        """Whether *exc* looks transient under this policy.

        A token-budget or quota stop is never retryable no matter what the
        patterns say: retrying is precisely the thing the ceiling exists to
        prevent, and the message would match "exceeded" style patterns a
        hand-written `retry_on` might contain.
        """
        from lib.openai_calls import TokenBudgetExceeded

        if isinstance(exc, (TokenBudgetExceeded, QuotaExceeded)):
            return False
        text = f"{type(exc).__name__}: {exc}".lower()
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (429, 500, 502, 503, 504):
            return True
        return any(pattern in text for pattern in self.retry_on)

    def backoff_for_attempt(self, attempt: int) -> float:
        """Seconds to wait after a failed 1-based *attempt* (0 = no wait)."""
        if not self.backoff_seconds:
            return 0.0
        idx = min(max(attempt, 1), len(self.backoff_seconds)) - 1
        return max(0.0, float(self.backoff_seconds[idx]))


class QuotaExceeded(RuntimeError):
    """The tenant's daily token quota is already spent."""


_DEFAULT = Policy()


def _as_tuple(value, cast) -> tuple:
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            try:
                out.append(cast(item))
            except (TypeError, ValueError):
                continue
        return tuple(out)
    return ()


def _int(value, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def for_kind(kind: str, cfg: "dict | None" = None) -> Policy:
    """Resolve the policy for *kind* in the current partition.

    Layering, lowest precedence first: built-in defaults → `work_policy.defaults`
    → `work_policy.kinds[kind]` → environment. A malformed block degrades to
    the layer beneath it rather than raising: a typo in a policy file must not
    be able to stop work from running, only to fail to change how it runs.
    """
    if cfg is None:
        try:
            from lib.config import get_active_config
            cfg = get_active_config()
        except Exception:  # noqa: BLE001 — config unreadable is not fatal here
            cfg = {}
    block = cfg.get("work_policy") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        block = {}
    kinds = block.get("kinds")
    merged: dict = {}
    for layer in (block.get("defaults"),
                  kinds.get(kind) if isinstance(kinds, dict) else None):
        if isinstance(layer, dict):
            merged.update(layer)

    max_attempts = max(1, _int(merged.get("max_attempts"), _DEFAULT.max_attempts))
    quota = _int(merged.get("daily_token_quota"), _DEFAULT.daily_token_quota)
    env_quota = os.environ.get("WORK_DAILY_TOKEN_QUOTA", "").strip()
    if env_quota:
        quota = _int(env_quota, quota)
    return Policy(
        kind=kind,
        model=str(merged.get("model") or "").strip(),
        fallback_models=_as_tuple(merged.get("fallback_models"), lambda v: str(v).strip()),
        max_attempts=max_attempts,
        backoff_seconds=_as_tuple(merged.get("backoff_seconds"), float),
        retry_on=_as_tuple(merged.get("retry_on"), lambda v: str(v).lower()) or _DEFAULT_RETRY_ON,
        token_budget=_int(merged.get("token_budget"), _DEFAULT.token_budget),
        daily_token_quota=quota,
    )


def tokens_used_today() -> int:
    """Tokens spent by the current partition since midnight UTC.

    Reads the P2 accounting columns, so it counts what was actually consumed —
    including by runs that failed, which is the spend a success-only tally
    would hide. UTC because `work_items` timestamps are `datetime('now')`,
    which is UTC; a local-midnight quota would need the tenant's timezone and
    would reset at a different instant than the rows it counts.
    """
    from lib.db import get_connection

    with get_connection() as con:
        try:
            row = con.execute(
                "SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0) AS total "
                "FROM work_items WHERE finished_at >= date('now')"
            ).fetchone()
        except Exception:  # noqa: BLE001 — no table yet means nothing spent
            return 0
    return int(row["total"] if row else 0)


def check_quota(policy: Policy) -> None:
    """Raise :class:`QuotaExceeded` when the tenant is over its daily quota.

    Checked before a run starts rather than after, so an exhausted tenant costs
    nothing at all rather than one more call. A run already in flight is never
    interrupted by the quota — `token_budget` is the per-run ceiling, and
    killing work mid-flight would leave a half-written document for a limit
    that was reached by something else.
    """
    if not policy.daily_token_quota:
        return
    used = tokens_used_today()
    if used >= policy.daily_token_quota:
        raise QuotaExceeded(
            f"daily token quota reached: {used} of {policy.daily_token_quota} "
            f"tokens used today (UTC); work resumes at 00:00 UTC"
        )


def quota_status(kind: str = "") -> dict:
    """Quota snapshot for status surfaces (`GET /api/work/stats`)."""
    policy = for_kind(kind)
    used = tokens_used_today()
    quota = policy.daily_token_quota
    return {
        "tokens_used_today": used,
        "daily_token_quota": quota,
        "remaining": max(0, quota - used) if quota else None,
        "exceeded": bool(quota and used >= quota),
    }
