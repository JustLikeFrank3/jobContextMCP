#!/usr/bin/env python3
"""Install the jobcontext app onto a GitHub Universe badge.

    python3 badge/install.py              # replaces "gallery"
    python3 badge/install.py --dry-run    # show what would change
    python3 badge/install.py --restore ~/badge-backups/<stamp>

Why it works this way (verified on hardware, 2026-10-02):

  * Apps live in /system/apps/<name>/ and /system is READ-ONLY to MicroPython
    on the badge, so mpremote cannot install anything there.  The badge has
    to be in USB-drive mode — double-tap the reset button — which mounts
    /system on the Mac as /Volumes/BADGER.
  * The launcher only shows apps named in a hard-coded list in
    apps/menu/__init__.py, laid out on a 3x2 grid that the six stock apps
    already fill.  A seventh entry would draw off-screen, so one stock app has
    to give up its slot.  Default: gallery (it pages through bundled PNGs —
    the least useful of the six; "badge" is the GitHub profile card and stays).

  * The app is installed PRECOMPILED (.mpy, via mpy-cross on the Mac), with a
    small __init__.py loader. Compiling ~80 KB of .py source on the badge
    itself cost so much RAM and fragmented the heap so badly that the app ran
    out of memory loading its fonts (2026-10-03); precompiled, startup has
    ~37 KB more headroom. The loader also frees what the launcher left
    loaded (the menu module, its sprites and fonts) before importing the app.

The replaced app's folder and the original menu are backed up first, so
--restore puts the badge back exactly as it was.  Stdlib only, plus the
mpy-cross binary:  uv tool install "mpy-cross==1.26.*"  (or pip install).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = "jobcontext"
APP_SRC = Path(__file__).resolve().parent / APP
# Compiled to .mpy for the badge. The app package's own __init__.py becomes
# app.mpy; a generated loader takes its place (LOADER below).
MODULES = {"__init__.py": "app.mpy", "api.py": "api.mpy", "inputs.py": "inputs.mpy",
           "keyboard.py": "keyboard.mpy", "ui.py": "ui.mpy",
           "screensaver.py": "screensaver.mpy", "tetris.py": "tetris.mpy"}
ASSETS = ("icon.png",)
# Kept for the source checks below; every one of these must exist.
APP_FILES = tuple(MODULES) + ASSETS
# MicroPython resolves name.py before name.mpy, so a stale .py left on the
# badge from an older install would silently shadow the compiled module.
STALE = tuple(src for src in MODULES if src != "__init__.py")
MPY_VERSION = "mpy v6.3"  # MicroPython 1.26 — the badge reports _mpy=7942
LOADER = """\
# Loader written by badge/install.py. The app itself is precompiled (app.mpy
# and friends) so the badge never runs the compiler; this stub frees what the
# launcher left in memory first, then loads it.
import gc
import sys

for _name in list(sys.modules):
    if _name.startswith("/system/apps/") and _name != __name__:
        del sys.modules[_name]
gc.collect()

from app import init, on_exit, update  # noqa: E402,F401
"""
# Personal, gitignored, copied when present: WiFi + token, and the screen
# saver's contact card (no contact.py = no screen saver).
OPTIONAL_FILES = ("secrets.py", "contact.py")
DEFAULT_VOLUME = Path("/Volumes/BADGER")
BACKUP_ROOT = Path.home() / "badge-backups"
_MENU = Path("apps/menu/__init__.py")


class InstallError(Exception):
    pass


# ── menu patching (pure, unit-tested) ──────────────────────────────────────────

def _entry_re(path: str) -> re.Pattern:
    """Matches one ("label", "path"), line in the menu's apps list."""
    return re.compile(r'^([ \t]*)\(\s*"[^"]*"\s*,\s*"' + re.escape(path) + r'"\s*\),[^\n]*\n', re.M)


def patch_menu(source: str, remove: str, app: str = APP) -> str:
    """Return *source* with *remove*'s menu entry swapped for *app*'s.

    Idempotent: if *app* is already listed, any *remove* entry is just dropped.
    """
    if "apps = [" not in source:
        raise InstallError("menu/__init__.py has no `apps = [` list — unknown firmware, not touching it")
    if _entry_re(app).search(source):
        return _entry_re(remove).sub("", source)
    match = _entry_re(remove).search(source)
    if match is None:
        raise InstallError(
            f'no "{remove}" entry in the menu to replace. Listed: {", ".join(listed_apps(source))}'
        )
    return source[: match.start()] + f'{match.group(1)}("{app}", "{app}"),\n' + source[match.end():]


def listed_apps(source: str) -> list[str]:
    return re.findall(r'^\s*\(\s*"[^"]*"\s*,\s*"([^"]+)"\s*\),', source, re.M)


# ── filesystem steps ───────────────────────────────────────────────────────────

