"""Control-plane wiring for document generation (control-plane P1).

Every generation becomes a durable ``work_items`` row carrying the inputs it
ran on and, in its artifacts, the provenance stamp P1 asks for: the work id
(the row itself), the prompt version, and the model that produced the text.
Before this, a generated document had no record of *which* prompt or *which*
model made it — a regression in output quality was unattributable after the
fact, and "did this ship before or after the prompt change?" was unanswerable.

Interactive by design. Generation is routed through :func:`lib.work.run_now`,
not ``enqueue``: the caller is waiting for the document, so the row is created
and executed inline rather than queued behind background work. Same row, same
lifecycle, same orphan recovery — only the dispatcher is skipped. The MCP tool,
the dashboard service, and the agent fallback all keep their synchronous
contract and return the same string they always did.

The interception is a decorator on the generator functions rather than edits at
each call site. There are three callers today (``tools/consolidated.py``,
``services/resume_service.py``, ``tools/langgraph_pipeline.py``) and adding a
fourth that silently bypassed the control plane would be an easy mistake to
make; wrapping the function means there is no unwrapped path to call.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import logging
from typing import Callable

from lib import work

_log = logging.getLogger(__name__)

KIND_RESUME = "generate.resume"
KIND_COVER_LETTER = "generate.cover_letter"
KIND_ASSESSMENT = "generate.assessment"

# Deliberately NOT tracked, despite being named in the P1 roadmap entry:
# tools.fitment.assess_job_fitment and tools.interview.generate_interview_prep_context
# are context *packers* — they read the master resume and return a formatted
# prompt for the orchestrating agent to act on. No model is called and no
# document is produced, so there is no artifact to stamp and no prompt/model
# pair to attribute. A row recording "we assembled a string" would be noise in
# the exact table you query to attribute a regression. The roadmap entry
# conflated them with run_job_assessment, which does call a model.


def _default_model() -> str:
    from tools import generate  # noqa: PLC0415 — lazy: avoids import cycle

    return generate._model()


def prompt_version(system_prompt: str) -> str:
    """Short digest identifying the prompt a document was generated from.

    A hash rather than a hand-maintained constant on purpose: a version number
    someone has to remember to bump is a version number that silently goes
    stale, and the stamp is worthless the first time it lies. This changes
    exactly when the prompt text changes, and never otherwise.
    """
    return hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest()[:12]


def _bind_inputs(fn: Callable, args: tuple, kwargs: dict) -> dict:
    """Normalize a call's arguments to a JSON-storable dict.

    Positional args become named so the stored row is readable and — more
    usefully — replayable: a failed row carries everything needed to re-run it.
    """
    bound = inspect.signature(fn).bind(*args, **kwargs)
    bound.apply_defaults()
    return {k: v for k, v in bound.arguments.items() if isinstance(
        v, (str, int, float, bool, type(None)))}


def tracked(
    kind: str,
    *,
    system_prompt: Callable[[], str],
    model: "Callable[[], str] | None" = None,
    origin: str = "generate",
):
    """Route a generator through the control plane without changing its callers.

    The wrapped function keeps its name, signature, and docstring (the MCP tool
    description is read from it), so the facade and its coverage test are
    unaffected. The *undecorated* function is what the executor runs, so there
    is no recursion.

    ``model`` is per-kind because kinds do not share a model: generation reads
    ``generate._model()`` while assessment resolves its own via
    ``get_llm_client(task="assessment")``, and stamping one with the other's
    model would be worse than not stamping at all.

    ``system_prompt`` is the *base* prompt. Where a caller composes onto it —
    assessment prepends a persona block — the persona is a parameter and is
    therefore already recorded in the row's inputs, so base version + recorded
    persona reconstructs the effective prompt. Taking the composed prompt here
    instead would mean duplicating the composition logic inside the decorator.

    A failed row returns a readable error string rather than raising: these
    generators already report failure in their return value ("✗ OpenAI API
    error: …") and callers render that text directly, so raising here would
    turn a handled failure into an unhandled one.
    """
    def decorate(fn: Callable[..., str]) -> Callable[..., str]:
        resolve_model = model or _default_model

        def _executor(inputs: dict) -> dict:
            text = fn(**inputs)
            try:
                stamped_model = resolve_model()
            except Exception:  # noqa: BLE001 — an unstampable model is not a
                # reason to fail a document that was produced successfully
                stamped_model = ""
            return {
                "result": text,
                "prompt_version": prompt_version(system_prompt()),
                "model": stamped_model,
            }

        work.register_kind(kind, _executor)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> str:
            try:
                inputs = _bind_inputs(fn, args, kwargs)
            except TypeError:  # bad call — let the real function raise properly
                return fn(*args, **kwargs)
            try:
                row = work.run_now(kind, inputs, origin=origin)
            except Exception:  # noqa: BLE001 — the control plane must never
                # be the reason a document fails to generate. A row we couldn't
                # write is a lost audit record, not a lost document.
                _log.exception("control-plane wrapper failed for %s; running direct", kind)
                return fn(*args, **kwargs)
            artifacts = row.get("artifacts") or {}
            if row.get("status") == "succeeded" and "result" in artifacts:
                result = str(artifacts["result"])
                # Handled failures come back as ✗-prefixed strings with
                # status "succeeded" (the generator reported, not raised) —
                # stamping those with an audit line would dress an error up
                # as an attested success. Leave them untouched.
                if result.lstrip().startswith("✗"):
                    return result
                # Surface the audit trail on real successes (failures already
                # name their row): an agent relaying this response can show
                # its user the run went through the control plane, not around it.
                return (
                    f"{result}\n"
                    f"  control plane: work item #{row.get('id')} ({kind}) — durable audit row"
                )
            return (
                f"✗ Generation failed (work item {row.get('id')}): "
                f"{row.get('error') or 'no result recorded'}"
            )

        wrapper.work_kind = kind  # type: ignore[attr-defined]
        return wrapper

    return decorate
