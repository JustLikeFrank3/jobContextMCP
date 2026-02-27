import datetime

from lib import config, honcho_client
from lib.io import _read, _load_json, _save_json
from lib.helpers import _build_tone_sample_entry, _scan_dirs


def log_tone_sample(
    text: str,
    source: str,
    context: str = "",
) -> str:
    """Ingest a writing sample to build Frank's tone/voice profile. Pass the text, a source label (e.g. 'cover_letter_fanduel'), and optional context describing the situation. Used to calibrate the AI before drafting new materials."""
    data = _load_json(config.TONE_FILE, {"samples": []})
    entry = _build_tone_sample_entry(data["samples"], text, source, context)
    data["samples"].append(entry)
    _save_json(config.TONE_FILE, data)

    # Mirror to Honcho tone-samples session
    honcho_content = f"[Tone Sample #{entry['id']}] source={source}\n"
    if context:
        honcho_content += f"context={context}\n"
    honcho_content += f"\n{text}"
    honcho_client.add_tone_sample(
        honcho_content,
        metadata={"id": entry["id"], "source": source, "context": context, "word_count": entry["word_count"]},
    )

    return f"✓ Tone sample logged (#{entry['id']}, {entry['word_count']} words from '{source}')"


def get_tone_profile() -> str:
    """Return Frank's writing voice profile. When Honcho is configured, returns an AI-synthesised description of his tone and style. Falls back to the full sample dump if Honcho is unavailable."""
    data = _load_json(config.TONE_FILE, {"samples": []})
    samples = data.get("samples", [])

    if not samples:
        return (
            "No tone samples logged yet.\n"
            "Use log_tone_sample() to ingest writing samples — cover letters, "
            "messages, anything Frank actually wrote."
        )

    # Honcho path — synthesised voice description
    if honcho_client.is_available():
        query = (
            "Based on Frank's tone samples, describe his writing voice and style in detail. "
            "What makes it distinctive? What patterns, rhythms, word choices, or structural "
            "habits appear consistently? What should be preserved when drafting cover letters, "
            "outreach messages, or LinkedIn posts on his behalf?"
        )
        result = honcho_client.query_context(query)
        if result:
            total_words = sum(s.get("word_count", 0) for s in samples)
            header = f"═══ TONE PROFILE (Honcho synthesis — {len(samples)} samples, {total_words} words) ═══\n"
            return header + result

    # JSON fallback — raw sample dump
    total_words = sum(s.get("word_count", 0) for s in samples)
    lines = [
        f"═══ TONE PROFILE ({len(samples)} samples, {total_words} total words) ═══",
        "Use these samples to calibrate Frank's voice before writing anything.",
        "",
    ]
    for s in samples:
        lines.append(f"── Sample #{s['id']} | {s['source']} ──")
        if s.get("context"):
            lines.append(f"Context: {s['context']}")
        lines.append(s["text"])
        lines.append("")
    return "\n".join(lines)


def scan_materials_for_tone(
    category: str = "cover_letters",
    limit: int = 3,
    company: str = "",
    force: bool = False,
) -> str:
    """Auto-scan resume materials and ingest new files as tone samples. category can be 'cover_letters', 'resumes', or 'all'. Skips already-indexed files unless force=True. Optionally filter by company name."""
    dirs = _scan_dirs(category)

    candidates: list = []
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.txt")):
            rel = str(f.relative_to(config.RESUME_FOLDER))
            candidates.append((rel, f))

    seen_rels: set = set()
    deduped = []
    for rel, f in candidates:
        if rel not in seen_rels:
            deduped.append((rel, f))
            seen_rels.add(rel)
    candidates = deduped

    if company:
        cl = company.lower()
        candidates = [(rel, f) for rel, f in candidates if cl in rel.lower()]

    index = _load_json(config.SCAN_INDEX_FILE, {"scanned": {}})
    scanned = index.get("scanned", {})
    if not force:
        candidates = [(rel, f) for rel, f in candidates if rel not in scanned]

    total_remaining = len(candidates)
    batch = candidates[:limit]

    if not batch:
        filter_note = f" (company filter: '{company}')" if company else ""
        return (
            f"All {category} files have been scanned{filter_note}.\n"
            "Use force=True to re-scan, change category, or add new files."
        )

    lines = [
        f"═══ MATERIAL SCAN — {category.upper()} ═══",
        f"Returning {len(batch)} of {total_remaining} unscanned files.",
        "",
    ]

    for rel, path in batch:
        content = _read(path)
        lines += [
            "─" * 60,
            f"FILE: {path.name}",
            "─" * 60,
            content,
            "",
        ]
        scanned[rel] = datetime.datetime.now().isoformat()

    index["scanned"] = scanned
    _save_json(config.SCAN_INDEX_FILE, index)

    remaining_after = total_remaining - len(batch)
    lines += [
        "═══ EXTRACTION INSTRUCTIONS ═══",
        "",
        "For each file above, extract:",
        "  1. TONE SAMPLES  — paragraphs that sound distinctly like Frank's voice.",
        "     Best candidates: opening paragraph, closing paragraph, any personal framing.",
        "     Call: log_tone_sample(text='...', source='Cover Letter <Company>')",
        "",
        "  2. PERSONAL STORIES — any specific anecdote, motivation, or non-resume detail.",
        "     Call: log_personal_story(story='...', tags=[...], title='...')",
        "",
        f"  {remaining_after} file(s) remaining in this category.",
        "  Call scan_materials_for_tone() again to continue.",
    ]

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(log_tone_sample)
    mcp.tool()(get_tone_profile)
    mcp.tool()(scan_materials_for_tone)
