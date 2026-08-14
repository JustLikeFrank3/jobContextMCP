"""The source-of-truth bundle (_load_master_context) with its STORIES section.

Why these properties matter: the generator, the deterministic provenance
gate, and the eval judge all consume this one loader. Stories folded into
the bundle is what retired the judge blind spot ("hallucination" flags on
claims sourced from stories the judge was never shown). The load-bearing
guarantees are:

  - stories and STAR stories are rendered into the bundle,
  - a token-budgeted bundle is an exact PREFIX of the unbudgeted bundle
    (trim is deterministic and tail-only), so an unbudgeted judge always
    sees every fact a budgeted generator could have cited,
  - the judge path (read_master_resume) gets the UNBUDGETED bundle,
  - a story snippet pasted into update_master_resume redirects to the
    story library instead of failing with a generic "not found".
"""
from __future__ import annotations

import json

from lib import config
from lib.io import _load_master_context


def _seed_stories() -> None:
    config.PERSONAL_CONTEXT_FILE.write_text(json.dumps({
        "stories": [
            {"id": 1, "title": "Index build", "story": "Indexed 1,491 chunks for under $0.10 total.",
             "tags": ["rag"], "people": ["Miguel"]},
            {"id": 2, "title": "Label origin", "story": "Co-founded a music label in Miami Beach.",
             "tags": ["identity"]},
        ],
        "star_stories": [
            {"id": 7, "title": "SLA hold", "situation": "Legacy migration under load.",
             "task": "Keep the SLA.", "action": "Staged rollout with canaries.",
             "result": "98% SLA held through every phase.",
             "metric_bullets": ["98% SLA", "zero rollbacks"]},
        ],
    }), encoding="utf-8")


def test_bundle_includes_stories_and_star_stories(isolated_server):
    _seed_stories()
    bundle = _load_master_context()
    assert "──── STORIES" in bundle
    assert "Indexed 1,491 chunks for under $0.10 total." in bundle
    assert "Miami Beach" in bundle
    assert "SLA hold (STAR)" in bundle
    assert "Metrics: 98% SLA; zero rollbacks" in bundle
    # Existing sections are untouched — stories append, never displace.
    assert "[TEST MASTER RESUME]" in bundle
    assert "──── ACHIEVEMENTS ────" in bundle


def test_zero_budget_omits_the_section_entirely(isolated_server):
    _seed_stories()
    bundle = _load_master_context(stories_token_budget=0)
    assert "──── STORIES" not in bundle
    assert "1,491" not in bundle


def test_budgeted_bundle_is_a_prefix_of_the_full_bundle(isolated_server):
    """THE parity property: whatever subset a token-ceiling forces on the
    generator, the judge's unbudgeted bundle starts with those exact bytes —
    every generator-visible fact is judge-visible."""
    _seed_stories()
    full = _load_master_context()
    # Find the smallest budget that admits the first story, by scanning rather
    # than reimplementing the estimator (tiktoken vs chars/4 varies by env).
    # At that exact boundary the second story cannot also fit, so this pins
    # whole-story granularity too.
    trimmed = next(
        (t for b in range(1, 500)
         if "1,491" in (t := _load_master_context(stories_token_budget=b))),
        None,
    )
    assert trimmed is not None
    assert full.startswith(trimmed)
    assert "Miami Beach" not in trimmed  # tail trimmed, whole-story granularity


def test_missing_or_empty_story_file_degrades_silently(isolated_server):
    config.PERSONAL_CONTEXT_FILE.write_text(json.dumps({"stories": []}), encoding="utf-8")
    assert "──── STORIES" not in _load_master_context()
    config.PERSONAL_CONTEXT_FILE.unlink()
    bundle = _load_master_context()
    assert "──── STORIES" not in bundle
    assert "[TEST MASTER RESUME]" in bundle


def test_judge_path_gets_the_unbudgeted_bundle(isolated_server):
    """read_master_resume feeds evals.runner._master_excerpt — the judge must
    see every story fact or story-sourced claims read as hallucinations."""
    _seed_stories()
    from tools.resume import read_master_resume

    text = read_master_resume()
    assert "Indexed 1,491 chunks for under $0.10 total." in text
    assert "98% SLA held through every phase." in text


def test_update_master_resume_redirects_story_snippets(isolated_server):
    _seed_stories()
    from tools.resume import update_master_resume

    out = update_master_resume(
        old_text="Indexed 1,491 chunks for under $0.10 total.", new_text="x"
    )
    assert "✗" in out
    assert "STORIES" in out
    assert "update_personal_story" in out
