"""Per-tenant eval loop: golden set, judge preference, triage rulings.

The suite machinery — runner, judge, critic, deterministic gates — has been
tenant-generic all along: it evaluates whatever partition context the work
row carries. What was owner-only is the *data*: the golden manifest is a
committed file describing the owner's five applications, the judge choice
is env/config that applies process-wide, and triage rulings lived in a chat
transcript. This module gives each partition its own copy of those three
things, which is what turns "the owner's eval harness" into "a product
feature every tenant gets."

Layout (everything below lives in the calling partition, so it syncs and
backs up like the rest of the workspace):

  workspace/evals/golden_dataset.json     tenant golden manifest (same schema
                                          as the committed one; reference_file
                                          may be "" — it is calibration-only)
  workspace/evals/golden/{id}-jd.txt      JD text per entry (resolve_file
                                          already searches this folder)
  workspace/evals/judge.json              judge preference (provider, model,
                                          optional key). The key is WRITE-ONLY
                                          toward pages AND encrypted at rest
                                          via lib.crypto (APP_ENCRYPTION_KEY;
                                          same guarantee as OAuth tokens, same
                                          documented cleartext degradation
                                          when no app key is configured) —
                                          not-rendering-back and
                                          not-stored-in-the-clear are
                                          different guarantees; this file
                                          carries both.
  <data>/eval_runs/triage.json            claim rulings (A/B/C/D + note),
                                          keyed by a hash of (gd_id, claim)

Judge honesty: a tenant may pick any judge to control cost, but judges are
NOT interchangeable — the calibration registry below records what has been
measured against blind human labels, and every surface showing a judge name
shows its calibration status beside it. An uncalibrated judge's scores are
comparable to its own earlier scores, not to another judge's.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from evals.golden import GoldenEntry

TRIAGE_RULINGS = ("A", "B", "C", "D")
TRIAGE_MEANINGS = {
    "A": "Fabrication — never happened; remove it",
    "B": "Misstated — real, but wrong number, place, or framing",
    "C": "Judge over-reach — the claim is fine as written",
    "D": "True but undocumented — add it to the master, then it's citable",
}

# What has actually been measured, against blind human labels on the owner's
# golden references (docs/evals.md carries the tables). Everything else is
# honestly unknown — which the default label says out loud.
# Scope discipline: these were measured on the PLATFORM's reference corpus
# (the owner's five labeled documents), not on any tenant's. Saying so in the
# label is load-bearing — "measured against blind human labels" rendered
# inside a tenant's own dashboard silently implies THEIR corpus, which is the
# same true-fact-widened-in-scope failure the entailment critic flags in
# resumes. Ruled D (true but undocumented) 2026-08-23; documented here.
JUDGE_CALIBRATION = {
    "claude-sonnet-5": ("calibrated on the platform's reference corpus (not your documents) — "
                        "accuracy MAE 1.48–1.56 vs blind human labels; best measured"),
    "gpt-4.1-mini": ("measured on the platform's reference corpus, NOT recommended — "
                     "scored accuracy a constant 5.0 (ranks nothing); MAE 3.0–3.2"),
    "llama3.1:8b": ("measured on the platform's reference corpus — accuracy MAE 3.2; "
                    "cheap drift signal only"),
}
JUDGE_UNCALIBRATED = (
    "uncalibrated — no measurement against human labels; scores are comparable "
    "only to this judge's own earlier runs, never across judges"
)


def judge_calibration_label(model: str) -> str:
    return JUDGE_CALIBRATION.get((model or "").strip(), JUDGE_UNCALIBRATED)


# ── partition paths ──────────────────────────────────────────────────────────

def _evals_dir() -> Path:
    from lib import config  # noqa: PLC0415 — late bind: workspace resolves per partition

    return Path(config.get_active_workspace_folder()) / "evals"


def _manifest_path() -> Path:
    return _evals_dir() / "golden_dataset.json"


def _jd_dir() -> Path:
    return _evals_dir() / "golden"


def _judge_prefs_path() -> Path:
    return _evals_dir() / "judge.json"


def _triage_path() -> Path:
    from evals.work import _partition_results_dir  # noqa: PLC0415 — same base the results use

    return _partition_results_dir() / "triage.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)


def _entry_jd_path(entry_id: str) -> Path:
    """A golden entry always names one file inside this tenant's JD folder."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", entry_id):
        raise ValueError("entry_id must contain only letters, numbers, hyphens or underscores")
    root = _jd_dir().resolve()
    path = (root / f"{entry_id}-jd.txt").resolve()
    if path.parent != root:
        raise ValueError("entry_id must resolve inside the golden folder")
    return path


# ── golden set ───────────────────────────────────────────────────────────────

def load_tenant_golden() -> "list[GoldenEntry] | None":
    """The partition's own golden entries, or None when the tenant has none.

    None (not []) so callers can distinguish "no set exists — fall back to
    the committed owner manifest" from "a set exists and is empty".
    """
    data = _read_json(_manifest_path(), None)
    if not isinstance(data, dict):
        return None
    entries = []
    for e in data.get("entries") or []:
        try:
            entries.append(GoldenEntry(**e))
        except TypeError:
            continue  # unknown/missing keys: skip the row, keep the set usable
    return entries


