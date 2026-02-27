#!/usr/bin/env python3
"""
One-time seed import: reads all stories, tone samples, and people from the
data/ JSON files and writes them into their respective Honcho sessions.

Sessions populated:
    personal-context  — data/personal_context.json
    tone-samples      — data/tone_samples.json
    people            — data/people.json

Run once after setting honcho_api_key in config.json:

    .venv/bin/python3 scripts/seed_honcho.py [--section stories|tone|people]

Omitting --section seeds all three. Safe to re-run — stories are additive.
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, honcho_client
from lib.io import _load_json


def seed_stories() -> tuple[int, int]:
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = data.get("stories", [])
    if not stories:
        print("  No stories found.")
        return 0, 0
    ok = fail = 0
    for s in stories:
        content = f"[Story #{s['id']}] {s.get('title', '(untitled)')}\n\n{s['story']}"
        meta = {"id": s["id"], "title": s.get("title", ""), "tags": s.get("tags", []), "people": s.get("people", [])}
        if honcho_client.add_story(content, metadata=meta):
            print(f"  ✓ #{s['id']}: {s.get('title', '(untitled)')}")
            ok += 1
        else:
            print(f"  ✗ #{s['id']}: {s.get('title', '(untitled)')} — FAILED")
            fail += 1
    return ok, fail


def seed_tone() -> tuple[int, int]:
    data = _load_json(config.TONE_FILE, {"samples": []})
    samples = data.get("samples", [])
    if not samples:
        print("  No tone samples found.")
        return 0, 0
    ok = fail = 0
    for s in samples:
        content = f"[Tone Sample #{s['id']}] source={s['source']}\n"
        if s.get("context"):
            content += f"context={s['context']}\n"
        content += f"\n{s['text']}"
        meta = {"id": s["id"], "source": s["source"], "context": s.get("context", ""), "word_count": s.get("word_count", 0)}
        if honcho_client.add_tone_sample(content, metadata=meta):
            print(f"  ✓ #{s['id']}: {s['source']} ({s.get('word_count', 0)} words)")
            ok += 1
        else:
            print(f"  ✗ #{s['id']}: {s['source']} — FAILED")
            fail += 1
    return ok, fail


def seed_people() -> tuple[int, int]:
    data = _load_json(config.PEOPLE_FILE, {"people": []})
    people = data.get("people", [])
    if not people:
        print("  No people found.")
        return 0, 0
    ok = fail = 0
    for p in people:
        content = (
            f"[Contact #{p['id']}] {p['name']}\n"
            f"Relationship: {p.get('relationship', '')}\n"
            f"Company: {p.get('company', '')}\n"
            f"Background: {p.get('context', '')}\n"
        )
        if p.get("tags"):
            content += f"Tags: {', '.join(p['tags'])}\n"
        if p.get("notes"):
            content += f"Notes: {p['notes']}\n"
        if p.get("outreach_status") and p["outreach_status"] != "none":
            content += f"Outreach status: {p['outreach_status']}\n"
        meta = {"id": p["id"], "name": p["name"], "company": p.get("company", "")}
        if honcho_client.add_person(content, metadata=meta):
            print(f"  ✓ #{p['id']}: {p['name']} — {p.get('relationship', '')} at {p.get('company', '')}")
            ok += 1
        else:
            print(f"  ✗ #{p['id']}: {p['name']} — FAILED")
            fail += 1
    return ok, fail


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Honcho from local JSON data files.")
    parser.add_argument("--section", choices=["stories", "tone", "people"], default=None,
                        help="Seed only this section (default: all)")
    args = parser.parse_args()

    if not honcho_client.is_available():
        print("✗ Honcho is not configured. Set honcho_api_key in config.json first.")
        sys.exit(1)

    print(f"Honcho workspace: '{config.HONCHO_WORKSPACE_ID}', peer: '{config.HONCHO_PEER_ID}'\n")

    total_ok = total_fail = 0
    sections = [args.section] if args.section else ["stories", "tone", "people"]

    for section in sections:
        if section == "stories":
            print(f"── Personal context stories ──")
            ok, fail = seed_stories()
        elif section == "tone":
            print(f"── Tone samples ──")
            ok, fail = seed_tone()
        elif section == "people":
            print(f"── People / contacts ──")
            ok, fail = seed_people()
        total_ok += ok
        total_fail += fail
        print()

    print(f"Done: {total_ok} seeded, {total_fail} failed.")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
