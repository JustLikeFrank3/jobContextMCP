"""badge/install.py against a fake /Volumes/BADGER.

The menu source below is the apps list exactly as it ships on the badge
(read off the hardware 2026-10-02); the installer's whole job is editing it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "badge" / "install.py"

STOCK_MENU = '''from icon import Icon
import ui

apps = [
    ("mona's quest", "quest"),
    ("mona pet", "monapet"),
    ("monasketch", "sketch"),
    ("flappy mona", "flappy"),
    ("gallery", "gallery"),
    ("badge", "badge"),
]

mona = SpriteSheet("/system/assets/mona-sprites/mona-default.png", 11, 1)
'''


@pytest.fixture()
def installer(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("badge_install", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "BACKUP_ROOT", tmp_path / "backups")
    # CI has no mpy-cross; stand in a compiler that records what it built.
    monkeypatch.setattr(mod, "find_mpy_cross", lambda: "fake-mpy-cross")
    monkeypatch.setattr(
        mod, "compile_module", lambda exe, src, dst: dst.write_bytes(b"MPY:" + src.name.encode())
    )
    return mod


@pytest.fixture()
def volume(tmp_path):
    vol = tmp_path / "BADGER"
    (vol / "apps/menu").mkdir(parents=True)
    (vol / "apps/menu/__init__.py").write_text(STOCK_MENU)
    (vol / "apps/gallery/images").mkdir(parents=True)
    (vol / "apps/gallery/__init__.py").write_text("# gallery")
    (vol / "apps/gallery/images/duck.png").write_bytes(b"png")
    return vol


def test_patch_swaps_the_slot_in_place(installer):
    out = installer.patch_menu(STOCK_MENU, "gallery")
    assert installer.listed_apps(out) == ["quest", "monapet", "sketch", "flappy", "jobcontext", "badge"]
    assert '    ("jobcontext", "jobcontext"),\n    ("badge", "badge"),' in out


def test_patch_is_idempotent(installer):
    once = installer.patch_menu(STOCK_MENU, "gallery")
    assert installer.patch_menu(once, "gallery") == once


def test_patch_refuses_an_unknown_target(installer):
    with pytest.raises(installer.InstallError, match="no \"nope\" entry"):
        installer.patch_menu(STOCK_MENU, "nope")


def test_patch_refuses_an_unrecognised_menu(installer):
    with pytest.raises(installer.InstallError, match="unknown firmware"):
        installer.patch_menu("print('hi')\n", "gallery")


def test_install_then_restore_round_trips(installer, volume):
    installer.install(volume, "gallery", dry_run=False)

    assert not (volume / "apps/gallery").exists()
    app = volume / "apps/jobcontext"
    for src, dst in installer.MODULES.items():
        assert (app / dst).read_bytes() == b"MPY:" + src.encode(), dst
    assert (app / "__init__.py").read_text() == installer.LOADER
    assert (app / "icon.png").is_file()
    assert not (app / "secrets.example.py").exists()
    assert "jobcontext" in installer.listed_apps((volume / "apps/menu/__init__.py").read_text())

    (saved,) = (installer.BACKUP_ROOT).iterdir()
    assert (saved / "apps/gallery/images/duck.png").read_bytes() == b"png"

    installer.restore(volume, saved, dry_run=False)
    assert (volume / "apps/menu/__init__.py").read_text() == STOCK_MENU
    assert (volume / "apps/gallery/images/duck.png").is_file()
    assert not (volume / "apps/jobcontext").exists()


def test_dry_run_writes_nothing(installer, volume):
    installer.install(volume, "gallery", dry_run=True)
    assert (volume / "apps/menu/__init__.py").read_text() == STOCK_MENU
    assert (volume / "apps/gallery").is_dir()
    assert not (volume / "apps/jobcontext").exists()
    assert not installer.BACKUP_ROOT.exists()


def test_refuses_a_volume_that_is_not_a_badge(installer, tmp_path):
    with pytest.raises(installer.InstallError, match="really the badge"):
        installer.install(tmp_path, "gallery", dry_run=False)


def test_reinstall_refreshes_files_without_a_useless_backup(installer, volume):
    installer.install(volume, "gallery", dry_run=False)
    (first,) = installer.BACKUP_ROOT.iterdir()
    (volume / "apps/jobcontext/ui.mpy").write_bytes(b"stale")

    installer.install(volume, "gallery", dry_run=False)

    assert list(installer.BACKUP_ROOT.iterdir()) == [first]
    assert (volume / "apps/jobcontext/ui.mpy").read_bytes() != b"stale"


def test_install_removes_stale_py_that_would_shadow_the_mpy(installer, volume):
    """MicroPython imports name.py before name.mpy: an old ui.py left on the
    badge would silently win over the freshly compiled ui.mpy."""
    app = volume / "apps/jobcontext"
    app.mkdir(parents=True)
    for name in ("ui.py", "api.py", "tetris.py", "secrets.py"):
        (app / name).write_text("# old")
    installer.install(volume, "gallery", dry_run=False)
    for name in ("ui.py", "api.py", "tetris.py"):
        assert not (app / name).exists(), name
    assert (app / "ui.mpy").is_file()
    assert (app / "secrets.py").exists()   # personal files are not "stale"


def test_install_refuses_without_a_compiler_before_touching_the_badge(installer, volume, monkeypatch):
    def missing():
        raise installer.InstallError("mpy-cross not found")

    monkeypatch.setattr(installer, "find_mpy_cross", missing)
    with pytest.raises(installer.InstallError, match="mpy-cross"):
        installer.install(volume, "gallery", dry_run=False)
    assert (volume / "apps/menu/__init__.py").read_text() == STOCK_MENU
    assert (volume / "apps/gallery").is_dir()
    assert not (volume / "apps/jobcontext").exists()


def test_wrong_mpy_cross_version_is_refused(installer, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("badge_install_real", _SCRIPT)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    fake = tmp_path / "mpy-cross"
    fake.write_text("#!/bin/sh\necho 'MicroPython v1.22.0; mpy-cross emitting mpy v6.2'\n")
    fake.chmod(0o755)
    monkeypatch.setattr(real.shutil, "which", lambda _name: str(fake))
    with pytest.raises(real.InstallError, match="wrong bytecode"):
        real.find_mpy_cross()


def test_real_compile_produces_loadable_bytecode(tmp_path):
    """With mpy-cross installed, every app module compiles for the badge."""
    spec = importlib.util.spec_from_file_location("badge_install_real2", _SCRIPT)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    try:
        exe = real.find_mpy_cross()
    except real.InstallError:
        pytest.skip("mpy-cross not installed")
    for src, dst in real.MODULES.items():
        real.compile_module(exe, real.APP_SRC / src, tmp_path / dst)
        assert (tmp_path / dst).read_bytes()[:2] == b"M\x06", dst   # mpy v6 header
