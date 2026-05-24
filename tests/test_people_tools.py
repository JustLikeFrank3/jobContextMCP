"""
Tests for people tool additions:
  - get_person   (singular lookup by name)
  - get_people   with slim=True
"""

import json

import pytest
import server as srv


# ── helpers ───────────────────────────────────────────────────────────────────

def _seed_people(isolated_server, entries: list[dict]) -> None:
    """Write a people.json with the given entries into the isolated tmp data dir."""
    people_file = srv.PEOPLE_FILE
    data = {"people": entries}
    people_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_person(id_: int, name: str, company: str = "Acme", **kwargs) -> dict:
    return {
        "id": id_,
        "timestamp": "2026-01-01",
        "name": name,
        "relationship": kwargs.get("relationship", "former coworker"),
        "company": company,
        "context": kwargs.get("context", f"Context for {name}"),
        "tags": kwargs.get("tags", ["gm"]),
        "contact_info": kwargs.get("contact_info", ""),
        "outreach_status": kwargs.get("outreach_status", "none"),
        "notes": kwargs.get("notes", ""),
        "last_updated": kwargs.get("last_updated", ""),
    }


# ── get_person ────────────────────────────────────────────────────────────────

class TestGetPerson:
    def test_exact_name_match(self, isolated_server):
        _seed_people(isolated_server, [_make_person(1, "Yousuf Qadri", "Stellantis")])
        result = srv.get_person("Yousuf Qadri")
        assert "Yousuf Qadri" in result
        assert "Stellantis" in result
        assert "#1" in result

    def test_partial_name_match(self, isolated_server):
        _seed_people(isolated_server, [_make_person(5, "Matthew Masarik", "General Motors")])
        result = srv.get_person("Masarik")
        assert "Matthew Masarik" in result
        assert "General Motors" in result

    def test_case_insensitive(self, isolated_server):
        _seed_people(isolated_server, [_make_person(2, "Adam James Canton", "Motion Recruitment")])
        result = srv.get_person("adam james canton")
        assert "Adam James Canton" in result

    def test_not_found(self, isolated_server):
        _seed_people(isolated_server, [_make_person(1, "Frank MacBride", "GM")])
        result = srv.get_person("Nobody Here")
        assert "No person found" in result
        assert "Nobody Here" in result

    def test_multiple_matches_returns_disambiguation(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(1, "Sarah McDarby", "General Motors"),
            _make_person(2, "Sarah Quehl", "General Motors"),
        ])
        result = srv.get_person("Sarah")
        assert "Multiple matches" in result
        assert "Sarah McDarby" in result
        assert "Sarah Quehl" in result

    def test_full_record_includes_notes(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(3, "Byron Woodard", "SRG", notes="Called May 6 about ICE role.")
        ])
        result = srv.get_person("Byron")
        assert "ICE role" in result

    def test_full_record_includes_contact_info(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(4, "Vlad Rusakov", "Ford", contact_info="vrusakov@ford.com")
        ])
        result = srv.get_person("Vlad")
        assert "vrusakov@ford.com" in result

    def test_empty_people_file(self, isolated_server):
        _seed_people(isolated_server, [])
        result = srv.get_person("Anyone")
        assert "No person found" in result

    def test_returns_single_record_not_list_header(self, isolated_server):
        _seed_people(isolated_server, [_make_person(1, "Yousuf Qadri", "Stellantis")])
        result = srv.get_person("Yousuf")
        # get_person should NOT include the ═══ PEOPLE DATABASE header
        assert "PEOPLE DATABASE" not in result


# ── get_people slim mode ──────────────────────────────────────────────────────

class TestGetPeopleSlim:
    def test_slim_excludes_notes(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(1, "Yousuf Qadri", "Stellantis",
                         notes="Lots of detailed notes about Yousuf that are expensive")
        ])
        result = srv.get_people(slim=True)
        assert "Yousuf Qadri" in result
        assert "expensive" not in result

    def test_slim_excludes_context(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(1, "Kate Griebel", "GM",
                         context="Detailed context paragraph that takes many tokens to represent")
        ])
        result = srv.get_people(slim=True)
        assert "Kate Griebel" in result
        assert "takes many tokens" not in result

    def test_slim_includes_essential_fields(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(7, "Byron Woodard", "SRG",
                         relationship="recruiter",
                         outreach_status="responded",
                         tags=["srg", "recruiter"])
        ])
        result = srv.get_people(slim=True)
        assert "#7" in result
        assert "Byron Woodard" in result
        assert "SRG" in result
        assert "recruiter" in result
        assert "responded" in result
        assert "srg" in result

    def test_slim_label_in_header(self, isolated_server):
        _seed_people(isolated_server, [_make_person(1, "Anyone", "Anywhere")])
        result = srv.get_people(slim=True)
        assert "[slim]" in result

    def test_full_mode_default_includes_context(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(1, "Yousuf Qadri", "Stellantis",
                         context="EV Battery Analytics Engineer at Stellantis")
        ])
        result = srv.get_people()
        assert "EV Battery Analytics Engineer" in result

    def test_slim_combined_with_filter(self, isolated_server):
        _seed_people(isolated_server, [
            _make_person(1, "Yousuf Qadri", "Stellantis",
                         notes="Private notes here"),
            _make_person(2, "Kate Griebel", "GM",
                         notes="Other private notes"),
        ])
        result = srv.get_people(name="Yousuf", slim=True)
        assert "Yousuf Qadri" in result
        assert "Kate Griebel" not in result
        assert "Private notes" not in result

    def test_slim_no_results(self, isolated_server):
        _seed_people(isolated_server, [_make_person(1, "Yousuf Qadri", "Stellantis")])
        result = srv.get_people(name="Nobody", slim=True)
        assert "No people found" in result
