import datetime

from lib import config
from lib.io import _read, _load_json, _save_json
from lib.helpers import _build_tone_sample_entry, _scan_dirs


_NO_TONE_SAMPLES_MESSAGE = (
    "No tone samples logged yet.\n"
    "Use log_tone_sample() to ingest writing samples — cover letters, "
    "messages, anything Frank actually wrote."
)


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
    return f"✓ Tone sample logged (#{entry['id']}, {entry['word_count']} words from '{source}')"


def get_tone_profile() -> str:
    """Return all logged tone samples so the AI can calibrate Frank's writing voice before drafting cover letters, outreach messages, or other materials."""
    data = _load_json(config.TONE_FILE, {"samples": []})
    samples = data.get("samples", [])

    if not samples:
        return _NO_TONE_SAMPLES_MESSAGE

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


def _format_tone_samples(samples: list, total_count: int) -> str:
    """Render a list of tone samples into the standard profile block."""
    total_words = sum(s.get("word_count", 0) for s in samples)
    header = f"═══ TONE PROFILE ({len(samples)} of {total_count} samples, {total_words} words) ═══"
    lines = [
        header,
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


def _tone_sample_cost(s: dict) -> int:
    """Estimated token cost of rendering one tone sample in the profile."""
    from lib.story_retrieval import estimate_tokens

    parts = [f"── Sample #{s.get('id')} | {s.get('source', '')} ──"]
    if s.get("context"):
        parts.append(f"Context: {s['context']}")
    parts.append(s.get("text", ""))
    return estimate_tokens("\n".join(parts))


def _pack_tone_samples(
    ordered: list,
    token_budget: int,
    max_samples: int,
    diverse: bool,
    state: dict,
) -> None:
    """Greedily add samples to ``state`` under budget/count limits.

    When ``diverse`` is True, skips sources already represented. Oversized
    samples are skipped (not stopped at) so one huge sample can't waste the
    remaining budget.
    """
    for s in ordered:
        if len(state["selected"]) >= max_samples:
            return
        if s.get("id") in state["ids"]:
            continue
        src = (s.get("source") or "").lower()
        if diverse and src in state["sources"]:
            continue
        cost = _tone_sample_cost(s)
        if state["used"] + cost > token_budget:
            continue
        state["selected"].append(s)
        state["ids"].add(s.get("id"))
        state["sources"].add(src)
        state["used"] += cost


def get_tone_profile_budgeted(
    token_budget: int = 1500,
    max_samples: int = 6,
) -> str:
    """Return a token-bounded tone profile for generation prompts.

    Unlike get_tone_profile() (which dumps every sample and can balloon to
    20k+ tokens), this selects the most recent, source-diverse samples and
    greedily packs them until ``token_budget`` or ``max_samples`` is reached.
    This keeps the tone section a bounded fixed cost so it can never starve
    the personal-context retrieval budget or bust the prompt ceiling.

    Selection strategy:
      1. Newest-first (latest samples best reflect current voice).
      2. Prefer source diversity — at most one sample per source on the first
         pass, then backfill with remaining samples if budget allows.
      3. Greedy pack until budget/count limit; oversized samples are skipped.
    """
    data = _load_json(config.TONE_FILE, {"samples": []})
    samples = data.get("samples", [])
    if not samples:
        return _NO_TONE_SAMPLES_MESSAGE

    if token_budget <= 0 or max_samples <= 0:
        return ""

    ordered = sorted(samples, key=lambda s: s.get("id", 0), reverse=True)
    state = {"selected": [], "used": 0, "ids": set(), "sources": set()}

    _pack_tone_samples(ordered, token_budget, max_samples, True, state)
    _pack_tone_samples(ordered, token_budget, max_samples, False, state)

    selected = state["selected"]
    if not selected:
        return ""

    # Restore chronological order for a natural read.
    selected.sort(key=lambda s: s.get("id", 0))
    return _format_tone_samples(selected, len(samples))


def _cover_letter_tone_score(sample: dict) -> tuple:
    """Return a priority score for samples that preserve Frank's cover-letter voice.

    Newest-first selection can overfit to short outreach snippets. Cover letters need
    the older high-signal samples that show how Frank connects a personal thread to
    professional evidence without sounding like a corporate template.
    """
    source = (sample.get("source") or "").lower()
    context = (sample.get("context") or "").lower()
    text = (sample.get("text") or "").lower()
    words = int(sample.get("word_count") or 0)

    score = 0
    if source.startswith("cover_letter"):
        score += 100
    if "strongest voice sample" in context or "target register" in context:
        score += 80
    if "unhinged professional bio" in source or "unhinged professional bio" in context:
        score += 70
    if "paved paths" in context or "engineering philosophy" in context:
        score += 60
    if "jobcontextmcp" in text and "actually sound like me" in text:
        score += 45
    if 80 <= words <= 400:
        score += 20
    if words < 40:
        score -= 25

    return (score, sample.get("id", 0))


def get_cover_letter_tone_profile_budgeted(
    token_budget: int = 1800,
    max_samples: int = 7,
) -> str:
    """Return a tone profile optimized for cover-letter generation.

    This keeps the bounded-token behavior of ``get_tone_profile_budgeted`` but
    seeds the packer with high-signal cover-letter and narrative samples before
    backfilling with recent writing. The goal is to preserve Frank's actual cover
    letter register after retrieval surfaces a strong personal hook.
    """
    data = _load_json(config.TONE_FILE, {"samples": []})
    samples = data.get("samples", [])
    if not samples:
        return _NO_TONE_SAMPLES_MESSAGE

    if token_budget <= 0 or max_samples <= 0:
        return ""

    state = {"selected": [], "used": 0, "ids": set(), "sources": set()}
    prioritized = sorted(samples, key=_cover_letter_tone_score, reverse=True)
    _pack_tone_samples(prioritized, token_budget, max_samples, True, state)

    recent = sorted(samples, key=lambda s: s.get("id", 0), reverse=True)
    _pack_tone_samples(recent, token_budget, max_samples, True, state)
    _pack_tone_samples(recent, token_budget, max_samples, False, state)

    selected = state["selected"]
    if not selected:
        return ""

    selected.sort(key=lambda s: s.get("id", 0))
    return _format_tone_samples(selected, len(samples))


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
