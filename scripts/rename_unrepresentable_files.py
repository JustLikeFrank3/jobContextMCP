#!/usr/bin/env python3
"""
Rename files whose names can never sync to a Windows peer.

The cloud runs Linux, where `: < > | ? * \\ "` and control characters are all
legal in a filename. `lib.helpers.sanitize_filename` has stripped them at
creation since 2026-07-13, but files written before that fix are still sitting
in the partition, and `lib.sync_client` skips each one on *every* sync - the
desktop can never pull them, forever. This is the one-off cleanup for those.

Dry-run by default: prints the before/after mapping and changes nothing.
Pass --apply to perform the renames.

    # see what would change (safe, read-only)
    python scripts/rename_unrepresentable_files.py --root /app/data

    # do it
    python scripts/rename_unrepresentable_files.py --root /app/data --apply

Content is never touched: this is a pure `rename(2)`, so bytes, inode and
mtime all survive. Nothing is ever overwritten - if the sanitized name is
already taken, a ` (2)`, ` (3)`, ... suffix is appended before the extension,
and the collision is called out in the output.

The rename rule is deliberately identical to `lib.helpers.sanitize_filename`;
`tests/test_rename_unrepresentable_files.py` fails if the two ever drift.
The regex is inlined rather than imported so the script can run standalone
inside the pod without importing the application (and its config side
effects).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

# Keep in lockstep with lib.helpers._ILLEGAL_FILENAME_CHARS.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Directories that are machine-local or never file-synced; skip them so a
# stray match under db/ or .git/ can't be renamed out from under something.
_SKIP_DIRS = {".git", "db", "__pycache__", "node_modules", ".venv"}


def sanitize_filename(name: str) -> str:
    """Make a single filename component safe on every supported platform.

    Mirrors lib.helpers.sanitize_filename exactly.
    """
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("-", name)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip().rstrip(". ")
    return cleaned or "untitled"


def _suffixed(name: str, counter: int) -> str:
    """Insert ' (N)' before the extension: 'a.md' -> 'a (2).md'."""
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        return f"{name} ({counter})"
    return f"{stem} ({counter}).{suffix}"


def plan_renames(filenames: list[str]) -> list[tuple[str, str, bool]]:
    """Plan renames for one directory's file list. Pure - no filesystem.

    *filenames* is every name in the directory, good and bad alike. Returns
    [(old, new, collided)] for only the names that need changing.

    A target is considered taken if a file of that name already exists in the
    directory OR an earlier entry in this same pass already claimed it - two
    different bad names can sanitize to the same string, and both must
    survive. Keeping this pure is deliberate: it is the part that could
    destroy data, and it can be tested on any platform, including the Windows
    box where these filenames cannot even be created.
    """
    taken = set(filenames)
    planned: list[tuple[str, str, bool]] = []

    for filename in sorted(filenames):
        clean = sanitize_filename(filename)
        if clean == filename:
            continue

        collided = clean in taken
        target = clean
        counter = 2
        while target in taken:
            target = _suffixed(clean, counter)
            counter += 1

        taken.add(target)
        planned.append((filename, target, collided))

    return planned


def find_renames(root: Path) -> list[tuple[Path, Path, bool]]:
    """Walk *root* and return [(source, target, collided)] for every rename."""
    planned: list[tuple[Path, Path, bool]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        directory = Path(dirpath)
        for old, new, collided in plan_renames(filenames):
            planned.append((directory / old, directory / new, collided))

    return planned


_IDENTICAL = "byte-identical to existing clean-named file"
_DIFFERENT = "DIFFERENT content from existing clean-named file - suffixed, existing untouched"
_UNREADABLE = "could not compare content - suffixed, existing untouched"


def compare_with_existing(source: Path) -> str:
    """Describe how *source* relates to the file already holding its clean name.

    A bad name whose sanitized twin already exists is usually not lost content:
    the same assessment was re-saved under the clean name after the sanitize
    fix landed, orphaning the old copy. Renaming that would just duplicate it,
    so the caller needs to know whether the bytes actually differ.
    """
    existing = source.parent / sanitize_filename(source.name)
    try:
        if _sha256(existing) == _sha256(source):
            return _IDENTICAL
        return _DIFFERENT
    except OSError:
        return _UNREADABLE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rename files whose names cannot exist on Windows.")
    parser.add_argument(
        "--root", default="/app/data",
        help="Directory to walk (default: /app/data, the partition root).")
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform the renames. Without this flag nothing is written.")
    parser.add_argument(
        "--force-duplicates", action="store_true",
        help="Also rename files that are byte-identical to an existing "
             "clean-named copy. Off by default: those are orphaned duplicates, "
             "and renaming them just clutters the workspace.")
    args = parser.parse_args(argv)

    # Output is deliberately ASCII-only. A pretty arrow raises
    # UnicodeEncodeError on a non-UTF-8 stdout, which under --apply would
    # abort the run *after* some files had already been renamed.
    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    planned = find_renames(root)

    mode = "APPLY" if args.apply else "DRY RUN - nothing will be written"
    print(f"root: {root}")
    print(f"mode: {mode}")
    print(f"files needing rename: {len(planned)}\n")

    if not planned:
        print("Nothing to do - every filename is already representable.")
        return 0

    renamed = failed = skipped_dupes = 0
    for source, target, collided in planned:
        verdict = ""
        if collided:
            verdict = compare_with_existing(source)
            note = f"    [!] name taken - {verdict}"
        else:
            note = ""
        print(f"  FROM: {source.relative_to(root)}")
        print(f"    TO: {target.relative_to(root)}{note}")

        if verdict == _IDENTICAL and not args.force_duplicates:
            skipped_dupes += 1
            print("    SKIPPED: byte-identical copy already present under the "
                  "clean name; renaming would only duplicate it. "
                  "Use --force-duplicates to rename anyway.")
            continue

        if not args.apply:
            continue
        try:
            # Re-check under the actual write: os.walk ran earlier, and this
            # must never clobber a file that appeared in between.
            if target.exists():
                raise FileExistsError(f"target appeared since scan: {target}")
            os.rename(source, target)
            renamed += 1
        except OSError as exc:
            failed += 1
            print(f"    *** FAILED: {exc}")

    print()
    if skipped_dupes:
        print(f"{skipped_dupes} of {len(planned)} are byte-identical duplicates of a")
        print("file already present under the clean name. Nothing is lost by leaving")
        print("them; they are orphaned pre-sanitize copies. Delete them by hand if")
        print("you want the partition tidy, or pass --force-duplicates to rename.")
        print()
    if args.apply:
        print(f"renamed: {renamed}    skipped: {skipped_dupes}    failed: {failed}")
        if failed:
            return 1
        print("Done. The desktop will pull any renamed files on the next sync.")
    else:
        print("Dry run complete. Re-run with --apply to perform the renames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
