"""Materials untracked-bucket management: associate, delete, and the MCP tool.

Route handlers are called directly (the auth dependency is exercised
elsewhere); the partition is activated through the same user-context
override the middleware uses, so the routes, lib.sync.active_sync_root, and
lib.db.get_connection all agree on the sync root — deletions must land a
file tombstone in that partition's journal.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

import lib.config as cfg
import lib.db as db
from lib import sync, user_context
from transport.http.routes.dashboard import materials as mats


@pytest.fixture()
def partition(tmp_path, monkeypatch):
    """An active per-user partition with a workspace and one tracked app."""
    root = tmp_path / "user"
    opt = root / "workspace" / "01-Current-Optimized"
    opt.mkdir(parents=True)
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps({"applications": [
            {"company": "Travelers", "role": "AI Engineer", "status": "applied"},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "STATUS_FILE", status, raising=False)
    token = user_context.set_data_folder(root)
    try:
        yield root, opt
    finally:
        user_context.reset_data_folder(token)


def _tombstones(root):
    with db.get_connection() as con:
        return sync.list_file_tombstones(con)


def _delete(name):
    return asyncio.run(
        mats.materials_untracked_delete(mats.UntrackedDeleteRequest(name=name))
    )


def _associate(name, company):
    return asyncio.run(
        mats.materials_untracked_associate(
            mats.UntrackedAssociateRequest(name=name, company=company)
        )
    )


class TestPayload:
    def test_untracked_detection_and_companies(self, partition):
        _, opt = partition
        (opt / "Travelers_AI_Engineer_Resume.txt").write_text("tracked", encoding="utf-8")
        (opt / "Orphan_Resume.txt").write_text("orphan", encoding="utf-8")
        payload = mats._materials_payload()
        assert payload["untracked_resume_files"] == ["Orphan_Resume.txt"]
        assert payload["gap"] == 1
        assert payload["tracked_companies"] == ["Travelers"]


class TestDelete:
    def test_delete_removes_file_and_records_tombstone(self, partition):
        root, opt = partition
        target = opt / "Orphan_Resume.txt"
        target.write_text("orphan", encoding="utf-8")

        resp = _delete("Orphan_Resume.txt")

        assert json.loads(resp.body) == {
            "status": "deleted", "name": "Orphan_Resume.txt", "synced": True,
        }
        assert not target.exists()
        rel = "workspace/01-Current-Optimized/Orphan_Resume.txt"
        assert rel in _tombstones(root)

    def test_delete_unknown_file_is_404(self, partition):
        with pytest.raises(HTTPException) as exc:
            _delete("nope.txt")
        assert exc.value.status_code == 404

    def test_delete_rejects_traversal(self, partition):
        root, _ = partition
        secret = root / "workspace" / "secret.txt"
        secret.write_text("keep", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _delete("../secret.txt")
        assert exc.value.status_code == 404
        assert secret.exists()


class TestAssociate:
    def test_associate_renames_and_tombstones_the_old_name(self, partition):
        root, opt = partition
        (opt / "Orphan_Resume.txt").write_text("orphan body", encoding="utf-8")

        resp = _associate("Orphan_Resume.txt", "Travelers")

        body = json.loads(resp.body)
        assert body["status"] == "associated"
        assert body["name"] == "Travelers - Orphan_Resume.txt"
        assert not (opt / "Orphan_Resume.txt").exists()
        assert (opt / "Travelers - Orphan_Resume.txt").read_text(encoding="utf-8") == "orphan body"
        # A rename is delete + create to file sync: old rel tombstoned.
        assert "workspace/01-Current-Optimized/Orphan_Resume.txt" in _tombstones(root)
        # The file now groups under the tracked application.
        assert mats._materials_payload()["untracked_resume_files"] == []

    def test_associate_requires_a_tracked_company(self, partition):
        _, opt = partition
        (opt / "Orphan_Resume.txt").write_text("x", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _associate("Orphan_Resume.txt", "NotTracked Inc")
        assert exc.value.status_code == 422
        assert (opt / "Orphan_Resume.txt").exists()

    def test_associate_refuses_to_overwrite_an_existing_file(self, partition):
        _, opt = partition
        (opt / "Orphan_Resume.txt").write_text("orphan", encoding="utf-8")
        (opt / "Travelers - Orphan_Resume.txt").write_text("existing", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _associate("Orphan_Resume.txt", "Travelers")
        assert exc.value.status_code == 409
        assert (opt / "Orphan_Resume.txt").read_text(encoding="utf-8") == "orphan"
        assert (opt / "Travelers - Orphan_Resume.txt").read_text(encoding="utf-8") == "existing"


class TestDeleteMaterialTool:
    """materials.delete — the chat-driven cleanup path (WebMCP retry orphans)."""

    def test_deletes_from_optimized_dir(self, isolated_server):
        from tools.resume import delete_material

        opt = cfg.get_active_optimized_resumes_dir()
        opt.mkdir(parents=True, exist_ok=True)
        target = opt / "Travelers_AI_Agents_Harnesses_Resume.txt"
        target.write_text("orphan", encoding="utf-8")

        out = delete_material("Travelers_AI_Agents_Harnesses_Resume.txt")

        assert out.startswith("✓ Deleted")
        assert not target.exists()

    def test_deletes_with_tombstone_when_partition_active(self, partition, monkeypatch):
        from tools.resume import delete_material

        root, opt = partition
        monkeypatch.setattr(cfg, "get_active_optimized_resumes_dir", lambda: opt)
        monkeypatch.setattr(
            cfg, "get_active_cover_letters_dir", lambda: root / "workspace" / "02-Cover-Letters"
        )
        (opt / "Orphan_Resume.txt").write_text("orphan", encoding="utf-8")

        out = delete_material("Orphan_Resume.txt")

        assert "✓ Deleted" in out and "propagate" in out
        assert "workspace/01-Current-Optimized/Orphan_Resume.txt" in _tombstones(root)

    def test_not_found_and_master_guard(self, isolated_server):
        from tools.resume import delete_material

        assert delete_material("missing.txt").startswith("✗ Not found")
        assert "Refusing" in delete_material("MASTER_resume.txt")

    def test_path_components_are_stripped(self, partition, monkeypatch):
        """A path-shaped filename must only ever address the bare name."""
        from tools.resume import delete_material

        root, opt = partition
        monkeypatch.setattr(cfg, "get_active_optimized_resumes_dir", lambda: opt)
        monkeypatch.setattr(
            cfg, "get_active_cover_letters_dir", lambda: root / "workspace" / "02-Cover-Letters"
        )
        secret = root / "workspace" / "secret.txt"
        secret.write_text("keep", encoding="utf-8")

        out = delete_material("../secret.txt")

        assert out.startswith("✗ Not found")
        assert secret.exists()


class TestMasterProtection:
    """The master resume must never be deletable or renamable through the
    untracked verbs: it is the ground truth every generation and eval checks
    against, and since file tombstones landed, a delete here would propagate
    to every synced peer and out of the mirrored backup within one tick."""

    def _master(self, opt):
        master = opt / "Frank Resume - MASTER SOURCE.txt"
        master.write_text("master", encoding="utf-8")
        return master

    def test_master_is_excluded_from_the_untracked_list(self, partition):
        _, opt = partition
        self._master(opt)
        (opt / "Orphan_Resume.txt").write_text("orphan", encoding="utf-8")
        payload = mats._materials_payload()
        assert payload["untracked_resume_files"] == ["Orphan_Resume.txt"]
        assert payload["gap"] == 1

    def test_delete_refuses_the_master(self, partition):
        root, opt = partition
        master = self._master(opt)
        with pytest.raises(HTTPException) as exc:
            _delete(master.name)
        assert exc.value.status_code == 403
        assert master.exists()
        assert not _tombstones(root)

    def test_associate_refuses_the_master(self, partition):
        _, opt = partition
        master = self._master(opt)
        with pytest.raises(HTTPException) as exc:
            _associate(master.name, "Travelers")
        assert exc.value.status_code == 403
        assert master.exists()

    def test_custom_named_master_is_protected_by_its_configured_path(
        self, partition, monkeypatch
    ):
        """A master whose name lacks the MASTER convention is still caught —
        by resolved-path comparison against the active config."""
        _, opt = partition
        custom = opt / "my-resume.txt"
        custom.write_text("master", encoding="utf-8")
        monkeypatch.setattr(cfg, "get_active_master_resume_path", lambda: custom)

        payload = mats._materials_payload()
        assert "my-resume.txt" not in payload["untracked_resume_files"]
        with pytest.raises(HTTPException) as exc:
            _delete("my-resume.txt")
        assert exc.value.status_code == 403
        assert custom.exists()

    def test_delete_material_tool_refuses_the_configured_master(
        self, partition, monkeypatch
    ):
        """Chat path, custom-named master: the name guard misses it, the
        config-path guard must not."""
        from tools.resume import delete_material

        root, opt = partition
        monkeypatch.setattr(cfg, "get_active_optimized_resumes_dir", lambda: opt)
        monkeypatch.setattr(
            cfg, "get_active_cover_letters_dir", lambda: root / "workspace" / "02-Cover-Letters"
        )
        custom = opt / "my-resume.txt"
        custom.write_text("master", encoding="utf-8")
        monkeypatch.setattr(cfg, "get_active_master_resume_path", lambda: custom)

        out = delete_material("my-resume.txt")

        assert out.startswith("✗ Refusing")
        assert "master resume" in out
        assert custom.exists()
        assert not _tombstones(root)
