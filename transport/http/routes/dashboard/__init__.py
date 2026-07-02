"""Dashboard package — assembles all sub-routers under /dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from . import api_keys, assets, digest, health, home, interviews, job_hunt, login, materials, oura, people, pipeline, posts, rejections, settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

for _sub in [assets, login, home, pipeline, job_hunt, materials, rejections, posts, people, health, digest, interviews, api_keys, oura, settings]:
    router.include_router(_sub.router)
