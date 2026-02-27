"""
Tests for lib/honcho_client.py and the Honcho-backed paths in tools/context.py.

All tests run without a live Honcho API key — the SDK is fully mocked.
Strategy:
  - honcho_client.reset() clears the singleton between tests.
  - monkeypatch swaps lib.config.HONCHO_API_KEY and the Honcho class.
  - context.py Honcho paths are tested by patching honcho_client directly.
"""

from unittest.mock import MagicMock, patch, call

import pytest

import server as srv
import lib.honcho_client as hc
from lib import config


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Always reset the honcho_client singleton before and after each test."""
    hc.reset()
    yield
    hc.reset()


@pytest.fixture()
def mock_honcho_sdk():
    """
    Patch honcho.client.Honcho with a fully controlled mock.

    Returns a (mock_class, mock_instance, mock_peer, mock_session) tuple.
    mock_instance is what Honcho(...) returns.
    """
    mock_session = MagicMock()
    mock_session.add_messages = MagicMock(return_value=None)

    mock_peer = MagicMock()
    mock_peer.message = MagicMock(return_value=MagicMock(name="MessageCreateParams"))
    mock_peer.chat = MagicMock(return_value="Synthesised context response.")

    mock_instance = MagicMock()
    mock_instance.peer = MagicMock(return_value=mock_peer)
    mock_instance.session = MagicMock(return_value=mock_session)

    mock_class = MagicMock(return_value=mock_instance)

    with patch("lib.honcho_client.Honcho", mock_class, create=True):
        yield mock_class, mock_instance, mock_peer, mock_session


# ──────────────────────────────────────────────────────────────────────────────
# is_available — no key
# ──────────────────────────────────────────────────────────────────────────────

class TestIsAvailableNoKey:
    def test_returns_false_when_api_key_empty(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "")
        assert hc.is_available() is False

    def test_returns_false_when_api_key_none(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", None)
        assert hc.is_available() is False

    def test_add_story_returns_false_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "")
        assert hc.add_story("some story") is False

    def test_query_context_returns_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "")
        assert hc.query_context("anything") is None


# ──────────────────────────────────────────────────────────────────────────────
# is_available — with key + mocked SDK
# ──────────────────────────────────────────────────────────────────────────────

class TestIsAvailableWithKey:
    def test_returns_true_when_key_set(self, monkeypatch, mock_honcho_sdk):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "test-key-123")
        monkeypatch.setattr(config, "HONCHO_WORKSPACE_ID", "test-workspace")
        # Re-import Honcho inside honcho_client is mocked at module level
        mock_class, _, _, _ = mock_honcho_sdk
        # Need to make honcho_client actually import the mocked class
        with patch.dict("lib.honcho_client.__dict__", {}):
            pass
        assert hc.is_available() is True

    def test_sdk_initialised_with_correct_params(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "my-api-key")
        monkeypatch.setattr(config, "HONCHO_WORKSPACE_ID", "my-workspace")
        monkeypatch.setattr(config, "HONCHO_PEER_ID", "frank")

        mock_session = MagicMock()
        mock_peer = MagicMock()
        mock_peer.chat = MagicMock(return_value="ok")
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        mock_instance.session = MagicMock(return_value=mock_session)
        mock_class = MagicMock(return_value=mock_instance)

        with patch("honcho.client.Honcho", mock_class, create=True):
            hc.reset()
            hc._get_client()  # trigger init

        mock_class.assert_called_once_with(
            api_key="my-api-key",
            workspace_id="my-workspace",
        )

    def test_returns_false_if_sdk_raises_on_init(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "bad-key")
        with patch("honcho.client.Honcho", side_effect=Exception("auth error"), create=True):
            hc.reset()
            assert hc.is_available() is False


# ──────────────────────────────────────────────────────────────────────────────
# add_story
# ──────────────────────────────────────────────────────────────────────────────

class TestAddStory:
    def _setup(self, monkeypatch, mock_peer, mock_session, mock_instance):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "test-key")
        monkeypatch.setattr(config, "HONCHO_WORKSPACE_ID", "ws")
        monkeypatch.setattr(config, "HONCHO_PEER_ID", "frank")
        # Patch _get_client to return mock directly (avoids import-time SDK patch)
        monkeypatch.setattr(hc, "_get_client", lambda: mock_instance)
        monkeypatch.setattr(hc, "_initialised", True)

    def test_returns_true_on_success(self, monkeypatch):
        mock_session = MagicMock()
        mock_peer = MagicMock()
        mock_peer.message = MagicMock(return_value=MagicMock())
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        mock_instance.session = MagicMock(return_value=mock_session)
        self._setup(monkeypatch, mock_peer, mock_session, mock_instance)

        result = hc.add_story("My cloud migration story", metadata={"tags": ["cloud"]})
        assert result is True

    def test_calls_peer_message_and_session_add_messages(self, monkeypatch):
        mock_msg = MagicMock()
        mock_peer = MagicMock()
        mock_peer.message = MagicMock(return_value=mock_msg)
        mock_session = MagicMock()
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        mock_instance.session = MagicMock(return_value=mock_session)
        self._setup(monkeypatch, mock_peer, mock_session, mock_instance)

        meta = {"tags": ["cloud"], "id": 1}
        hc.add_story("story text", metadata=meta)

        mock_peer.message.assert_called_once_with("story text", metadata=meta)
        mock_session.add_messages.assert_called_once_with([mock_msg])

    def test_returns_false_if_add_messages_raises(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.message = MagicMock(return_value=MagicMock())
        mock_session = MagicMock()
        mock_session.add_messages = MagicMock(side_effect=Exception("network error"))
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        mock_instance.session = MagicMock(return_value=mock_session)
        self._setup(monkeypatch, mock_peer, mock_session, mock_instance)

        assert hc.add_story("story") is False

    def test_metadata_is_optional(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.message = MagicMock(return_value=MagicMock())
        mock_session = MagicMock()
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        mock_instance.session = MagicMock(return_value=mock_session)
        self._setup(monkeypatch, mock_peer, mock_session, mock_instance)

        # Should not raise
        result = hc.add_story("story with no metadata")
        assert result is True


# ──────────────────────────────────────────────────────────────────────────────
# query_context
# ──────────────────────────────────────────────────────────────────────────────

class TestQueryContext:
    def _setup(self, monkeypatch, mock_peer, mock_instance):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "test-key")
        monkeypatch.setattr(config, "HONCHO_PEER_ID", "frank")
        monkeypatch.setattr(hc, "_get_client", lambda: mock_instance)
        monkeypatch.setattr(hc, "_initialised", True)

    def test_returns_chat_response(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.chat = MagicMock(return_value="Frank led a cloud migration at GM.")
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        self._setup(monkeypatch, mock_peer, mock_instance)

        result = hc.query_context("What are Frank's cloud strengths?")
        assert result == "Frank led a cloud migration at GM."

    def test_calls_peer_chat_with_query(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.chat = MagicMock(return_value="response")
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        self._setup(monkeypatch, mock_peer, mock_instance)

        hc.query_context("Tell me about leadership stories")
        mock_peer.chat.assert_called_once_with("Tell me about leadership stories")

    def test_returns_none_if_chat_raises(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.chat = MagicMock(side_effect=Exception("timeout"))
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        self._setup(monkeypatch, mock_peer, mock_instance)

        assert hc.query_context("anything") is None

    def test_returns_none_if_chat_returns_none(self, monkeypatch):
        mock_peer = MagicMock()
        mock_peer.chat = MagicMock(return_value=None)
        mock_instance = MagicMock()
        mock_instance.peer = MagicMock(return_value=mock_peer)
        self._setup(monkeypatch, mock_peer, mock_instance)

        assert hc.query_context("anything") is None


# ──────────────────────────────────────────────────────────────────────────────
# reset()
# ──────────────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_initialised_flag(self):
        hc._initialised = True
        hc._client = MagicMock()
        hc.reset()
        assert hc._initialised is False
        assert hc._client is None

    def test_reset_allows_reinitialisation(self, monkeypatch):
        monkeypatch.setattr(config, "HONCHO_API_KEY", "")
        hc._get_client()  # initialises with no key → None
        assert hc._initialised is True
        hc.reset()
        assert hc._initialised is False


# ──────────────────────────────────────────────────────────────────────────────
# tools/context.py — Honcho write path
# ──────────────────────────────────────────────────────────────────────────────

class TestContextToolsHonchoWritePath:
    """Verify log_personal_story calls honcho_client.add_story when available."""

    def test_add_story_called_on_log(self, isolated_server, monkeypatch):
        mock_add = MagicMock(return_value=True)
        monkeypatch.setattr(hc, "add_story", mock_add)

        srv.log_personal_story(
            story="Migrated 40 apps to Azure in 18 months.",
            tags=["cloud", "azure"],
            title="Azure migration",
        )

        assert mock_add.called
        args, kwargs = mock_add.call_args
        assert "Azure migration" in args[0]
        assert "Migrated 40 apps" in args[0]

    def test_honcho_metadata_includes_tags_and_title(self, isolated_server, monkeypatch):
        mock_add = MagicMock(return_value=True)
        monkeypatch.setattr(hc, "add_story", mock_add)

        srv.log_personal_story(
            story="Built CI/CD pipeline for 12 squads.",
            tags=["ci_cd", "devops"],
            title="CI/CD pipeline rollout",
            people=["Tim", "Sarah"],
        )

        _, kwargs = mock_add.call_args
        meta = kwargs.get("metadata") or mock_add.call_args[1].get("metadata") or {}
        # metadata passed as kwarg
        assert meta.get("tags") == ["ci_cd", "devops"]
        assert meta.get("title") == "CI/CD pipeline rollout"
        assert "Tim" in meta.get("people", [])

    def test_json_still_written_even_if_honcho_fails(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "add_story", MagicMock(return_value=False))

        srv.log_personal_story(story="JSON backup story.", tags=["backup"])

        import json
        data = json.loads(srv.PERSONAL_CONTEXT_FILE.read_text())
        assert len(data["stories"]) == 1
        assert "JSON backup story" in data["stories"][0]["story"]

    def test_return_value_unaffected_by_honcho_status(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "add_story", MagicMock(return_value=False))
        result = srv.log_personal_story(story="Story.", tags=["test"])
        assert "✓" in result


# ──────────────────────────────────────────────────────────────────────────────
# tools/context.py — Honcho read path
# ──────────────────────────────────────────────────────────────────────────────

class TestContextToolsHonchoReadPath:
    """Verify get_personal_context uses Honcho synthesis when available."""

    def test_uses_honcho_when_available(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=True))
        monkeypatch.setattr(hc, "query_context", MagicMock(return_value="Honcho synthesised this."))

        result = srv.get_personal_context()
        assert result == "Honcho synthesised this."

    def test_query_includes_tag_when_provided(self, isolated_server, monkeypatch):
        mock_query = MagicMock(return_value="Filtered response.")
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=True))
        monkeypatch.setattr(hc, "query_context", mock_query)

        srv.get_personal_context(tag="cloud")

        query_str = mock_query.call_args[0][0]
        assert "cloud" in query_str

    def test_query_includes_person_when_provided(self, isolated_server, monkeypatch):
        mock_query = MagicMock(return_value="Person filtered.")
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=True))
        monkeypatch.setattr(hc, "query_context", mock_query)

        srv.get_personal_context(person="Sachin")

        query_str = mock_query.call_args[0][0]
        assert "Sachin" in query_str

    def test_falls_back_to_json_when_honcho_unavailable(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=False))
        srv.log_personal_story(story="A real JSON story.", tags=["test"])

        result = srv.get_personal_context()
        assert "A real JSON story" in result

    def test_falls_back_to_json_when_query_returns_none(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=True))
        monkeypatch.setattr(hc, "query_context", MagicMock(return_value=None))
        srv.log_personal_story(story="Fallback story here.", tags=["fallback"])

        result = srv.get_personal_context()
        assert "Fallback story here" in result

    def test_fallback_empty_message_when_no_json_stories(self, isolated_server, monkeypatch):
        monkeypatch.setattr(hc, "is_available", MagicMock(return_value=True))
        monkeypatch.setattr(hc, "query_context", MagicMock(return_value=None))

        result = srv.get_personal_context()
        assert "No personal stories" in result
