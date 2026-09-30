"""Slow model requests must not starve health probes or lose tenant context."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from lib import user_context
from transport.http.auth import require_api_key
from transport.http.routes.dashboard import pipeline


@pytest.mark.parametrize("action", ["generate-resume", "generate-cover-letter", "evaluate"])
def test_health_responds_while_generation_waits(action, monkeypatch, tmp_path):
    started, release = threading.Event(), threading.Event()
    seen = {}

    def slow_model(**kwargs):
        seen["oid"] = user_context.get_current_user_oid()
        seen["folder"] = user_context.get_data_folder_override()
        started.set()
        # Simulates both synchronous network I/O and SDK rate-limit retry sleep.
        if not release.wait(3):
            raise RuntimeError("Generation blocked the health request")
        return SimpleNamespace(success=True, content="generated", notes=[], provenance={},
                               company="Acme", role="Engineer", queue_status="evaluated",
                               evaluated=True, fitment_context="assessment")

    monkeypatch.setattr(pipeline.ResumeService, "generate", slow_model)
    monkeypatch.setattr(pipeline.JobAnalysisService, "evaluate", slow_model)
    monkeypatch.setattr(pipeline, "_find_job", lambda _: {
        "company": "Acme", "role": "Engineer", "jd": "test", "selected_resume": "saved.md"})
    monkeypatch.setattr(pipeline, "_update_job", lambda *args: None)
    app = FastAPI()
    app.dependency_overrides[require_api_key] = lambda: None
    app.include_router(pipeline.router, prefix="/dashboard")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    async def run():
        oid = user_context.set_user_oid("tenant-generation")
        folder = user_context.set_data_folder(tmp_path)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                job = asyncio.create_task(client.post(f"/dashboard/pipeline/{action}", json={"job_id": 1, "export_pipeline": "html"}))
                try:
                    while not started.is_set():
                        if job.done():
                            raise AssertionError(f"Generation ended before model call: {await job}")
                        await asyncio.sleep(0.01)
                    response = await asyncio.wait_for(client.get("/health"), timeout=1)
                    assert response.status_code == 200
                    assert not job.done(), "Health was delayed until generation finished"
                finally:
                    release.set()
                result = await job
                assert result.status_code == 200
                assert result.json()["ok"]
        finally:
            user_context.reset_data_folder(folder)
            user_context.reset_user_oid(oid)

    asyncio.run(run())
    assert seen == {"oid": "tenant-generation", "folder": tmp_path}