def wait_for_volume(volume: Path, timeout: int) -> Path:
    if volume.is_dir():
        return volume
    print(f"Waiting for {volume} ...")
    print("  Put the badge in USB-drive mode: plug it in with a DATA cable and")
    print("  double-tap the reset button on the back.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if volume.is_dir():
            time.sleep(1)  # let Finder finish mounting
            return volume
        time.sleep(1)
    raise InstallError(f"{volume} never appeared (waited {timeout}s)")


def backup(volume: Path, remove: str) -> Path:
    dest = BACKUP_ROOT / _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (dest / "apps/menu").mkdir(parents=True)
    shutil.copy2(volume / _MENU, dest / _MENU)
    if (volume / "apps" / remove).is_dir():
        shutil.copytree(volume / "apps" / remove, dest / "apps" / remove)
    (dest / "REMOVED_APP").write_text(remove + "\n")
    return dest


def find_mpy_cross() -> str:
    """Path to an mpy-cross that emits the badge's bytecode version."""
    candidates = [shutil.which("mpy-cross"), str(Path.home() / ".local/bin/mpy-cross")]
    for exe in candidates:
        if not exe or not Path(exe).is_file():
            continue
        try:
            version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
        except OSError:
            continue
        if MPY_VERSION in version:
            return exe
        raise InstallError(
            f"{exe} emits the wrong bytecode ({version.strip()}); the badge needs {MPY_VERSION}. "
            'Install:  uv tool install "mpy-cross==1.26.*"'
        )
    raise InstallError('mpy-cross not found. Install:  uv tool install "mpy-cross==1.26.*"')


def compile_module(exe: str, src: Path, dst: Path) -> None:
    result = subprocess.run([exe, "-o", str(dst), str(src)], capture_output=True, text=True)
    if result.returncode != 0:
        raise InstallError(f"mpy-cross failed on {src.name}: {result.stderr.strip()}")


def install(volume: Path, remove: str, dry_run: bool) -> None:
    menu_path = volume / _MENU
    if not menu_path.is_file():
        raise InstallError(f"{menu_path} not found — is {volume} really the badge?")
    missing = [f for f in APP_FILES if not (APP_SRC / f).is_file()]
    if missing:
        raise InstallError(f"missing from {APP_SRC}: {', '.join(missing)}")

    original = menu_path.read_text()
    patched = patch_menu(original, remove)
    optional = tuple(f for f in OPTIONAL_FILES if (APP_SRC / f).is_file())
    has_secrets = "secrets.py" in optional

    print(f"menu now:  {', '.join(listed_apps(original))}")
    print(f"menu after: {', '.join(listed_apps(patched))}")
    print(f"delete:    apps/{remove}/" if (volume / "apps" / remove).is_dir() else f"delete:    (apps/{remove} already gone)")
    print(f"compile:   {', '.join(MODULES)} -> .mpy (+ loader __init__.py)")
    print(f"copy:      {', '.join(ASSETS + optional)}")
    if not has_secrets:
        print(f"  ! no {APP_SRC / 'secrets.py'} — the app will install but show a")
        print("    'no secrets.py' error until you add one (see secrets.example.py).")
    if "contact.py" not in optional:
        print("  (no contact.py — no screen saver; see contact.example.py)")
    if dry_run:
        print("dry run — nothing written.")
        return
    exe = find_mpy_cross()  # before touching the badge: fail with nothing changed

    if patched != original or (volume / "apps" / remove).is_dir():
        saved = backup(volume, remove)
        print(f"backup:    {saved}")
    else:
        # Already installed: this run only refreshes app files. A backup now
        # would hold the patched menu and no removed app — a restore point
        # that restores nothing. The first install's backup is the real one.
        print("backup:    skipped (already installed; restore from the first install's backup)")

    target = volume / "apps" / APP
    target.mkdir(exist_ok=True)
    # Compile on the Mac, then copy each finished file in one write. mpy-cross
    # writing straight onto the badge's FAT drive took ~1 minute per file —
    # it emits many tiny writes, and the USB mass-storage mount is slow at them.
    with tempfile.TemporaryDirectory() as tmp:
        for src, dst in MODULES.items():
            compile_module(exe, APP_SRC / src, Path(tmp) / dst)
            shutil.copyfile(Path(tmp) / dst, target / dst)
    for name in STALE:
        (target / name).unlink(missing_ok=True)
    (target / "__init__.py").write_text(LOADER)
    for name in ASSETS + optional:
        shutil.copyfile(APP_SRC / name, target / name)
    # macOS leaves AppleDouble ._* metadata files on FAT volumes; on the badge
    # they are just clutter in a small filesystem.
    for junk in target.glob("._*"):
        junk.unlink(missing_ok=True)
    menu_path.write_text(patched)
    if (volume / "apps" / remove).is_dir():
        shutil.rmtree(volume / "apps" / remove)
    print("installed.")


def restore(volume: Path, saved: Path, dry_run: bool) -> None:
    removed = (saved / "REMOVED_APP").read_text().strip()
    print(f"restore:   menu + apps/{removed}/ from {saved}; delete apps/{APP}/")
    if dry_run:
        print("dry run — nothing written.")
        return
    shutil.copyfile(saved / _MENU, volume / _MENU)
    if (saved / "apps" / removed).is_dir():
        shutil.copytree(saved / "apps" / removed, volume / "apps" / removed, dirs_exist_ok=True)
    shutil.rmtree(volume / "apps" / APP, ignore_errors=True)
    print("restored.")


def eject(volume: Path) -> None:
    subprocess.run(["sync"], check=False)
    if sys.platform == "darwin":
        result = subprocess.run(["diskutil", "eject", str(volume)], capture_output=True, text=True)
        if result.returncode == 0:
            print("ejected — press reset on the badge, then pick jobcontext from the menu.")
            return
    print(f"eject {volume} before unplugging, then press reset on the badge.")


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remove", default="gallery", help="stock app whose menu slot jobcontext takes (default: gallery)")
    parser.add_argument("--volume", type=Path, default=DEFAULT_VOLUME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="BACKUP_DIR", help="undo an install from its backup")
    parser.add_argument("--no-eject", action="store_true")
    parser.add_argument("--wait", type=int, default=120, help="seconds to wait for the drive (default 120)")
    args = parser.parse_args(argv)

    try:
        volume = wait_for_volume(args.volume, args.wait)
        if args.restore:
            restore(volume, args.restore.expanduser(), args.dry_run)
        else:
            install(volume, args.remove, args.dry_run)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run and not args.no_eject:
        eject(volume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
