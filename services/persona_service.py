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

_BUILTIN_PERSONAS: dict[str, dict[str, Any]] = {
    "default": {
        "name": "default",
        "description": "Neutral baseline persona: concise, evidence-led, no AI tells, no em dashes, ellipses for natural connective tissue.",
        "tone_modifiers": {
            "register": "professional-conversational",
            "voice": "first-person where appropriate, active verbs, short sentences",
            "banned_phrases": [
                "I hope this finds you well",
                "I wanted to reach out",
                "I am excited to",
                "I trust this email finds you",
                "synergy",
                "leverage cross-functional",
            ],
            "preferred_punctuation": {
                "flow_connector": "ellipsis",
                "no_em_dash": True,
                "no_hyphen_connector": True,
                "no_emoji": True,
            },
        },
        "weighting": {
            "recent_experience_boost": 1.0,
            "leadership_keywords_boost": 1.0,
            "ic_keywords_boost": 1.0,
            "domain_keywords_boost": 1.0,
        },
        "formatting_rules": {
            "bullet_max_lines": 2,
            "lead_with_credential": True,
            "low_commitment_close": True,
            "summary_word_target": 60,
        },
    },
    "executive_polish": {
        "name": "executive_polish",
        "description": "Director / VP / C-suite framing: outcomes, P&L, org scope, strategic narrative. Tighter, more declarative.",
        "tone_modifiers": {
            "register": "executive-formal",
            "voice": "outcome-first, third-person business-impact phrasing, fewer first-person verbs",
            "banned_phrases": [
                "I hope this finds you well",
                "I wanted to reach out",
                "I am excited to",
                "I trust this email finds you",
                "passionate about",
            ],
            "preferred_punctuation": {
                "flow_connector": "semicolon",
                "no_em_dash": True,
                "no_hyphen_connector": True,
                "no_emoji": True,
            },
        },
        "weighting": {
            "recent_experience_boost": 1.1,
            "leadership_keywords_boost": 1.5,
            "ic_keywords_boost": 0.6,
            "domain_keywords_boost": 1.0,
        },
        "formatting_rules": {
            "bullet_max_lines": 2,
            "lead_with_credential": True,
            "low_commitment_close": False,
            "summary_word_target": 80,
            "metrics_required_per_bullet": True,
        },
    },
    "faang_technical": {
        "name": "faang_technical",
        "description": "Big-tech senior/staff IC framing: systems, scale, ambiguity, cross-team influence. STAR bullets with quantified scope.",
        "tone_modifiers": {
            "register": "technical-precise",
            "voice": "active verbs, system-and-scale nouns, avoid superlatives",
            "banned_phrases": [
                "I hope this finds you well",
                "I wanted to reach out",
                "rockstar",
                "ninja",
                "guru",
            ],
            "preferred_punctuation": {
                "flow_connector": "ellipsis",
                "no_em_dash": True,
                "no_hyphen_connector": True,
                "no_emoji": True,
            },
        },
        "weighting": {
            "recent_experience_boost": 1.0,
            "leadership_keywords_boost": 0.8,
            "ic_keywords_boost": 1.5,
            "domain_keywords_boost": 1.2,
        },
        "formatting_rules": {
            "bullet_max_lines": 2,
            "lead_with_credential": True,
            "low_commitment_close": True,
            "summary_word_target": 70,
            "star_bullets_required": True,
            "metrics_required_per_bullet": True,
        },
    },
    "startup_founder": {
        "name": "startup_founder",
        "description": "Early-stage / founder-adjacent framing: range, scrappy ownership, 0-to-1 stories, momentum verbs.",
        "tone_modifiers": {
            "register": "founder-direct",
            "voice": "first-person ownership, momentum verbs (shipped, owned, built), no corporate hedging",
            "banned_phrases": [
                "I hope this finds you well",
                "I wanted to reach out",
                "responsible for",
                "tasked with",
            ],
            "preferred_punctuation": {
                "flow_connector": "ellipsis",
                "no_em_dash": True,
                "no_hyphen_connector": True,
                "no_emoji": True,
            },
        },
        "weighting": {
            "recent_experience_boost": 1.2,
            "leadership_keywords_boost": 1.1,
            "ic_keywords_boost": 1.2,
            "domain_keywords_boost": 1.0,
        },
        "formatting_rules": {
            "bullet_max_lines": 2,
            "lead_with_credential": True,
            "low_commitment_close": True,
            "summary_word_target": 55,
            "metrics_required_per_bullet": False,
        },
    },
}


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
        from lib.user_context import get_data_folder_override

        try:
            from lib import config as _cfg
            base = get_data_folder_override() or Path(_cfg.DATA_FOLDER)
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
        if d.exists():
            names = sorted(p.stem for p in d.glob("*.json"))
            if names:
                return names
        return sorted(_BUILTIN_PERSONAS.keys())

    @staticmethod
    def _from_data(target: str, data: dict[str, Any]) -> PersonaConfig:
        return PersonaConfig(
            name=data.get("name", target),
            description=data.get("description", ""),
            tone_modifiers=data.get("tone_modifiers", {}),
            weighting=data.get("weighting", {}),
            formatting_rules=data.get("formatting_rules", {}),
        )

    @staticmethod
    def get(name: str | None = None) -> PersonaConfig:
        """Load a persona by name. Falls back to "default" when name is None.

        Raises:
            UnknownPersonaError: If the requested persona has no JSON file.
        """
        target = name or DEFAULT_PERSONA
        d = PersonaService._personas_dir()
        path = d / f"{target}.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return PersonaService._from_data(target, data)

        builtin = _BUILTIN_PERSONAS.get(target)
        if builtin is not None:
            return PersonaService._from_data(target, builtin)

        available = ", ".join(PersonaService.list_personas()) or "(none)"
        raise UnknownPersonaError(
            f"Unknown persona {target!r}. Available: {available}"
        )
