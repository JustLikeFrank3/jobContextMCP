"""Dashboard package — assembles all sub-routers under /dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from . import api_keys, assets, certification, digest, evals_lab, health, home, interviews, job_hunt, login, materials, oura, people, pipeline, posts, rejections, settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

for _sub in [assets, login, home, pipeline, job_hunt, materials, rejections, posts, people, health, digest, interviews, evals_lab, api_keys, oura, settings, certification]:
    router.include_router(_sub.router)