def list_tenant_entries() -> list[dict]:
    data = _read_json(_manifest_path(), None)
    if not isinstance(data, dict):
        return []
    return [e for e in (data.get("entries") or []) if isinstance(e, dict)]


def _next_entry_id(existing: list[dict]) -> str:
    taken = {str(e.get("id")) for e in existing}
    i = 1
    while f"GD-T{i:02d}" in taken:
        i += 1
    return f"GD-T{i:02d}"


def upsert_golden_entry(
    company: str,
    role: str,
    jd_text: str,
    entry_id: str = "",
    archetype: str = "",
    eval_signal: str = "",
    output_kind: str = "resume",
) -> dict:
    """Create or update one golden entry; returns the stored manifest row.

    The JD text is the load-bearing input — it is what the generator writes
    against and the judge reads. reference_file stays "" for tenant entries:
    references only matter for judge *calibration*, which needs blind human
    labels a tenant supplies later if ever.
    """
    company, role, jd_text = company.strip(), role.strip(), jd_text.strip()
    if not (company and role and jd_text):
        raise ValueError("company, role, and jd_text are all required")
    if output_kind not in ("resume", "cover_letter"):
        raise ValueError("output_kind must be 'resume' or 'cover_letter'")
    entries = list_tenant_entries()
    entry_id = entry_id.strip() or _next_entry_id(entries)
    jd_path = _entry_jd_path(entry_id)
    jd_file = jd_path.name
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text(jd_text, encoding="utf-8")
    row = {
        "id": entry_id,
        "company": company,
        "role": role,
        "archetype": archetype.strip(),
        "eval_signal": eval_signal.strip(),
        "reference_file": "",
        "jd_file": jd_file,
        "output_kind": output_kind,
    }
    entries = [e for e in entries if str(e.get("id")) != entry_id] + [row]
    _write_json(_manifest_path(), {"entries": entries})
    return row


def delete_golden_entry(entry_id: str) -> bool:
    jd_path = _entry_jd_path(entry_id)
    entries = list_tenant_entries()
    kept = [e for e in entries if str(e.get("id")) != entry_id]
    if len(kept) == len(entries):
        return False
    _write_json(_manifest_path(), {"entries": kept})
    try:
        jd_path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


# ── judge preference ─────────────────────────────────────────────────────────

_JUDGE_PROVIDERS = ("", "openai", "anthropic", "ollama")


def load_judge_prefs() -> dict:
    """{"provider": "", "model": "", "has_key": bool, "base_url": ""}.

    The stored api_key is deliberately NOT returned — pages get only the
    fact that one exists. Provider "" means "use the server default judge".
    """
    data = _read_json(_judge_prefs_path(), {})
    if not isinstance(data, dict):
        data = {}
    stored_key = str(data.get("api_key", "") or "").strip()
    return {
        "provider": str(data.get("provider", "") or "").lower(),
        "model": str(data.get("model", "") or ""),
        "base_url": str(data.get("base_url", "") or ""),
        "has_key": bool(stored_key),
        # Cleartext-at-rest is a DIFFERENT risk for a tenant-supplied key
        # than for platform-provisioned OAuth tokens — it is their secret in
        # our storage. Surfaced so the page can say so instead of implying
        # the encrypted guarantee everywhere.
        "key_plaintext_at_rest": bool(stored_key) and not stored_key.startswith("enc:v1:"),
    }


def save_judge_prefs(provider: str, model: str = "", api_key: str = "", base_url: str = "") -> dict:
    """Persist the tenant's judge choice. Empty provider clears the override.

    An empty api_key KEEPS any previously stored key (so re-saving the model
    doesn't wipe the key the user pasted once); clearing happens by clearing
    the provider.
    """
    provider = (provider or "").strip().lower()
    if provider not in _JUDGE_PROVIDERS:
        raise ValueError(f"provider must be one of {_JUDGE_PROVIDERS}")
    if not provider:
        _write_json(_judge_prefs_path(), {})
        return load_judge_prefs()
    from lib.crypto import encrypt_secret, encryption_enabled  # noqa: PLC0415

    stored = _read_json(_judge_prefs_path(), {})
    if not isinstance(stored, dict):
        stored = {}
    new_key = (api_key or "").strip()
    payload = {
        "provider": provider,
        "model": (model or "").strip(),
        "base_url": (base_url or "").strip(),
        # A newly pasted key is encrypted before it touches disk; an absent
        # one keeps whatever is stored (already-encrypted, or legacy
        # plaintext that migrates on the next paste).
        "api_key": encrypt_secret(new_key) if new_key else str(stored.get("api_key", "") or ""),
    }
    if new_key and not encryption_enabled():
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).warning(
            "tenant judge API key stored WITHOUT encryption — APP_ENCRYPTION_KEY "
            "is not configured; a tenant-supplied secret in cleartext at rest")
    _write_json(_judge_prefs_path(), payload)
    return load_judge_prefs()


