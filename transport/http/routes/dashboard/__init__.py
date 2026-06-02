"""Dashboard package — assembles all sub-routers under /dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from . import assets, digest, health, home, job_hunt, materials, people, posts, rejections

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

for _sub in [assets, home, job_hunt, materials, rejections, posts, people, health, digest]:
    router.include_router(_sub.router)
