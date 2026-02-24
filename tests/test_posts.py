"""
Tests for log_linkedin_post(), update_post_metrics(), and get_linkedin_posts().

These tools (v0.4.8) manage a structured LinkedIn post store with engagement
metrics and audience demographics. Posts auto-ingest as tone samples by default.
All filesystem tests use the isolated_server fixture.
"""

import json
from datetime import date
from pathlib import Path

import pytest

import server as srv


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _posts(isolated_server) -> list[dict]:
    """Read posts directly from the JSON store."""
    if not srv.LINKEDIN_POSTS_FILE.exists():
        return []
    return json.loads(srv.LINKEDIN_POSTS_FILE.read_text()).get("posts", [])


def _seed(source="test_post", title="", text="Test post text.", **kwargs):
    """Convenience: log a post with auto_log_tone disabled."""
    srv.log_linkedin_post(text=text, source=source, title=title, auto_log_tone=False, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# log_linkedin_post
# ──────────────────────────────────────────────────────────────────────────────

class TestLogLinkedInPost:
    def test_post_is_persisted(self, isolated_server):
        _seed(source="post_persist")
        assert len(_posts(isolated_server)) == 1

    def test_source_slug_stored(self, isolated_server):
        _seed(source="my_slug")
        assert _posts(isolated_server)[0]["source"] == "my_slug"

    def test_returns_confirmation_with_id(self, isolated_server):
        result = srv.log_linkedin_post(text="Hi.", source="post_confirm", auto_log_tone=False)
        assert "✓" in result
        assert "#1" in result

    def test_ids_are_sequential(self, isolated_server):
        for i in range(3):
            _seed(source=f"seq_post_{i}")
        assert [p["id"] for p in _posts(isolated_server)] == [1, 2, 3]

    def test_title_stored(self, isolated_server):
        _seed(source="title_test", title="My Big Announcement")
        assert _posts(isolated_server)[0]["title"] == "My Big Announcement"

    def test_hashtags_stored(self, isolated_server):
        _seed(source="tag_test", hashtags=["Python", "MCP"])
        tags = _posts(isolated_server)[0]["hashtags"]
        assert "Python" in tags
        assert "MCP" in tags

    def test_links_stored(self, isolated_server):
        _seed(source="link_test", links=["https://github.com/test"])
        assert "https://github.com/test" in _posts(isolated_server)[0]["links"]

    def test_url_stored(self, isolated_server):
        _seed(source="url_test", url="https://linkedin.com/posts/123")
        assert _posts(isolated_server)[0]["url"] == "https://linkedin.com/posts/123"

    def test_posted_date_stored(self, isolated_server):
        _seed(source="date_test", posted_date="2026-02-01")
        assert _posts(isolated_server)[0]["posted_date"] == "2026-02-01"

    def test_posted_date_defaults_to_today(self, isolated_server):
        _seed(source="date_default")
        assert _posts(isolated_server)[0]["posted_date"] == str(date.today())

    def test_context_stored(self, isolated_server):
        _seed(source="ctx_test", text="T.", context="Announcing v5")
        assert _posts(isolated_server)[0]["context"] == "Announcing v5"

    def test_blank_metrics_block_initialized(self, isolated_server):
        _seed(source="metrics_init")
        m = _posts(isolated_server)[0]["metrics"]
        for key in ("impressions", "reactions", "comments", "reposts", "saves",
                    "link_clicks", "profile_views_from_post", "followers_gained"):
            assert key in m
            assert m[key] is None

    def test_audience_highlights_initialized_empty(self, isolated_server):
        _seed(source="ah_init")
        assert _posts(isolated_server)[0]["audience_highlights"] == {}

    def test_update_existing_post_by_source(self, isolated_server):
        _seed(source="dup_test", text="Original.")
        srv.log_linkedin_post(text="Updated.", source="dup_test", title="New Title", auto_log_tone=False)
        posts = _posts(isolated_server)
        assert len(posts) == 1
        assert posts[0]["text"] == "Updated."
        assert posts[0]["title"] == "New Title"

    def test_update_returns_updated_confirmation(self, isolated_server):
        _seed(source="dup_confirm")
        result = srv.log_linkedin_post(text="Updated.", source="dup_confirm", auto_log_tone=False)
        assert "Updated" in result or "updated" in result or "✓" in result

    def test_hashtags_deduplicated_on_update(self, isolated_server):
        _seed(source="dedup_test", hashtags=["Python"])
        srv.log_linkedin_post(text="T.", source="dedup_test", hashtags=["Python", "MCP"], auto_log_tone=False)
        assert _posts(isolated_server)[0]["hashtags"].count("Python") == 1

    def test_links_deduplicated_on_update(self, isolated_server):
        url = "https://github.com/test"
        _seed(source="link_dedup", links=[url])
        srv.log_linkedin_post(text="T.", source="link_dedup", links=[url, "https://other.com"], auto_log_tone=False)
        assert _posts(isolated_server)[0]["links"].count(url) == 1

    def test_auto_log_tone_false_skips_tone_sample(self, isolated_server):
        _seed(source="no_tone", text="Don't capture me.")
        tone_data = json.loads(srv.TONE_FILE.read_text()) if srv.TONE_FILE.exists() else {"samples": []}
        sources = [s.get("source", "") for s in tone_data.get("samples", [])]
        assert "no_tone" not in sources

    def test_auto_log_tone_true_ingests_sample(self, isolated_server):
        srv.log_linkedin_post(text="Capture this voice.", source="yes_tone", auto_log_tone=True)
        assert srv.TONE_FILE.exists()
        tone_data = json.loads(srv.TONE_FILE.read_text())
        sources = [s.get("source", "") for s in tone_data.get("samples", [])]
        assert "yes_tone" in sources

    def test_multiple_posts_append_correctly(self, isolated_server):
        for i in range(5):
            _seed(source=f"append_{i}")
        assert len(_posts(isolated_server)) == 5


# ──────────────────────────────────────────────────────────────────────────────
# update_post_metrics
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdatePostMetrics:
    def test_update_by_post_id(self, isolated_server):
        _seed(source="upd_id")
        srv.update_post_metrics(post_id=1, impressions=1000, reactions=42)
        m = _posts(isolated_server)[0]["metrics"]
        assert m["impressions"] == 1000
        assert m["reactions"] == 42

    def test_update_by_source(self, isolated_server):
        _seed(source="upd_src")
        srv.update_post_metrics(source="upd_src", impressions=500)
        assert _posts(isolated_server)[0]["metrics"]["impressions"] == 500

    def test_only_provided_fields_updated(self, isolated_server):
        _seed(source="upd_partial")
        srv.update_post_metrics(post_id=1, reactions=10)
        m = _posts(isolated_server)[0]["metrics"]
        assert m["reactions"] == 10
        assert m["impressions"] is None  # untouched

    def test_all_metric_fields_accepted(self, isolated_server):
        _seed(source="upd_all")
        srv.update_post_metrics(
            post_id=1,
            impressions=5000,
            members_reached=3000,
            reactions=55,
            comments=12,
            reposts=7,
            saves=3,
            link_clicks=31,
            profile_views_from_post=54,
            followers_gained=2,
        )
        m = _posts(isolated_server)[0]["metrics"]
        assert m["impressions"] == 5000
        assert m["members_reached"] == 3000
        assert m["reactions"] == 55
        assert m["reposts"] == 7
        assert m["link_clicks"] == 31
        assert m["followers_gained"] == 2

    def test_returns_error_without_identifier(self, isolated_server):
        result = srv.update_post_metrics(impressions=100)
        assert "✗" in result

    def test_returns_error_for_missing_post_id(self, isolated_server):
        result = srv.update_post_metrics(post_id=999, impressions=100)
        assert "✗" in result

    def test_returns_error_for_missing_source(self, isolated_server):
        result = srv.update_post_metrics(source="ghost_post", reactions=5)
        assert "✗" in result

    def test_audience_highlights_stored(self, isolated_server):
        _seed(source="ah_test")
        srv.update_post_metrics(post_id=1, audience_highlights={
            "top_company": "Google",
            "top_seniority": "Senior",
        })
        ah = _posts(isolated_server)[0]["audience_highlights"]
        assert ah["top_company"] == "Google"
        assert ah["top_seniority"] == "Senior"

    def test_audience_highlights_merged_not_replaced(self, isolated_server):
        _seed(source="ah_merge")
        srv.update_post_metrics(post_id=1, audience_highlights={"top_company": "GM"})
        srv.update_post_metrics(post_id=1, audience_highlights={"top_seniority": "Entry"})
        ah = _posts(isolated_server)[0]["audience_highlights"]
        assert ah["top_company"] == "GM"
        assert ah["top_seniority"] == "Entry"

    def test_last_checked_is_set_after_update(self, isolated_server):
        _seed(source="lc_test")
        srv.update_post_metrics(post_id=1, impressions=200)
        assert _posts(isolated_server)[0]["metrics"]["last_checked"] is not None

    def test_returns_confirmation_string(self, isolated_server):
        _seed(source="conf_test")
        result = srv.update_post_metrics(post_id=1, impressions=750, reactions=30)
        assert "✓" in result
        assert "impressions=750" in result
        assert "reactions=30" in result


# ──────────────────────────────────────────────────────────────────────────────
# get_linkedin_posts
# ──────────────────────────────────────────────────────────────────────────────

class TestGetLinkedInPosts:
    def test_empty_store_returns_message(self, isolated_server):
        result = srv.get_linkedin_posts()
        assert "No LinkedIn posts" in result

    def test_returns_all_posts_unfiltered(self, isolated_server):
        _seed(source="get_1", title="Post Alpha")
        _seed(source="get_2", title="Post Beta")
        result = srv.get_linkedin_posts()
        assert "get_1" in result or "Post Alpha" in result
        assert "get_2" in result or "Post Beta" in result

    def test_header_shows_post_count(self, isolated_server):
        _seed(source="cnt_1")
        _seed(source="cnt_2")
        result = srv.get_linkedin_posts()
        assert "2 posts" in result

    def test_filter_by_source_partial_match(self, isolated_server):
        _seed(source="mcp_v3_launch")
        _seed(source="retroscam_beta")
        result = srv.get_linkedin_posts(source="mcp")
        assert "mcp_v3_launch" in result
        assert "retroscam_beta" not in result

    def test_filter_by_hashtag(self, isolated_server):
        _seed(source="ht_1", hashtags=["Python", "MCP"])
        _seed(source="ht_2", hashtags=["IoT"])
        result = srv.get_linkedin_posts(hashtag="MCP")
        assert "ht_1" in result
        assert "ht_2" not in result

    def test_filter_by_hashtag_case_insensitive(self, isolated_server):
        _seed(source="htci_1", hashtags=["python"])
        result = srv.get_linkedin_posts(hashtag="Python")
        assert "htci_1" in result

    def test_filter_by_hashtag_strips_hash_prefix(self, isolated_server):
        _seed(source="htstrip", hashtags=["mcp"])
        result = srv.get_linkedin_posts(hashtag="#mcp")
        assert "htstrip" in result

    def test_filter_min_reactions(self, isolated_server):
        _seed(source="mr_low")
        _seed(source="mr_high")
        srv.update_post_metrics(source="mr_low", reactions=2)
        srv.update_post_metrics(source="mr_high", reactions=20)
        result = srv.get_linkedin_posts(min_reactions=10)
        assert "mr_high" in result
        assert "mr_low" not in result

    def test_aggregate_reactions_correct(self, isolated_server):
        _seed(source="agg_a")
        _seed(source="agg_b")
        srv.update_post_metrics(source="agg_a", reactions=10)
        srv.update_post_metrics(source="agg_b", reactions=20)
        result = srv.get_linkedin_posts()
        assert "30" in result

    def test_aggregate_impressions_correct(self, isolated_server):
        _seed(source="imp_a")
        _seed(source="imp_b")
        srv.update_post_metrics(source="imp_a", impressions=1000)
        srv.update_post_metrics(source="imp_b", impressions=500)
        result = srv.get_linkedin_posts()
        assert "1500" in result

    def test_include_text_false_hides_body(self, isolated_server):
        _seed(source="body_hidden", text="SECRET BODY CONTENT")
        assert "SECRET BODY CONTENT" not in srv.get_linkedin_posts(include_text=False)

    def test_include_text_true_shows_body(self, isolated_server):
        _seed(source="body_shown", text="VISIBLE BODY CONTENT")
        assert "VISIBLE BODY CONTENT" in srv.get_linkedin_posts(include_text=True)

    def test_no_match_returns_message(self, isolated_server):
        _seed(source="real_post")
        result = srv.get_linkedin_posts(source="zzz_nonexistent")
        assert "No posts match" in result

    def test_posts_sorted_newest_first(self, isolated_server):
        _seed(source="old_post", posted_date="2025-01-01")
        _seed(source="new_post", posted_date="2026-02-24")
        result = srv.get_linkedin_posts()
        assert result.index("new_post") < result.index("old_post")

    def test_url_shown_in_output(self, isolated_server):
        _seed(source="url_show", url="https://linkedin.com/posts/test-123")
        result = srv.get_linkedin_posts()
        assert "https://linkedin.com/posts/test-123" in result

    def test_context_shown_in_output(self, isolated_server):
        _seed(source="ctx_show", text="T.", context="Announcing JobContextMCP v5")
        result = srv.get_linkedin_posts()
        assert "Announcing JobContextMCP v5" in result
