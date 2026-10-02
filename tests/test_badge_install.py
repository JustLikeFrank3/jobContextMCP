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
    for name in installer.APP_FILES:
        assert (app / name).is_file(), name
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
    (volume / "apps/jobcontext/ui.py").write_text("stale")

    installer.install(volume, "gallery", dry_run=False)

    assert list(installer.BACKUP_ROOT.iterdir()) == [first]
    assert (volume / "apps/jobcontext/ui.py").read_text() != "stale"
