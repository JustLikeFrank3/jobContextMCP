"""Golden dataset loading for Layer 3.

The manifest (``golden_dataset.json``) is committed; the JD / reference
files it points to are personal data living in the user's workspace and are
resolved at run time. A missing file is reported per-entry, never fatal for
the whole suite.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_MANIFEST_PATH = Path(__file__).parent / "golden_dataset.json"


@dataclass(frozen=True)
class GoldenEntry:
    id: str
    company: str
    role: str
    archetype: str
    eval_signal: str
    reference_file: str
    jd_file: str
    output_kind: str = "resume"
    labels: dict[str, int] | None = None
    """Blind human rubric scores on the reference output (judge calibration)."""


def load_golden(manifest_path: Path | None = None) -> list[GoldenEntry]:
    """Entries from the committed manifest; [] when the manifest is absent.

    Absent happens legitimately in a frozen desktop build where the data
    file didn't travel (and is belt-and-braces even now that the spec
    ships it): the caller's no-entries handling ("add golden entries
    first") is the right user experience there — a FileNotFoundError
    from the Run button is not.
    """
    import logging  # noqa: PLC0415

    path = manifest_path or _MANIFEST_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.getLogger(__name__).warning("golden manifest missing at %s — empty set", path)
        return []
    return [GoldenEntry(**e) for e in data["entries"]]


def _candidate_dirs() -> list[Path]:
    """Workspace folders a golden file may live in, best-first."""
    from lib import config  # noqa: PLC0415 — lazy: importing config resolves the active workspace

    evals_dir = Path(__file__).resolve().parent
    dirs = [Path("."), evals_dir, evals_dir / "golden", evals_dir / "fixtures"]
    try:
        dirs.insert(0, config.get_active_optimized_resumes_dir())
    except Exception:
        pass
    try:
        workspace = config.get_active_workspace_folder()
        dirs[1:1] = [
            workspace,
            workspace / "jd",
            workspace / "evals" / "golden",
            workspace / "evals" / "fixtures",
        ]
    except Exception:
        pass
    return dirs


def resolve_file(name: str) -> Path | None:
    """Find *name* in the workspace (or as a literal path); None if absent."""
    literal = Path(name)
    if literal.is_absolute():
        return literal if literal.exists() else None
    for base in _candidate_dirs():
        candidate = base / name
        if candidate.exists():
            return candidate
    return None
