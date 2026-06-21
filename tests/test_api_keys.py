"""Tests for lib/api_keys.py and EntraAuthProvider API-key branch.

Covers:
- generate_api_key format and uniqueness
- create_key inserts a row; returns (id, plaintext) with jcmcp_ prefix
- lookup_key: valid token → oid; invalid token → None; wrong prefix → None
- lookup_key: updates last_used_at on hit
- list_keys: returns rows for the right oid, never key_hash
- revoke_key: deletes own key; ignores wrong-owner attempt
- EntraAuthProvider: jcmcp_ bearer → routes to correct oid
- EntraAuthProvider: invalid jcmcp_ bearer → returns None
- EntraAuthProvider: non-jcmcp_ bearer still goes to Entra JWT path
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def global_db(tmp_path, monkeypatch):
    """Provide a fresh in-memory-style SQLite DB wired to lib.db.global_db_path."""
    from scripts.migrate_to_sqlite import _SCHEMA

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_file = db_dir / "jobcontextmcp.db"

    con = sqlite3.connect(db_file)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()

    import lib.db as _db
    monkeypatch.setattr(_db, "global_db_path", lambda: db_file)
    # Also patch db_path so get_connection(path=None) in user_context-less contexts
    # hits the same DB.
    monkeypatch.setattr(_db, "db_path", lambda: db_file)

    # Patch lib.user_context so get_data_folder_override() returns None
    # (no per-user context active during these tests)
    import lib.user_context as uctx
    token = uctx._DATA_FOLDER_CTX.set("")
    yield db_file
    uctx._DATA_FOLDER_CTX.reset(token)


# ── lib/api_keys tests ────────────────────────────────────────────────────────

class TestCreateKey:
    def test_returns_int_id_and_plaintext(self, global_db):
        from lib.api_keys import create_key
        key_id, plaintext = create_key("oid-alice", "my shortcut")
        assert isinstance(key_id, int)
        assert isinstance(plaintext, str)

    def test_plaintext_has_jcmcp_prefix(self, global_db):
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice")
        assert plaintext.startswith("jcmcp_")

    def test_plaintext_length(self, global_db):
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice")
        # "jcmcp_" (6) + 32 url-safe base64 chars from 24 bytes
        assert len(plaintext) >= 38

    def test_each_call_generates_unique_key(self, global_db):
        from lib.api_keys import create_key
        _, k1 = create_key("oid-alice")
        _, k2 = create_key("oid-alice")
        assert k1 != k2

    def test_hash_stored_not_plaintext(self, global_db):
        """The DB must not contain the plaintext token."""
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice", "test key")
        con = sqlite3.connect(global_db)
        rows = con.execute("SELECT key_hash FROM user_api_keys").fetchall()
        con.close()
        stored_hashes = [r[0] for r in rows]
        assert plaintext not in stored_hashes
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        assert expected_hash in stored_hashes

    def test_label_stored(self, global_db):
        from lib.api_keys import create_key
        key_id, _ = create_key("oid-alice", "iPhone")
        con = sqlite3.connect(global_db)
        row = con.execute("SELECT label FROM user_api_keys WHERE id = ?", (key_id,)).fetchone()
        con.close()
        assert row[0] == "iPhone"

    def test_empty_label_stored_as_empty_string(self, global_db):
        from lib.api_keys import create_key
        key_id, _ = create_key("oid-alice")
        con = sqlite3.connect(global_db)
        row = con.execute("SELECT label FROM user_api_keys WHERE id = ?", (key_id,)).fetchone()
        con.close()
        assert row[0] == ""


class TestLookupKey:
    def test_valid_token_returns_oid(self, global_db):
        from lib.api_keys import create_key, lookup_key
        _, plaintext = create_key("oid-alice")
        assert lookup_key(plaintext) == "oid-alice"

    def test_unknown_token_returns_none(self, global_db):
        from lib.api_keys import lookup_key
        assert lookup_key("jcmcp_doesnotexist123456789012345678") is None

    def test_non_jcmcp_prefix_returns_none(self, global_db):
        from lib.api_keys import lookup_key
        # A real Entra JWT would start with "eyJ..." — must not be processed here
        assert lookup_key("eyJhbGciOiJSUzI1NiJ9.fake") is None

    def test_empty_string_returns_none(self, global_db):
        from lib.api_keys import lookup_key
        assert lookup_key("") is None

    def test_updates_last_used_at_on_hit(self, global_db):
        from lib.api_keys import create_key, lookup_key
        key_id, plaintext = create_key("oid-alice")

        # last_used_at starts NULL
        con = sqlite3.connect(global_db)
        row_before = con.execute(
            "SELECT last_used_at FROM user_api_keys WHERE id = ?", (key_id,)
        ).fetchone()
        con.close()
        assert row_before[0] is None

        lookup_key(plaintext)

        con = sqlite3.connect(global_db)
        row_after = con.execute(
            "SELECT last_used_at FROM user_api_keys WHERE id = ?", (key_id,)
        ).fetchone()
        con.close()
        assert row_after[0] is not None

    def test_does_not_update_last_used_on_miss(self, global_db):
        """A failed lookup must not leave any trace."""
        from lib.api_keys import lookup_key
        result = lookup_key("jcmcp_badtoken00000000000000000000")
        assert result is None
        con = sqlite3.connect(global_db)
        count = con.execute("SELECT COUNT(*) FROM user_api_keys").fetchone()[0]
        con.close()
        assert count == 0

    def test_correct_oid_returned_for_multiple_users(self, global_db):
        from lib.api_keys import create_key, lookup_key
        _, k_alice = create_key("oid-alice")
        _, k_bob = create_key("oid-bob")
        assert lookup_key(k_alice) == "oid-alice"
        assert lookup_key(k_bob) == "oid-bob"


class TestListKeys:
    def test_returns_keys_for_oid(self, global_db):
        from lib.api_keys import create_key, list_keys
        create_key("oid-alice", "key-1")
        create_key("oid-alice", "key-2")
        keys = list_keys("oid-alice")
        assert len(keys) == 2
        labels = {k.label for k in keys}
        assert labels == {"key-1", "key-2"}

    def test_does_not_return_other_users_keys(self, global_db):
        from lib.api_keys import create_key, list_keys
        create_key("oid-alice", "alice-key")
        create_key("oid-bob", "bob-key")
        alice_keys = list_keys("oid-alice")
        assert all(k.label == "alice-key" for k in alice_keys)
        assert len(alice_keys) == 1

    def test_empty_when_no_keys(self, global_db):
        from lib.api_keys import list_keys
        assert list_keys("oid-nobody") == []

    def test_no_key_hash_in_result(self, global_db):
        from lib.api_keys import create_key, list_keys, ApiKeyInfo
        create_key("oid-alice", "my key")
        keys = list_keys("oid-alice")
        for key in keys:
            assert isinstance(key, ApiKeyInfo)
            assert not hasattr(key, "key_hash")

    def test_result_has_expected_fields(self, global_db):
        from lib.api_keys import create_key, list_keys
        key_id, _ = create_key("oid-alice", "shortcut")
        keys = list_keys("oid-alice")
        assert len(keys) == 1
        k = keys[0]
        assert k.id == key_id
        assert k.label == "shortcut"
        assert k.created_at is not None
        assert k.last_used_at is None  # not used yet


class TestRevokeKey:
    def test_revoke_own_key_returns_true(self, global_db):
        from lib.api_keys import create_key, revoke_key
        key_id, _ = create_key("oid-alice")
        assert revoke_key(key_id, "oid-alice") is True

    def test_revoked_key_is_deleted(self, global_db):
        from lib.api_keys import create_key, revoke_key, lookup_key
        key_id, plaintext = create_key("oid-alice")
        revoke_key(key_id, "oid-alice")
        assert lookup_key(plaintext) is None

    def test_revoke_wrong_owner_returns_false(self, global_db):
        from lib.api_keys import create_key, revoke_key
        key_id, _ = create_key("oid-alice")
        # Bob tries to revoke Alice's key — must silently fail
        assert revoke_key(key_id, "oid-bob") is False

    def test_revoke_wrong_owner_does_not_delete(self, global_db):
        from lib.api_keys import create_key, revoke_key, lookup_key
        key_id, plaintext = create_key("oid-alice")
        revoke_key(key_id, "oid-bob")
        assert lookup_key(plaintext) == "oid-alice"

    def test_revoke_nonexistent_id_returns_false(self, global_db):
        from lib.api_keys import revoke_key
        assert revoke_key(999999, "oid-alice") is False

    def test_revoke_does_not_affect_other_keys(self, global_db):
        from lib.api_keys import create_key, revoke_key, lookup_key
        key_id1, plaintext1 = create_key("oid-alice", "key-1")
        _, plaintext2 = create_key("oid-alice", "key-2")
        revoke_key(key_id1, "oid-alice")
        assert lookup_key(plaintext1) is None
        assert lookup_key(plaintext2) == "oid-alice"


# ── EntraAuthProvider integration tests ──────────────────────────────────────

class TestEntraAuthProviderApiKey:
    """Verify EntraAuthProvider accepts jcmcp_ tokens via the lookup path."""

    @pytest.fixture(autouse=True)
    def _reset_provider(self):
        from transport.http.security import reset_auth_provider_cache
        yield
        reset_auth_provider_cache()

    def _make_provider(self, monkeypatch):
        """Return an EntraAuthProvider with Entra env vars set."""
        monkeypatch.setenv("ENTRA_TENANT_ID", "fake-tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "fake-client")
        from transport.http.security import reset_auth_provider_cache, EntraAuthProvider
        reset_auth_provider_cache()
        return EntraAuthProvider()

    def test_valid_api_key_returns_user_with_correct_oid(self, global_db, monkeypatch):
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice")

        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization=f"Bearer {plaintext}",
            session_token=None,
        )
        assert user is not None
        assert user.id == "oid-alice"

    def test_api_key_user_name_is_api_key(self, global_db, monkeypatch):
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice")

        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization=f"Bearer {plaintext}",
            session_token=None,
        )
        assert user is not None
        assert user.name == "api-key"

    def test_invalid_api_key_returns_none(self, global_db, monkeypatch):
        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization="Bearer jcmcp_totallyfaketoken00000000000000",
            session_token=None,
        )
        assert user is None

    def test_revoked_api_key_returns_none(self, global_db, monkeypatch):
        from lib.api_keys import create_key, revoke_key
        key_id, plaintext = create_key("oid-alice")
        revoke_key(key_id, "oid-alice")

        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization=f"Bearer {plaintext}",
            session_token=None,
        )
        assert user is None

    def test_non_api_key_bearer_falls_through_to_entra(self, global_db, monkeypatch):
        """A non-jcmcp_ token should attempt Entra validation, not API-key lookup.

        We expect None back (the fake JWT won't validate) — the point is it
        doesn't raise and doesn't return a User based on the DB lookup.
        """
        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization="Bearer eyJhbGciOiJSUzI1NiJ9.fake.jwt",
            session_token=None,
        )
        # validate_token will raise → caught → None
        assert user is None

    def test_no_credentials_returns_none(self, global_db, monkeypatch):
        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization=None,
            session_token=None,
        )
        assert user is None

    def test_api_key_in_session_token_field(self, global_db, monkeypatch):
        """jcmcp_ token sent as cookie/session_token (not bearer) should also work."""
        from lib.api_keys import create_key
        _, plaintext = create_key("oid-alice")

        provider = self._make_provider(monkeypatch)
        user = provider.authenticate_request(
            authorization=None,
            session_token=plaintext,
        )
        assert user is not None
        assert user.id == "oid-alice"
