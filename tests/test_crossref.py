"""
Tests for tools/crossref.py — multi-platform contact cross-reference.

Structure:
  Pure unit tests   — normalize, first_last, name_keys, fb_index, hints
  Integration tests — run_contact_crossref / get_contact_crossref with fake data
"""

import json
from pathlib import Path

import pytest

from tools.crossref import (
    _normalize,
    _first_last,
    _name_keys,
    _build_fb_index,
    _lookup_fb,
    _hints,
    run_contact_crossref,
    get_contact_crossref,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_fb_folder(tmp: Path, friends=(), sent=(), received=(), removed=()) -> Path:
    """Write minimal Facebook export files into a temp folder."""
    folder = tmp / "fb_export"
    folder.mkdir(exist_ok=True)
    _write_json(folder / "your_friends.json",
                {"friends_v2": [{"name": n, "timestamp": 0} for n in friends]})
    _write_json(folder / "sent_friend_requests.json",
                {"sent_requests_v2": [{"name": n, "timestamp": 0} for n in sent]})
    _write_json(folder / "received_friend_requests.json",
                {"received_requests_v2": [{"name": n, "timestamp": 0} for n in received]})
    _write_json(folder / "removed_friends.json",
                {"deleted_friends_v2": [{"name": n, "timestamp": 0} for n in removed]})
    return folder


def _li_conn(full_name: str, company: str = "", position: str = "") -> dict:
    """Minimal LinkedIn connection entry."""
    parts = full_name.strip().split()
    first = parts[0] if parts else ""
    last  = parts[-1] if len(parts) > 1 else ""
    norm  = _normalize(full_name)
    return {
        "first_name": first,
        "last_name": last,
        "full_name": full_name,
        "full_name_normalized": norm,
        "linkedin_url": f"https://linkedin.com/in/{norm.replace(' ', '-')}",
        "email": "",
        "company": company,
        "position": position,
        "connected_on": "01 Jan 2025",
        "facebook_match": None,
    }


def _li_data(connections: list[dict]) -> dict:
    return {
        "metadata": {"source": "test", "total": len(connections)},
        "connections": connections,
    }


def _people_data(people: list[dict]) -> dict:
    return {"people": people}


def _person(id_: int, name: str, company: str = "", tags=(), outreach_status: str = "none") -> dict:
    return {
        "id": id_,
        "name": name,
        "company": company,
        "tags": list(tags),
        "outreach_status": outreach_status,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Pure unit tests — name normalization
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_lowercases():
    assert _normalize("Frank MacBride") == "frank macbride"


def test_normalize_strips_diacritics():
    assert _normalize("José García") == "jose garcia"
    assert _normalize("Anaïs Abrams") == "anais abrams"


def test_normalize_removes_punctuation():
    assert _normalize("O'Brien") == "obrien"
    assert _normalize("Chuck Handy III") == "chuck handy iii"
    assert _normalize("Gustavo A. Chaparro-Baquero") == "gustavo a chaparrobaquero"


def test_normalize_collapses_whitespace():
    assert _normalize("  Jane   Doe  ") == "jane doe"


def test_first_last_simple():
    assert _first_last("Jane Doe") == ("jane", "doe")


def test_first_last_middle_name():
    first, last = _first_last("Mary Jo Smith")
    assert first == "mary"
    assert last == "smith"


def test_first_last_single_token():
    first, last = _first_last("Madonna")
    assert first == "madonna"
    assert last == ""


def test_name_keys_simple_two_tokens():
    # "jane doe" normalized == "jane doe", shortform also "jane doe" → no dup
    keys = _name_keys("Jane Doe")
    assert "jane doe" in keys
    assert len(keys) == 1  # shortform == full norm, deduped


def test_name_keys_middle_name_generates_shortform():
    keys = _name_keys("Mary Jo Smith")
    assert "mary jo smith" in keys
    assert "mary smith" in keys


def test_name_keys_suffix_generates_shortform():
    keys = _name_keys("Chuck Handy III")
    assert "chuck handy iii" in keys
    assert "chuck iii" in keys  # first + last token


# ──────────────────────────────────────────────────────────────────────────────
# Pure unit tests — FB index
# ──────────────────────────────────────────────────────────────────────────────

def test_build_fb_index_indexes_all_keys():
    entries = [{"raw": "Mary Jo Smith", "relationship": "friend", "ts": 0}]
    index = _build_fb_index(entries)
    assert "mary jo smith" in index
    assert "mary smith" in index


def test_build_fb_index_higher_signal_wins():
    entries = [
        {"raw": "Jane Doe", "relationship": "removed",  "ts": 1},
        {"raw": "Jane Doe", "relationship": "friend",   "ts": 2},
        {"raw": "Jane Doe", "relationship": "pending_sent", "ts": 3},
    ]
    index = _build_fb_index(entries)
    assert index["jane doe"]["relationship"] == "friend"


def test_build_fb_index_pending_received_beats_pending_sent():
    entries = [
        {"raw": "Bob Lee", "relationship": "pending_sent",     "ts": 0},
        {"raw": "Bob Lee", "relationship": "pending_received", "ts": 1},
    ]
    index = _build_fb_index(entries)
    assert index["bob lee"]["relationship"] == "pending_received"


# ──────────────────────────────────────────────────────────────────────────────
# Pure unit tests — lookup_fb
# ──────────────────────────────────────────────────────────────────────────────

def test_lookup_fb_exact_match():
    entries = [{"raw": "Jane Doe", "relationship": "friend", "ts": 0}]
    index = _build_fb_index(entries)
    result = _lookup_fb("jane doe", "jane", "doe", index)
    assert result is not None
    assert result["raw"] == "Jane Doe"


def test_lookup_fb_middle_name_variance():
    # LI has "Jane Doe", FB has "Jane Marie Doe" — should match via first+last scan
    entries = [{"raw": "Jane Marie Doe", "relationship": "friend", "ts": 0}]
    index = _build_fb_index(entries)
    result = _lookup_fb("jane doe", "jane", "doe", index)
    assert result is not None
    assert result["raw"] == "Jane Marie Doe"


def test_lookup_fb_no_match():
    entries = [{"raw": "Alice Smith", "relationship": "friend", "ts": 0}]
    index = _build_fb_index(entries)
    assert _lookup_fb("bob jones", "bob", "jones", index) is None


# ──────────────────────────────────────────────────────────────────────────────
# Pure unit tests — action hints
# ──────────────────────────────────────────────────────────────────────────────

def test_hints_all_three():
    fb   = {"relationship": "friend"}
    li   = {"url": ""}
    intl = {"id": 1}
    hints = _hints(fb, li, intl)
    assert any("all three" in h for h in hints)


def test_hints_fb_friend_and_linkedin():
    fb = {"relationship": "friend"}
    li = {"url": ""}
    hints = _hints(fb, li, None)
    assert any("strong" in h for h in hints)


def test_hints_removed_still_on_linkedin():
    fb = {"relationship": "removed"}
    li = {"url": ""}
    hints = _hints(fb, li, None)
    assert any("unfriended" in h for h in hints)


def test_hints_pending_sent_on_linkedin():
    fb = {"relationship": "pending_sent"}
    li = {"url": ""}
    hints = _hints(fb, li, None)
    assert any("pending" in h for h in hints)


def test_hints_linkedin_only():
    hints = _hints(None, {"url": ""}, None)
    assert any("linkedin only" in h for h in hints)


def test_hints_fb_friend_only():
    fb = {"relationship": "friend"}
    hints = _hints(fb, None, None)
    assert any("opportunity" in h for h in hints)


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests — run_contact_crossref
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def crossref_env(tmp_path, isolated_server):
    """
    Yields a helper that writes fake data and returns the FB folder path.
    The data_dir is wired to isolated_server's tmp_path via _reconfigure.
    """
    import lib.config as config

    def setup(friends=(), sent=(), received=(), removed=(),
              li_connections=(), people=()):
        fb_folder = _make_fb_folder(tmp_path, friends, sent, received, removed)
        _write_json(config.DATA_FOLDER / "linkedin_connections.json",
                    _li_data(list(li_connections)))
        _write_json(config.PEOPLE_FILE,
                    _people_data(list(people)))
        return fb_folder

    yield setup


def test_run_crossref_missing_folder():
    result = run_contact_crossref(fb_folder="/does/not/exist")
    assert result.startswith("✗")


def test_run_crossref_linkedin_only_contact(crossref_env):
    fb_folder = crossref_env(li_connections=[_li_conn("Alice Smith", "Acme")])
    result = run_contact_crossref(fb_folder=str(fb_folder))
    assert "✓" in result
    assert "linkedin only" in result.lower()


def test_run_crossref_fb_friend_matched_on_linkedin(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        friends=["Jane Doe"],
        li_connections=[_li_conn("Jane Doe", "BigCo")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    li_data = json.loads(config.LINKEDIN_CONNECTIONS_FILE.read_text())
    conn = li_data["connections"][0]
    assert conn["facebook_match"]["matched"] is True
    assert conn["facebook_match"]["relationship"] == "friend"


def test_run_crossref_fb_friend_not_on_linkedin(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        friends=["Bob Jones"],
        li_connections=[_li_conn("Alice Smith")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    insight = data["insights"]["fb_friend_only"]
    names = [c["name"] for c in insight["contacts"]]
    assert "Bob Jones" in names


def test_run_crossref_all_three_platforms(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        friends=["Marc Lande"],
        li_connections=[_li_conn("Marc Lande", "MDS")],
        people=[_person(1, "Marc Lande", "MDS", tags=["ai"])],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    contacts = data["insights"]["all_three_platforms"]["contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Marc Lande"


def test_run_crossref_pending_sent_on_linkedin(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        sent=["Casey Brown"],
        li_connections=[_li_conn("Casey Brown", "StartupCo")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    contacts = data["insights"]["fb_pending_sent_on_linkedin"]["contacts"]
    assert any(c["name"] == "Casey Brown" for c in contacts)


def test_run_crossref_removed_still_on_linkedin(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        removed=["Old Friend"],
        li_connections=[_li_conn("Old Friend", "Corp")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    contacts = data["insights"]["fb_removed_still_on_linkedin"]["contacts"]
    assert any(c["name"] == "Old Friend" for c in contacts)


def test_run_crossref_middle_name_variance(crossref_env):
    """FB 'Jane Marie Doe' should match LinkedIn 'Jane Doe' via first+last scan."""
    import lib.config as config
    fb_folder = crossref_env(
        friends=["Jane Marie Doe"],
        li_connections=[_li_conn("Jane Doe", "Corp")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    li_data = json.loads(config.LINKEDIN_CONNECTIONS_FILE.read_text())
    assert li_data["connections"][0]["facebook_match"]["matched"] is True


def test_run_crossref_internal_only_contact(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        people=[_person(1, "Recruiter Person", "TechCo", outreach_status="sent")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    contacts = data["insights"]["internal_only"]["contacts"]
    assert any(c["name"] == "Recruiter Person" for c in contacts)


def test_run_crossref_saves_metadata(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(friends=["A Person"], li_connections=[_li_conn("B Person")])
    run_contact_crossref(fb_folder=str(fb_folder))

    data = json.loads(config.CONTACT_CROSSREF_FILE.read_text())
    assert "generated" in data["metadata"]
    assert data["metadata"]["sources"]["facebook_friends"] == 1
    assert data["metadata"]["sources"]["linkedin_connections"] == 1


def test_run_crossref_updates_linkedin_file_metadata(crossref_env):
    import lib.config as config
    fb_folder = crossref_env(
        friends=["Jane Doe"],
        li_connections=[_li_conn("Jane Doe")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))

    li_data = json.loads(config.LINKEDIN_CONNECTIONS_FILE.read_text())
    assert li_data["metadata"].get("facebook_crossref_done") is True
    assert li_data["metadata"]["facebook_matches"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests — get_contact_crossref
# ──────────────────────────────────────────────────────────────────────────────

def test_get_crossref_no_data_returns_error(isolated_server):
    # No crossref file written — should fail gracefully
    result = get_contact_crossref()
    assert result.startswith("✗")


def test_get_crossref_summary(crossref_env):
    fb_folder = crossref_env(
        friends=["Jane Doe"],
        li_connections=[_li_conn("Jane Doe"), _li_conn("Bob Jones")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref()
    assert "Unique contacts" in result
    assert "Multi-platform" in result
    assert "insight bucket" in result.lower() or "insight=" in result


def test_get_crossref_insight_bucket(crossref_env):
    fb_folder = crossref_env(
        friends=["Jane Doe"],
        li_connections=[_li_conn("Jane Doe", "Acme")],
    )
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref(insight="fb_friend_and_linkedin")
    assert "Jane Doe" in result


def test_get_crossref_unknown_insight(crossref_env):
    fb_folder = crossref_env(li_connections=[_li_conn("Jane Doe")])
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref(insight="made_up_bucket")
    assert result.startswith("✗")
    assert "Available" in result


def test_get_crossref_name_lookup(crossref_env):
    fb_folder = crossref_env(
        friends=["Marc Lande"],
        li_connections=[_li_conn("Marc Lande", "MDS")],
        people=[_person(1, "Marc Lande", "MDS", tags=["ai", "warm"])],
    )
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref(name="marc lande")
    assert "Marc Lande" in result
    assert "facebook" in result.lower()
    assert "linkedin" in result.lower()
    assert "tracker" in result.lower() or "internal" in result.lower()


def test_get_crossref_name_partial_match(crossref_env):
    fb_folder = crossref_env(li_connections=[_li_conn("Alexandria Jones", "Corp")])
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref(name="alex")
    # Partial match on "alexandria"
    assert "Alexandria Jones" in result


def test_get_crossref_name_no_match(crossref_env):
    fb_folder = crossref_env(li_connections=[_li_conn("Alice Smith")])
    run_contact_crossref(fb_folder=str(fb_folder))
    result = get_contact_crossref(name="nobody here")
    assert "No contacts found" in result
