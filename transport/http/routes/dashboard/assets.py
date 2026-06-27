"""Shared SVG asset helpers and /logo endpoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse, Response

from transport.http.auth import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])

_ROOT = Path(__file__).resolve().parents[4]

_LOGO_SVG_PATH   = _ROOT / "docs" / "branding" / "logo"   / "jobcontextmcp-mark-dark.svg"
_BANNER_SVG_PATH = _ROOT / "docs" / "branding" / "banner" / "banner.svg"


def logo_svg() -> str:
    try:
        return _LOGO_SVG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def banner_svg() -> str:
    try:
        return _BANNER_SVG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


@router.get("/logo", response_model=None)
async def serve_logo() -> Response:
    if _LOGO_SVG_PATH.exists():
        return FileResponse(_LOGO_SVG_PATH, media_type="image/svg+xml")
    return JSONResponse({"error": "Logo not found"}, status_code=404)
