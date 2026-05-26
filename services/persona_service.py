"""PersonaService: load named persona configs that bias tone/weighting/format.

Personas live in `data/personas/<name>.json`. Each persona is a static config
file (not LLM-generated) that the resume/cover-letter pipeline can pass into
the prompt or context package to bias drafting.

The service is intentionally read-only and stateless — callers fetch a
PersonaConfig and pass it through to tools or include it in the LLM prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PERSONA = "default"


@dataclass(frozen=True)
class PersonaConfig:
    """Immutable persona configuration loaded from disk."""

    name: str
    description: str
    tone_modifiers: dict[str, Any] = field(default_factory=dict)
    weighting: dict[str, float] = field(default_factory=dict)
    formatting_rules: dict[str, Any] = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Render this persona as a system-prompt fragment for an LLM."""
        lines = [
            f"# Persona: {self.name}",
            self.description,
            "",
            "## Tone modifiers",
            json.dumps(self.tone_modifiers, indent=2),
            "",
            "## Weighting",
            json.dumps(self.weighting, indent=2),
            "",
            "## Formatting rules",
            json.dumps(self.formatting_rules, indent=2),
        ]
        return "\n".join(lines)


class UnknownPersonaError(KeyError):
    """Raised when PersonaService.get is given a persona name that has no JSON file."""


class PersonaService:
    """Read-only loader for named persona configs."""

    @staticmethod
    def _user_personas_dir() -> Path:
        """User-overridable personas directory (under configured DATA_FOLDER)."""
        try:
            from lib import config as _cfg
            base = Path(_cfg.DATA_FOLDER)
        except Exception:
            base = Path("data")
        return base / "personas"

    @staticmethod
    def _bundled_personas_dir() -> Path:
        """Repo-bundled personas (shipped alongside the source tree)."""
        return Path(__file__).resolve().parent.parent / "data" / "personas"

    @staticmethod
    def _personas_dir() -> Path:
        """Resolve which personas directory to use.

        Prefer a user-customized `<DATA_FOLDER>/personas/` if it exists and
        contains at least one JSON file. Otherwise fall back to the repo-
        bundled defaults so tests and fresh installs work without copying.
        """
        user = PersonaService._user_personas_dir()
        if user.exists() and any(user.glob("*.json")):
            return user
        return PersonaService._bundled_personas_dir()

    @staticmethod
    def list_personas() -> list[str]:
        """Return sorted names of personas with a JSON file on disk."""
        d = PersonaService._personas_dir()
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    @staticmethod
    def get(name: str | None = None) -> PersonaConfig:
        """Load a persona by name. Falls back to "default" when name is None.

        Raises:
            UnknownPersonaError: If the requested persona has no JSON file.
        """
        target = name or DEFAULT_PERSONA
        d = PersonaService._personas_dir()
        path = d / f"{target}.json"
        if not path.exists():
            available = ", ".join(PersonaService.list_personas()) or "(none)"
            raise UnknownPersonaError(
                f"Unknown persona {target!r}. Available: {available}"
            )
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return PersonaConfig(
            name=data.get("name", target),
            description=data.get("description", ""),
            tone_modifiers=data.get("tone_modifiers", {}),
            weighting=data.get("weighting", {}),
            formatting_rules=data.get("formatting_rules", {}),
        )
