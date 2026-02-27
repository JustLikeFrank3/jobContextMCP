"""Tests for tools/ingest.py — ingest_anecdote bundler."""
import json
import pytest
from tests.conftest import isolated_server  # noqa: F401


def test_ingest_anecdote_logs_to_personal_context(isolated_server):
    from tools.ingest import ingest_anecdote
    result = ingest_anecdote(
        story="I spent three weeks modernizing a 500K-line codebase that wasn't in the backlog. Nobody asked me to. I requested user stories in standup so there'd be a paper trail.",
        tags=["modernization", "leadership"],
        title="Out-of-scope modernization",
    )
    assert "personal context" in result
    import lib.config as config
    data = json.loads(config.PERSONAL_CONTEXT_FILE.read_text())
    assert any("modernization" in s.get("title", "").lower() or
               "modernization" in s.get("tags", [])
               for s in data["stories"])


def test_ingest_anecdote_logs_tone_sample_when_long_enough(isolated_server):
    from tools.ingest import ingest_anecdote
    long_story = "I spent three weeks modernizing a 500K-line codebase. " * 5
    result = ingest_anecdote(story=long_story, tags=["modernization"], title="Long story", tone_sample=True)
    assert "tone profile" in result
    assert "skipped" not in result
    import lib.config as config
    tone_data = json.loads(config.TONE_FILE.read_text())
    assert len(tone_data["samples"]) > 0


def test_ingest_anecdote_skips_tone_sample_when_too_short(isolated_server):
    from tools.ingest import ingest_anecdote
    result = ingest_anecdote(story="Short story.", tags=["leadership"], tone_sample=True)
    assert "skipped" in result


def test_ingest_anecdote_skips_tone_sample_when_disabled(isolated_server):
    from tools.ingest import ingest_anecdote
    import lib.config as config
    long_story = "I spent three weeks modernizing a legacy codebase that nobody had touched in years. " * 3
    result = ingest_anecdote(story=long_story, tags=["modernization"], tone_sample=False)
    # tone_sample=False: tone file should either not exist or have no samples
    if config.TONE_FILE.exists():
        tone_data = json.loads(config.TONE_FILE.read_text())
        assert len(tone_data.get("samples", [])) == 0
    else:
        pass  # never written — correct


def test_ingest_anecdote_detects_star_tags(isolated_server):
    from tools.ingest import ingest_anecdote
    result = ingest_anecdote(
        story="Led the Azure migration from PCF to Container Apps with zero downtime.",
        tags=["cloud_migration", "azure", "leadership"],
    )
    assert "STAR tags detected" in result
    assert "cloud_migration" in result or "azure" in result or "leadership" in result


def test_ingest_anecdote_warns_on_no_star_tags(isolated_server):
    from tools.ingest import ingest_anecdote
    result = ingest_anecdote(
        story="I went to the store and bought some milk and bread for the week.",
        tags=["personal", "groceries"],
    )
    assert "No STAR interview tags matched" in result


def test_ingest_anecdote_with_people(isolated_server):
    from tools.ingest import ingest_anecdote
    import lib.config as config
    ingest_anecdote(
        story="Pat McDevitt formed a SWAT team after I raised the CORS issue in diagonal slice. Andrea Samo was on the call.",
        tags=["leadership", "azure", "speak_up"],
        title="Azure SWAT Team",
        people=["Patrick McDevitt", "Andrea Samo"],
    )
    data = json.loads(config.PERSONAL_CONTEXT_FILE.read_text())
    stories_with_pat = [s for s in data["stories"] if "Patrick McDevitt" in s.get("people", [])]
    assert len(stories_with_pat) > 0


def test_ingest_anecdote_returns_multiple_destinations(isolated_server):
    from tools.ingest import ingest_anecdote
    long_story = "This is a long enough story to qualify as a tone sample. " * 4
    result = ingest_anecdote(story=long_story, tags=["leadership"], tone_sample=True)
    assert "2 destination(s)" in result
