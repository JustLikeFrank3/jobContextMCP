"""The consolidated facades must not block the event loop.

FastMCP calls SYNC tools directly on the event loop
(mcp/server/fastmcp/utilities/func_metadata.py: ``return fn(**arguments)``),
so when the facades were plain ``def``, a slow action — LLM generation, an
assessment — froze the whole server for the call's duration. Health probes
went unanswerable and the kubelet liveness-killed a healthy prod pod
mid-generation, twice, on 2026-08-27; readiness had been flapping the same
way on every LLM call all day.

The facades are therefore ``async def`` and push ``_run`` onto a worker
thread via anyio. These tests pin all three load-bearing properties:
the facades are coroutines, the loop stays responsive while an action
runs, and the per-request partition contextvars survive the thread hop
(the reason bare run_in_executor stays forbidden — see lib/user_context.py
and the PR #90 partition-escape post-mortem).
"""
from __future__ import annotations

import inspect
import time

import anyio
import pytest

import tools.consolidated as consolidated
from lib import user_context


class TestFacadesAreCoroutines:
    def test_every_registered_facade_is_async(self):
        for name, fn in consolidated.FACADES.items():
            assert inspect.iscoroutinefunction(fn), (
                f"facade {name!r} is sync — FastMCP would run it on the event "
                "loop and a slow action would freeze the whole server"
            )


class TestLoopStaysResponsive:
    """A deliberately slow action must not starve concurrently running tasks."""

    SLEEP = 0.6
    TICK = 0.02

    @pytest.fixture()
    def slow_checkin(self, monkeypatch):
        def _slow(mood=None, energy=None, notes="", productive=False):
            time.sleep(self.SLEEP)
            return "slept"

        monkeypatch.setitem(consolidated.DOMAINS["wellbeing"], "checkin", (_slow, "slow stub"))

    def _ticks_during(self, work) -> int:
        """Run `work` (an async fn) alongside a heartbeat; count heartbeats."""
        ticks = 0

        async def main():
            nonlocal ticks
            async with anyio.create_task_group() as tg:
                stop = anyio.Event()

                async def heartbeat():
                    nonlocal ticks
                    while not stop.is_set():
                        await anyio.sleep(self.TICK)
                        ticks += 1

                tg.start_soon(heartbeat)
                await work()
                stop.set()

        anyio.run(main)
        return ticks

    def test_control_sync_dispatch_starves_the_loop(self, slow_checkin):
        """Documents the OLD behavior: _run inline on the loop stops time."""

        async def blocking_work():
            consolidated._run("wellbeing", "checkin", {"mood": 8, "energy": 7})

        ticks = self._ticks_during(blocking_work)
        assert ticks <= 2, "inline sync dispatch unexpectedly yielded to the loop"

    def test_async_facade_keeps_the_loop_alive(self, slow_checkin):
        async def offloaded_work():
            result = await consolidated.wellbeing(action="checkin", mood=8, energy=7)
            assert result == "slept"

        ticks = self._ticks_during(offloaded_work)
        # ~0.6s of work at a 20ms heartbeat should yield dozens of ticks; a
        # generous floor keeps slow CI honest without flaking.
        assert ticks >= 10, f"loop starved during facade call (ticks={ticks})"


class TestContextvarsSurviveTheThreadHop:
    def test_partition_context_visible_inside_worker_thread(self, monkeypatch):
        seen: dict[str, str] = {}

        def _capture():
            seen["oid"] = user_context.get_current_user_oid()
            seen["folder"] = str(user_context.get_data_folder_override())
            return "captured"

        monkeypatch.setitem(consolidated.DOMAINS["workspace"], "check", (_capture, "capture stub"))

        async def main():
            oid_token = user_context.set_user_oid("tenant-async-test")
            folder_token = user_context.set_data_folder("/tmp/tenant-async-test")
            try:
                return await consolidated.workspace(action="check")
            finally:
                user_context.reset_data_folder(folder_token)
                user_context.reset_user_oid(oid_token)

        result = anyio.run(main)
        assert result == "captured"
        assert seen["oid"] == "tenant-async-test"
        assert seen["folder"] == "/tmp/tenant-async-test"
