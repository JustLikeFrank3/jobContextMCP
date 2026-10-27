"""Filename arguments to the materials/documents tools must stay inside the
caller's own partition.

These tools join a client-supplied ``filename`` onto a per-tenant directory.
Without a containment check, ``../`` or an absolute path escapes the tenant
folder — letting one tenant read or overwrite another tenant's files, or read
arbitrary server files (``/proc/self/environ`` etc.). The regressions below
assert the escape is refused while a normal filename still works.
"""
from __future__ import annotations

import pytest

from lib import config, user_context
from lib.helpers import UnsafePathError, contained_path


@pytest.fixture()
def two_partitions(tmp_path):
    """A root holding an attacker partition (active) and a victim partition."""
    for oid in ("oid-attacker", "oid-victim"):
        (tmp_path / "data" / "users" / oid / "workspace" / "01-Current-Optimized").mkdir(
            parents=True
        )
    victim_secret = (
        tmp_path
        / "data"
        / "users"
        / "oid-victim"
        / "workspace"
        / "01-Current-Optimized"
        / "Resume - MASTER SOURCE.txt"
    )
    victim_secret.write_text("VICTIM PII 555-0100", encoding="utf-8")
    token = user_context.set_data_folder(tmp_path / "data" / "users" / "oid-attacker")
    try:
        yield tmp_path, victim_secret
    finally:
        user_context.reset_data_folder(token)


def test_contained_path_blocks_traversal_and_absolute(tmp_path):
    base = tmp_path / "base"
    (base / "ok.txt").parent.mkdir(parents=True, exist_ok=True)
    assert contained_path(base, "ok.txt") == (base.resolve() / "ok.txt")
    assert contained_path(base, "sub/ok.txt") == (base.resolve() / "sub" / "ok.txt")
    for bad in ("../escape.txt", "../../etc/passwd", "/etc/passwd", "a/../../x"):
        with pytest.raises(UnsafePathError):
            contained_path(base, bad)


def test_read_resume_cannot_escape_partition(two_partitions):
    from tools.resume import read_existing_resume

    rel = "../../oid-victim/workspace/01-Current-Optimized/Resume - MASTER SOURCE.txt"
    out_rel = read_existing_resume(rel)
    out_abs = read_existing_resume(str(two_partitions[1]))
    assert "VICTIM PII" not in out_rel
    assert "VICTIM PII" not in out_abs


def test_read_reference_cannot_read_server_files(two_partitions):
    from tools.resume import read_reference_file

    assert "root:" not in read_reference_file("/etc/passwd")


def test_save_resume_cannot_overwrite_victim(two_partitions):
    from tools.resume import save_resume_txt

    victim = two_partitions[1]
    victim.write_text("ORIGINAL", encoding="utf-8")
    save_resume_txt(
        "../../oid-victim/workspace/01-Current-Optimized/Resume - MASTER SOURCE",
        "ATTACKER WAS HERE",
    )
    assert victim.read_text(encoding="utf-8") == "ORIGINAL"


def test_normal_filename_still_works(two_partitions):
    from tools.resume import read_existing_resume, save_resume_txt

    msg = save_resume_txt("My Tailored Resume.txt", "hello world")
    assert "saved" in msg.lower()
    assert "hello world" in read_existing_resume("My Tailored Resume.txt")
