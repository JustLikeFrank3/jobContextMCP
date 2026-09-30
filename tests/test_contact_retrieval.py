"""Retrieval stays small, attributable, and preserves the original message."""
import pytest

from lib import config
from lib.io import _load_json
from tools import people, tone, context


def test_tone_paging_and_exact_fetch(isolated_server):
    for i in range(7):
        tone.log_tone_sample(f"Original message {i}", f"source_{i}")
    first = tone.get_tone_profile()
    assert "5 of 7 samples" in first
    assert "Original message 0" not in first
    assert "offset=5" in first
    second = tone.get_tone_profile(offset=5)
    assert "Original message 0" in second
    assert "More samples" not in second
    assert "Original message 0" in tone.get_tone_profile(sample_id=1)
    assert "No tone samples match" in tone.get_tone_profile(sample_id=999)


def test_tone_filters_and_preview(isolated_server):
    text = "Exact body\n" + "word " * 1000 + "\nKindest regards\n"
    tone.log_tone_sample(text, "outreach_jane_example", "Subject: Consent review")
    tone.log_tone_sample("Unrelated", "outreach_jane_example_other")
    result = tone.get_tone_profile(source="OUTREACH_JANE_EXAMPLE", query="consent review")
    assert "Preview only" in result
    assert "Unrelated" not in result
    assert text in tone.get_tone_profile(sample_id=1)
    assert "No tone samples match" in tone.get_tone_profile(query="missing")


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 21}, {"offset": -1}])
def test_invalid_page(isolated_server, kwargs):
    tone.log_tone_sample("text", "source")
    assert "Use limit between" in tone.get_tone_profile(**kwargs)


def test_contact_context_and_subject(isolated_server):
    body = "  Hello Jane,\nConsent first.\nKindest regards\n"
    people.log_person("Jane Example", "referral", "Example", "Met through family",
                      sent_message=body, sent_subject="A consent-first pilot")
    people.log_person("Jane Example", "", "", "", sent_message="Second message",
                      sent_subject="Following up")
    context.log_personal_story("Consent gates", ["pilot"], ["Jane Example"], "Pilot")
    context.log_personal_story("Unresolved identity", ["pilot"], ["Jane"], "Different")
    result = people.get_person("Jane Example", include_context=True)
    assert body in result
    assert "Subject: A consent-first pilot" in result
    assert "Subject: Following up" in result
    assert "referral at Example" in result
    assert "Consent gates" in result
    assert "Unresolved identity" not in result
    assert "Sample #1" in result
    assert "Logged:" in result
    assert "not independent confirmation" in result
    assert "Subject:" not in people.get_person("Jane Example")
    assert _load_json(config.TONE_FILE, {})["samples"][0]["text"] == body


def test_subject_requires_message_without_writing(isolated_server):
    result = people.log_person("Jane", "friend", "", "", sent_subject="Missing body")
    assert "requires sent_message" in result
    assert not config.PEOPLE_FILE.exists()


def test_context_does_not_guess_contact(isolated_server):
    for name in ("Jane Example", "Jane Other"):
        people.log_person(name, "friend", "", "")
    assert "Multiple matches" in people.get_person("Jane", include_context=True)
    assert "No person found" in people.get_person("Nobody", include_context=True)
    assert "No exact-name story links" in people.get_person("Jane Example", include_context=True)


@pytest.mark.parametrize("sqlite", [False, True])
def test_contact_retrieval_partition_and_storage(isolated_server, monkeypatch, sqlite):
    from lib import io
    from lib.user_context import set_data_folder, reset_data_folder
    from lib.user_provisioning import provision_user_data

    monkeypatch.setattr(io, "_USE_SQLITE", sqlite)
    monkeypatch.setattr(io, "_SQLITE_ONLY", sqlite)
    for tenant in ("one", "two"):
        folder = isolated_server / tenant
        if sqlite:
            provision_user_data(folder)
        token = set_data_folder(folder)
        try:
            people.log_person("Same Name", "friend", "", "",
                              sent_message=f"  Private body {tenant}\n",
                              sent_subject=f"Subject {tenant}")
        finally:
            reset_data_folder(token)
    token = set_data_folder(isolated_server / "one")
    try:
        result = people.get_person("Same Name", include_context=True)
        assert "  Private body one\n" in result
        assert "Subject: Subject one" in result
        assert "Private body two" not in result
        assert "Subject two" not in result
    finally:
        reset_data_folder(token)
