"""Synthetic fixture support for eval harness regression cases.

The main golden dataset points at personal workspace files. These fixtures give
us a committed, non-sensitive corpus for smoke tests and offline validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from evals.golden import GoldenEntry

_FIXTURE_MANIFEST_PATH = Path(__file__).parent / "fixtures" / "fixture_dataset.json"


@dataclass(frozen=True)
class FixtureEntry(GoldenEntry):
    """A fixture-backed golden entry with committed corpus files."""


def load_fixture_entries() -> list[FixtureEntry]:
    data = json.loads(_FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return [FixtureEntry(**e) for e in data["entries"]]
