#!/usr/bin/env python3
"""
One-time seed import: reads all stories, tone samples, people, performance
reviews, and reference materials and writes them into Honcho.

Sessions populated:
    personal-context  — data/personal_context.json + 04-Performance-Reviews/ + 06-Reference-Materials/ + HBDI profile
    tone-samples      — data/tone_samples.json
    people            — data/people.json

Run once after setting honcho_api_key in config.json:

    .venv/bin/python3 scripts/seed_honcho.py [--section stories|tone|people|reviews|reference|hbdi]

Omitting --section seeds all six. Safe to re-run — messages are additive.
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


# Reference: which files in 06-Reference-Materials are worth seeding
_REFERENCE_FILES = [
    "GM Recognition Awards - Frank MacBride.txt",
    "Feedback_Received.txt",
    "Frank MacBride Talent Card.txt",
    "Pre-Engineering Background - Hospitality and Management History.txt",
    "Ford Cloud Developer Summary (300 chars).txt",
]


def seed_reviews() -> tuple[int, int]:
    """Seed all performance review .txt files as stories in the personal-context session.
    Files larger than 6000 chars are split into chunks."""
    reviews_dir = config.RESUME_FOLDER / "04-Performance-Reviews"
    if not reviews_dir.exists():
        print(f"  Directory not found: {reviews_dir}")
        return 0, 0
    files = sorted(reviews_dir.glob("*.txt"))
    if not files:
        print("  No review files found.")
        return 0, 0
    ok = fail = 0
    import re as _re
    for fpath in files:
        text = fpath.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        chunks: list[str] = []
        if len(text) <= 6000:
            chunks = [text]
        else:
            paragraphs = [p.strip() for p in _re.split(r"\n{2,}", text) if p.strip()]
            current = ""
            for para in paragraphs:
                if len(current) + len(para) + 2 > 6000 and current:
                    chunks.append(current.strip())
                    current = para
                else:
                    current = (current + "\n\n" + para).strip()
            if current:
                chunks.append(current)

        meta = {"source": "performance_review", "file": fpath.name,
                "tags": ["performance_review", "manager_feedback", "gm"]}
        for i, chunk in enumerate(chunks, 1):
            part_label = f"{fpath.stem} (part {i}/{len(chunks)})" if len(chunks) > 1 else fpath.stem
            content = f"[Performance Review] {part_label}\n\n{chunk}"
            if honcho_client.add_story(content, metadata=meta):
                print(f"  ✓ {fpath.name}" + (f" [{i}/{len(chunks)}]" if len(chunks) > 1 else ""))
                ok += 1
            else:
                print(f"  ✗ {fpath.name} [{i}] — FAILED")
                fail += 1
    return ok, fail


def seed_reference() -> tuple[int, int]:
    """Seed selected reference material files as stories in the personal-context session.
    Files larger than 6000 chars are split into chunks to stay within Honcho message limits."""
    ref_dir = config.RESUME_FOLDER / "06-Reference-Materials"
    if not ref_dir.exists():
        print(f"  Directory not found: {ref_dir}")
        return 0, 0
    ok = fail = 0
    for fname in _REFERENCE_FILES:
        fpath = ref_dir / fname
        if not fpath.exists():
            print(f"  ! {fname} not found, skipping")
            continue
        text = fpath.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        # Split into ~6000-char chunks at paragraph boundaries if needed
        chunks: list[str] = []
        if len(text) <= 6000:
            chunks = [text]
        else:
            import re as _re
            paragraphs = [p.strip() for p in _re.split(r"\n{2,}", text) if p.strip()]
            current = ""
            for para in paragraphs:
                if len(current) + len(para) + 2 > 6000 and current:
                    chunks.append(current.strip())
                    current = para
                else:
                    current = (current + "\n\n" + para).strip()
            if current:
                chunks.append(current)

        label = fpath.stem
        meta = {"source": "reference_material", "file": fname,
                "tags": ["reference", "awards", "feedback", "gm"]}
        for i, chunk in enumerate(chunks, 1):
            part_label = f"{label} (part {i}/{len(chunks)})" if len(chunks) > 1 else label
            content = f"[Reference Material] {part_label}\n\n{chunk}"
            if honcho_client.add_story(content, metadata=meta):
                print(f"  ✓ {fname}" + (f" [{i}/{len(chunks)}]" if len(chunks) > 1 else ""))
                ok += 1
            else:
                print(f"  ✗ {fname} [{i}/{len(chunks)}] — FAILED")
                fail += 1
    return ok, fail


def seed_hbdi() -> tuple[int, int]:
    """Seed the HBDI cognitive profile into the personal-context session."""
    try:
        from tools.hbdi import get_hbdi_profile
        profile = get_hbdi_profile()
    except Exception as e:
        print(f"  Could not load HBDI profile: {e}")
        return 0, 1
    if not profile or "No HBDI" in profile:
        print("  No HBDI profile found — run run_hbdi_assessment() first.")
        return 0, 0
    content = "[HBDI Cognitive Profile]\n\n" + profile
    meta = {"source": "hbdi", "tags": ["hbdi", "cognitive_style", "interview_framing", "behavioral"]}
    if honcho_client.add_story(content, metadata=meta):
        print("  ✓ HBDI cognitive profile seeded")
        return 1, 0
    print("  ✗ HBDI seed failed")
    return 0, 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Honcho from local JSON data files.")
    parser.add_argument("--section", choices=["stories", "tone", "people", "reviews", "reference", "hbdi"], default=None,
                        help="Seed only this section (default: all six)")
    args = parser.parse_args()

    if not honcho_client.is_available():
        print("✗ Honcho is not configured. Set honcho_api_key in config.json first.")
        sys.exit(1)

    print(f"Honcho workspace: '{config.HONCHO_WORKSPACE_ID}', peer: '{config.HONCHO_PEER_ID}'\n")

    total_ok = total_fail = 0
    sections = [args.section] if args.section else ["stories", "tone", "people", "reviews", "reference", "hbdi"]

    for section in sections:
        if section == "stories":
            print("── Personal context stories ──")
            ok, fail = seed_stories()
        elif section == "tone":
            print("── Tone samples ──")
            ok, fail = seed_tone()
        elif section == "people":
            print("── People / contacts ──")
            ok, fail = seed_people()
        elif section == "reviews":
            print("── Performance reviews ──")
            ok, fail = seed_reviews()
        elif section == "reference":
            print("── Reference materials ──")
            ok, fail = seed_reference()
        elif section == "hbdi":
            print("── HBDI cognitive profile ──")
            ok, fail = seed_hbdi()
        total_ok += ok
        total_fail += fail
        print()

    print(f"Done: {total_ok} seeded, {total_fail} failed.")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
