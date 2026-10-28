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

# The launcher's own modules linger in sys.modules under plain names (its
# app.py and ui.py would shadow ours), so drop anything cached under a name
# this app owns before importing.
for _name in ("app", "api", "inputs", "keyboard", "ui", "screensaver",
              "tetris", "secrets", "contact", "features"):
    sys.modules.pop(_name, None)
for _name in list(sys.modules):
    if _name.startswith("/system/apps/") and _name != __name__:
        del sys.modules[_name]
gc.collect()

_DIR = "/system/apps/jobcontext"
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from app import init, on_exit, update  # noqa: E402,F401

# Two launcher generations: the old badgeware firmware imports this module
# and drives init/update/on_exit itself; BadgeOS (where `badge` is a builtin)
# runs apps as scripts that own the frame loop, so this stub provides one.
try:
    badge  # noqa: B018
except NameError:
    pass
else:
    import machine

    def _home(_pin):
        machine.reset()  # back to the launcher, same as the stock apps

    try:
        machine.Pin.board.BUTTON_HOME.irq(trigger=machine.Pin.IRQ_FALLING, handler=_home)
    except AttributeError:
        pass
    init()
    try:
        while True:
            update()
            badge.update()
    finally:
        on_exit()
"""
# Personal, gitignored, copied when present: WiFi + token, and the screen
# saver's contact card (no contact.py = no screen saver).
OPTIONAL_FILES = ("secrets.py", "contact.py")
DEFAULT_VOLUME = Path("/Volumes/BADGER")
BACKUP_ROOT = Path.home() / "badge-backups"
_MENU = Path("apps/menu/__init__.py")
_MENU_APP = Path("apps/menu/app.py")

# The jC mark as menu-tile contours (see badge/make_menu_icon.py).
_BADGEOS_ICON = (
    (0.494, 0.0, 0.488, 0.077, 0.47, 0.153, 0.44, 0.224, 0.399, 0.29, 0.349, 0.349, 0.29, 0.399, 0.224, 0.44, 0.153, 0.47, 0.077, 0.488, 0.0, 0.494, -0.077, 0.488, -0.153, 0.47, -0.224, 0.44, -0.29, 0.399, -0.349, 0.349, -0.399, 0.29, -0.44, 0.224, -0.47, 0.153, -0.488, 0.077, -0.494, 0.0, -0.488, -0.077, -0.47, -0.153, -0.44, -0.224, -0.399, -0.29, -0.349, -0.349, -0.29, -0.399, -0.224, -0.44, -0.153, -0.47, -0.077, -0.488, -0.0, -0.494, 0.077, -0.488, 0.153, -0.47, 0.224, -0.44, 0.29, -0.399, 0.349, -0.349, 0.399, -0.29, 0.44, -0.224, 0.47, -0.153, 0.488, -0.077, 0.494, 0.0, 0.463, 0.0, 0.457, -0.072, 0.44, -0.143, 0.412, -0.21, 0.374, -0.272, 0.327, -0.327, 0.272, -0.374, 0.21, -0.412, 0.143, -0.44, 0.072, -0.457, -0.0, -0.463, -0.072, -0.457, -0.143, -0.44, -0.21, -0.412, -0.272, -0.374, -0.327, -0.327, -0.374, -0.272, -0.412, -0.21, -0.44, -0.143, -0.457, -0.072, -0.463, 0.0, -0.457, 0.072, -0.44, 0.143, -0.412, 0.21, -0.374, 0.272, -0.327, 0.327, -0.272, 0.374, -0.21, 0.412, -0.143, 0.44, -0.072, 0.457, 0.0, 0.463, 0.072, 0.457, 0.143, 0.44, 0.21, 0.412, 0.272, 0.374, 0.327, 0.327, 0.374, 0.272, 0.412, 0.21, 0.44, 0.143, 0.457, 0.072, 0.463, 0.0),
    (0.227, -0.169, 0.204, -0.186, 0.179, -0.201, 0.153, -0.212, 0.126, -0.22, 0.097, -0.224, 0.069, -0.225, 0.04, -0.222, 0.012, -0.215, -0.015, -0.205, -0.04, -0.192, -0.063, -0.175, -0.084, -0.156, -0.103, -0.134, -0.118, -0.11, -0.131, -0.084, -0.14, -0.057, -0.145, -0.029, -0.147, 0.0, -0.145, 0.029, -0.14, 0.057, -0.131, 0.084, -0.118, 0.11, -0.103, 0.134, -0.084, 0.156, -0.063, 0.175, -0.04, 0.192, -0.015, 0.205, 0.012, 0.215, 0.04, 0.222, 0.069, 0.225, 0.097, 0.224, 0.126, 0.22, 0.153, 0.212, 0.179, 0.201, 0.204, 0.186, 0.227, 0.169, 0.239, 0.153, 0.244, 0.134, 0.241, 0.115, 0.231, 0.098, 0.216, 0.086, 0.197, 0.081, 0.178, 0.084, 0.161, 0.094, 0.148, 0.103, 0.134, 0.112, 0.12, 0.118, 0.104, 0.122, 0.089, 0.125, 0.073, 0.125, 0.057, 0.123, 0.041, 0.12, 0.027, 0.114, 0.013, 0.106, -0.0, 0.097, -0.012, 0.087, -0.022, 0.074, -0.031, 0.061, -0.038, 0.047, -0.043, 0.032, -0.046, 0.016, -0.047, 0.0, -0.046, -0.016, -0.043, -0.032, -0.038, -0.047, -0.031, -0.061, -0.022, -0.074, -0.012, -0.087, -0.0, -0.097, 0.013, -0.106, 0.027, -0.114, 0.041, -0.12, 0.057, -0.123, 0.073, -0.125, 0.089, -0.125, 0.104, -0.122, 0.12, -0.118, 0.134, -0.112, 0.148, -0.103, 0.161, -0.094, 0.239, -0.153, 0.244, -0.134, 0.241, -0.115, 0.231, -0.098, 0.216, -0.086, 0.197, -0.081, 0.178, -0.084),
    (-0.166, -0.15, -0.168, -0.135, -0.174, -0.12, -0.183, -0.108, -0.195, -0.099, -0.21, -0.093, -0.225, -0.091, -0.24, -0.093, -0.255, -0.099, -0.267, -0.108, -0.276, -0.12, -0.282, -0.135, -0.284, -0.15, -0.282, -0.165, -0.276, -0.18, -0.267, -0.192, -0.255, -0.201, -0.24, -0.207, -0.225, -0.209, -0.21, -0.207, -0.195, -0.201, -0.183, -0.192, -0.174, -0.18, -0.168, -0.165),
    (-0.272, -0.056, -0.272, 0.14, -0.272, 0.149, -0.273, 0.155, -0.274, 0.159, -0.275, 0.162, -0.277, 0.164, -0.278, 0.166, -0.279, 0.167, -0.281, 0.168, -0.285, 0.169, -0.29, 0.171, -0.297, 0.172, -0.308, 0.172, -0.29, 0.175, -0.275, 0.184, -0.264, 0.199, -0.259, 0.217, -0.262, 0.235, -0.272, 0.25, -0.287, 0.261, -0.304, 0.266, -0.289, 0.265, -0.272, 0.263, -0.256, 0.258, -0.241, 0.252, -0.226, 0.244, -0.213, 0.233, -0.202, 0.22, -0.193, 0.206, -0.186, 0.19, -0.181, 0.174, -0.179, 0.158, -0.178, 0.142, -0.178, -0.056, -0.182, -0.038, -0.192, -0.023, -0.207, -0.013, -0.225, -0.009, -0.243, -0.013, -0.258, -0.023, -0.268, -0.038),
)



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


def uses_dynamic_app_discovery(source: str) -> bool:
    """Detect the newer Badgeware launcher that discovers /system/apps folders."""
    return re.search(r"shared_apps\(\s*['\"]?/system/apps['\"]?\s*\)", source) is not None


def patch_badgeos_menu(source: str, app: str = APP) -> str:
    """Give *app* a real tile on the BadgeOS launcher: first in APP_ORDER and
    the jC mark in ICONS (unknown slugs otherwise sort last with the default
    tile). Idempotent; missing anchors leave the source unchanged."""
    if f'"{app}",' not in source and "APP_ORDER = (" in source:
        source = source.replace("APP_ORDER = (", f'APP_ORDER = (\n    "{app}",', 1)
    anchor = "from icons import ICONS"
    if f'ICONS["{app}"]' not in source and anchor in source:
        inject = f'{anchor}\n\nICONS["{app}"] = {_BADGEOS_ICON!r}  # badge/install.py'
        source = source.replace(anchor, inject, 1)
    return source


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


def backup(volume: Path, remove: str | None, replace_app: str | None = None) -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / stamp
    n = 1
    while dest.exists():  # two installs in one second (reinstalls, tests)
        n += 1
        dest = BACKUP_ROOT / f"{stamp}-{n}"
    (dest / "apps/menu").mkdir(parents=True)
    shutil.copy2(volume / _MENU, dest / _MENU)
    if (volume / _MENU_APP).is_file():
        shutil.copy2(volume / _MENU_APP, dest / _MENU_APP)
    if remove and (volume / "apps" / remove).is_dir():
        shutil.copytree(volume / "apps" / remove, dest / "apps" / remove)
    if replace_app and (volume / "apps" / replace_app).is_dir():
        shutil.copytree(volume / "apps" / replace_app, dest / "apps" / replace_app)
        (dest / "REPLACED_APP").write_text(replace_app + "\n")
    (dest / "REMOVED_APP").write_text((remove or "") + "\n")
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


def install(
    volume: Path,
    remove: str,
    dry_run: bool,
    features: "dict | None" = None,
    skip_secrets: bool = False,
) -> None:
    """Install the app. *features* writes a generated features.py of flags.

    None — the default, and what badge/install.py alone ever passes — DELETES
    any features.py already on the badge. That is what makes this the fallback
    install rather than the same build carrying a stale flag from a previous
    run of install_phone.py.
    """
    menu_path = volume / _MENU
    if not menu_path.is_file():
        raise InstallError(f"{menu_path} not found — is {volume} really the badge?")
    missing = [f for f in APP_FILES if not (APP_SRC / f).is_file()]
    if missing:
        raise InstallError(f"missing from {APP_SRC}: {', '.join(missing)}")

    original = menu_path.read_text()
    dynamic_menu = uses_dynamic_app_discovery(original)
    menu_app_original = menu_app_patched = None
    if dynamic_menu:
        # Current Badgeware scans /system/apps and creates an app tile for
        # every package directory; it has no fixed slot to patch or evict.
        # The tile itself (icon + ordering) lives in menu/app.py instead.
        patched = original
        remove_app = None
        menu_app_path = volume / _MENU_APP
        if menu_app_path.is_file():
            menu_app_original = menu_app_path.read_text()
            menu_app_patched = patch_badgeos_menu(menu_app_original)
    else:
        patched = patch_menu(original, remove)
        remove_app = remove
    optional = tuple(
        name for name in OPTIONAL_FILES
        if (APP_SRC / name).is_file() and not (skip_secrets and name == "secrets.py")
    )
    has_secrets = "secrets.py" in optional

    if dynamic_menu:
        print("launcher:  dynamically discovers app folders; no menu edit or stock-app removal")
        if menu_app_patched is not None and menu_app_patched != menu_app_original:
            print("menu tile: jobcontext pinned first in APP_ORDER with the jC mark")
        elif menu_app_original is not None:
            print("menu tile: already patched")
    else:
        print(f"menu now:  {', '.join(listed_apps(original))}")
        print(f"menu after: {', '.join(listed_apps(patched))}")
        print(
            f"delete:    apps/{remove_app}/"
            if (volume / "apps" / remove_app).is_dir()
            else f"delete:    (apps/{remove_app} already gone)"
        )
    print(f"compile:   {', '.join(MODULES)} -> .mpy (+ loader __init__.py)")
    print(f"copy:      {', '.join(ASSETS + optional)}")
    if skip_secrets and (APP_SRC / "secrets.py").is_file():
        print("  ! secrets.py deliberately omitted; add a newly rotated badge token before network use.")
    if features:
        print(f"features:  {', '.join('%s=%r' % kv for kv in sorted(features.items()))}")
    else:
        print("features:  none (any features.py on the badge is removed)")
    if not has_secrets:
        print(f"  ! no {APP_SRC / 'secrets.py'} — the app will install but show a")
        print("    'no secrets.py' error until you add one (see secrets.example.py).")
    if "contact.py" not in optional:
        print("  (no contact.py — no screen saver; see contact.example.py)")
    if dry_run:
        print("dry run — nothing written.")
        return
    exe = find_mpy_cross()  # before touching the badge: fail with nothing changed

    target = volume / "apps" / APP
    target_exists = target.is_dir()
    menu_app_changed = menu_app_patched is not None and menu_app_patched != menu_app_original
    needs_backup = (
        patched != original
        or menu_app_changed
        or (remove_app and (volume / "apps" / remove_app).is_dir())
        or (dynamic_menu and target_exists)
    )
    if needs_backup:
        saved = backup(
            volume,
            remove_app,
            replace_app=APP if dynamic_menu and target_exists else None,
        )
        print(f"backup:    {saved}")
    elif dynamic_menu:
        print("backup:    skipped (new app folder; launcher is unchanged)")
    else:
        # Already installed: this run only refreshes app files. A backup now
        # would hold the patched menu and no removed app — a restore point
        # that restores nothing. The first install's backup is the real one.
        print("backup:    skipped (already installed; restore from the first install's backup)")

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
    # Plain source, not .mpy: it is three lines, and a human reading the badge
    # to work out why the phone form is or is not running should be able to.
    if features:
        body = "".join("%s = %r\n" % kv for kv in sorted(features.items()))
        (target / "features.py").write_text(
            "# Generated by badge/install_phone.py. Delete to switch off, or\n"
            "# reinstall with badge/install.py, which removes it.\n" + body
        )
    else:
        (target / "features.py").unlink(missing_ok=True)
    # macOS leaves AppleDouble ._* metadata files on FAT volumes; on the badge
    # they are just clutter in a small filesystem.
    for junk in target.glob("._*"):
        junk.unlink(missing_ok=True)
    if patched != original:
        menu_path.write_text(patched)
    if menu_app_changed:
        (volume / _MENU_APP).write_text(menu_app_patched)
    if remove_app and (volume / "apps" / remove_app).is_dir():
        shutil.rmtree(volume / "apps" / remove_app)
    print("installed.")


def restore(volume: Path, saved: Path, dry_run: bool) -> None:
    replaced_marker = saved / "REPLACED_APP"
    removed = (saved / "REMOVED_APP").read_text().strip() if (saved / "REMOVED_APP").is_file() else ""
    if replaced_marker.is_file() or not removed:
        # Dynamic-launcher backup: menu/__init__.py was never touched, but
        # menu/app.py may carry the tile patch and the app folder may have
        # been replaced or freshly added.
        replaced = replaced_marker.read_text().strip() if replaced_marker.is_file() else None
        menu_app_saved = saved / _MENU_APP
        what = f"apps/{replaced}/" if replaced else f"delete apps/{APP}/"
        extra = " + menu app.py" if menu_app_saved.is_file() else ""
        print(f"restore:   {what}{extra} from {saved}; keep dynamic launcher menu")
        if dry_run:
            print("dry run — nothing written.")
            return
        if menu_app_saved.is_file():
            shutil.copyfile(menu_app_saved, volume / _MENU_APP)
        shutil.rmtree(volume / "apps" / APP, ignore_errors=True)
        if replaced and replaced != APP:
            shutil.rmtree(volume / "apps" / replaced, ignore_errors=True)
        if replaced:
            shutil.copytree(saved / "apps" / replaced, volume / "apps" / replaced)
        print("restored.")
        return

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


def main(argv: "list[str] | None" = None, features: "dict | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remove", default="gallery", help="stock app whose menu slot jobcontext takes (default: gallery)")
    parser.add_argument("--volume", type=Path, default=DEFAULT_VOLUME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help="do not copy the local secrets.py (use after rotating exposed credentials)",
    )
    parser.add_argument("--restore", type=Path, metavar="BACKUP_DIR", help="undo an install from its backup")
    parser.add_argument("--no-eject", action="store_true")
    parser.add_argument("--wait", type=int, default=120, help="seconds to wait for the drive (default 120)")
    args = parser.parse_args(argv)

    try:
        volume = wait_for_volume(args.volume, args.wait)
        if args.restore:
            restore(volume, args.restore.expanduser(), args.dry_run)
        else:
            install(volume, args.remove, args.dry_run, features, skip_secrets=args.skip_secrets)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run and not args.no_eject:
        eject(volume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
