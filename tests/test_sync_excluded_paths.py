"""The file-sync endpoints must refuse config.json and the SQLite database.

config.json carries machine-local settings that can repoint the server's own
LLM credential (azure_foundry_endpoint) and the active folders; the database
is owned by the row journal, not file sync. A crafted /files/put must not be
able to smuggle either into a partition. Ordinary workspace files still sync.
"""
from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from lib import user_context
from transport.http.routes import sync as sync_routes


@pytest.fixture()
def partition(tmp_path):
    root = tmp_path / "data" / "users" / "oid-a"
    root.mkdir(parents=True)
    token = user_context.set_data_folder(root)
    try:
        yield root
    finally:
        user_context.reset_data_folder(token)


def _put(rel: str, content: bytes = b"x"):
    import asyncio

    return asyncio.run(
        sync_routes.sync_files_put(
            sync_routes.FilePut(rel=rel, content_b64=base64.b64encode(content).decode()),
            user=None,
        )
    )


@pytest.mark.parametrize(
    "rel",
    [
        "config.json",
        "db/jobcontextmcp.db",
        "db/anything.db",
        "workspace/notes.db",
        "./config.json",
        "db/../config.json",
    ],
)
def test_excluded_paths_refused(partition, rel):
    with pytest.raises(HTTPException) as exc:
        _put(rel)
    assert exc.value.status_code == 422
    assert not (partition / "config.json").exists()


def test_ordinary_workspace_file_still_syncs(partition):
    out = _put("workspace/01-Current-Optimized/Resume.txt", b"hello")
    assert out["status"] == "stored"
    assert (partition / "workspace" / "01-Current-Optimized" / "Resume.txt").read_bytes() == b"hello"