def build_judge_fn():
    """A judge_fn for run_suite honoring the partition's preference, or None.

    None means "no override" — the runner uses the default judge (env/config
    resolution, the calibrated path). A stored preference builds its own
    client so the tenant's key and model apply to THEIR runs only, without
    touching the process-wide env that other partitions resolve against.
    """
    data = _read_json(_judge_prefs_path(), {})
    if not isinstance(data, dict) or not str(data.get("provider", "") or "").strip():
        return None
    from lib.crypto import decrypt_secret  # noqa: PLC0415

    provider = str(data["provider"]).lower()
    model = str(data.get("model", "") or "").strip()
    api_key = decrypt_secret(str(data.get("api_key", "") or "")).strip()
    base_url = str(data.get("base_url", "") or "").strip()

    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError:
        return None

    if provider == "anthropic":
        if not api_key:
            return None
        client = OpenAI(base_url="https://api.anthropic.com/v1/", api_key=api_key)
        model = model or "claude-sonnet-5"
    elif provider == "ollama":
        client = OpenAI(base_url=base_url or "http://localhost:11434/v1", api_key="ollama")
        model = model or "llama3.1:8b"
    else:  # openai
        if not api_key:
            return None
        client = OpenAI(api_key=api_key)
        model = model or "gpt-4o-mini"

    from evals.judge import judge_output  # noqa: PLC0415

    def _judge(jd: str, master: str, output: str):
        return judge_output(jd, master, output, client=client, model=model)

    return _judge


# ── run history (feeds the scoring visuals) ──────────────────────────────────

def results_history(limit: int = 24) -> list[dict]:
    """Compact per-run stats from the partition's stored results files.

    One dict per run, oldest first: started_at, mean (suite average of entry
    means), flags (total across runs; None — not 0 — for pre-count payloads,
    matching the wallboard's absent-is-not-zero rule), and per-dimension mean
    averages for the dimension bars. Malformed files are skipped.
    """
    from evals.work import _partition_results_dir  # noqa: PLC0415

    out: list[dict] = []
    try:
        files = sorted(_partition_results_dir().glob("results-*.json"))
    except OSError:
        return out
    for path in files[-limit:]:
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            continue
        rows = payload.get("rows") or []
        detail = payload.get("detail") or {}
        means = [float(r.get("mean") or 0) for r in rows if isinstance(r, dict) and "mean" in r]
        if not means:
            continue
        flag_counts = [
            agg.get("hallucination_flags")
            for agg in detail.values() if isinstance(agg, dict)
        ]
        flags = sum(int(f or 0) for f in flag_counts) if any(f is not None for f in flag_counts) else None
        dims: dict[str, list[float]] = {}
        for agg in detail.values():
            for dim, stats in ((agg or {}).get("per_dimension") or {}).items():
                if isinstance(stats, dict) and "mean" in stats:
                    dims.setdefault(dim, []).append(float(stats["mean"]))
        out.append({
            "started_at": str(payload.get("started_at") or ""),
            "mean": sum(means) / len(means),
            "flags": flags,
            # N rides along because a flag total is only comparable at the
            # same N — classes that fire in 1/5 runs triple their count going
            # N=1 → N=5 with zero real change. The trend panel normalizes.
            "n_runs": int(payload.get("n_runs") or 0) or None,
            # Ground-truth identity: two points are only comparable when they
            # measured the same master. "" = pre-stamp payload (unknown).
            "master_sha": str(payload.get("master_sha") or ""),
            "dimensions": {d: sum(v) / len(v) for d, v in dims.items()},
        })
    return out


# ── triage rulings ───────────────────────────────────────────────────────────

def claim_key(gd_id: str, claim: str) -> str:
    """Stable key for one flagged claim. Hash of entry + exact claim text:
    the same claim re-flagged on a later run keeps its ruling; a reworded
    claim is honestly a new one to rule on."""
    return hashlib.sha1(f"{gd_id}|{claim}".encode()).hexdigest()[:16]


def load_triage() -> dict:
    data = _read_json(_triage_path(), {})
    return data if isinstance(data, dict) else {}


def save_ruling(gd_id: str, claim: str, ruling: str, note: str = "") -> dict:
    """Store one ruling; empty ruling clears it. Returns the stored record."""
    ruling = (ruling or "").strip().upper()
    if ruling and ruling not in TRIAGE_RULINGS:
        raise ValueError(f"ruling must be one of {TRIAGE_RULINGS} or empty to clear")
    key = claim_key(gd_id, claim)
    triage = load_triage()
    if not ruling:
        triage.pop(key, None)
        _write_json(_triage_path(), triage)
        return {}
    record = {
        "gd_id": gd_id,
        "claim": claim,
        "ruling": ruling,
        "note": (note or "").strip(),
        "ruled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    triage[key] = record
    _write_json(_triage_path(), triage)
    return record
