"""Persona configuration endpoints (read-only)."""

from fastapi import APIRouter, Depends, HTTPException

from services import PersonaService, UnknownPersonaError
from transport.http.auth import require_api_key


router = APIRouter(
    prefix="/personas",
    tags=["personas"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
async def list_personas() -> dict[str, list[str]]:
    return {"personas": PersonaService.list_personas()}


@router.get("/{name}", responses={404: {"description": "Persona not found"}})
async def get_persona(name: str) -> dict:
    try:
        p = PersonaService.get(name)
    except UnknownPersonaError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "name": p.name,
        "description": p.description,
        "tone_modifiers": p.tone_modifiers,
        "weighting": p.weighting,
        "formatting_rules": p.formatting_rules,
    }
