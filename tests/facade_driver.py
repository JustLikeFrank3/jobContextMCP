"""Sync driver for the async consolidated facades.

The facades are ``async def`` (they push dispatch onto a worker thread so a
slow action can't freeze the event loop — see tools/consolidated.py and
tests/test_consolidated_async_dispatch.py). Tests that exercise a facade
end-to-end call it through here instead of sprouting per-file event-loop
boilerplate.
"""
from __future__ import annotations

from functools import partial

import anyio


def call_facade(facade, /, **kwargs):
    return anyio.run(partial(facade, **kwargs))
