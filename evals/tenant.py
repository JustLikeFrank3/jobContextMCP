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
                                          optional key — key is WRITE-ONLY:
                                          never rendered back to a page)
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
JUDGE_CALIBRATION = {
    "claude-sonnet-5": "calibrated — accuracy MAE 1.48–1.56 vs blind human labels (best measured)",
    "gpt-4.1-mini": "measured, NOT recommended — scored accuracy a constant 5.0 (ranks nothing); MAE 3.0–3.2",
    "llama3.1:8b": "measured — accuracy MAE 3.2 vs blind human labels; cheap drift signal only",
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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
    jd_file = f"{entry_id}-jd.txt"
    jd_path = _jd_dir() / jd_file
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
    entries = list_tenant_entries()
    kept = [e for e in entries if str(e.get("id")) != entry_id]
    if len(kept) == len(entries):
        return False
    _write_json(_manifest_path(), {"entries": kept})
    try:
        (_jd_dir() / f"{entry_id}-jd.txt").unlink(missing_ok=True)
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
    return {
        "provider": str(data.get("provider", "") or "").lower(),
        "model": str(data.get("model", "") or ""),
        "base_url": str(data.get("base_url", "") or ""),
        "has_key": bool(str(data.get("api_key", "") or "").strip()),
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
    stored = _read_json(_judge_prefs_path(), {})
    if not isinstance(stored, dict):
        stored = {}
    payload = {
        "provider": provider,
        "model": (model or "").strip(),
        "base_url": (base_url or "").strip(),
        "api_key": (api_key or "").strip() or str(stored.get("api_key", "") or ""),
    }
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
    provider = str(data["provider"]).lower()
    model = str(data.get("model", "") or "").strip()
    api_key = str(data.get("api_key", "") or "").strip()
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
