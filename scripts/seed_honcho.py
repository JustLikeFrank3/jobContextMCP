#!/usr/bin/env python3
"""
One-time seed import: reads all stories from data/personal_context.json
and writes them into Honcho so the peer has full historical context.

Run once after setting honcho_api_key in config.json:

    .venv/bin/python3 scripts/seed_honcho.py

Safe to re-run — stories are additive in Honcho (duplicates are harmless
but unnecessary, so the script skips entries whose JSON id appears in
existing message metadata).
"""
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, honcho_client
from lib.io import _load_json


def main() -> None:
    if not honcho_client.is_available():
        print("✗ Honcho is not configured. Set honcho_api_key in config.json first.")
        sys.exit(1)

    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = data.get("stories", [])

    if not stories:
        print("No stories found in personal_context.json — nothing to seed.")
        return

    print(f"Seeding {len(stories)} stories into Honcho workspace "
          f"'{config.HONCHO_WORKSPACE_ID}', peer '{config.HONCHO_PEER_ID}'...")

    ok = 0
    fail = 0
    for s in stories:
        content = f"[Story #{s['id']}] {s.get('title', '(untitled)')}\n\n{s['story']}"
        meta = {
            "id": s["id"],
            "title": s.get("title", ""),
            "tags": s.get("tags", []),
            "people": s.get("people", []),
        }
        if honcho_client.add_story(content, metadata=meta):
            print(f"  ✓ #{s['id']}: {s.get('title', '(untitled)')}")
            ok += 1
        else:
            print(f"  ✗ #{s['id']}: {s.get('title', '(untitled)')} — FAILED")
            fail += 1

    print(f"\nDone: {ok} seeded, {fail} failed.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
