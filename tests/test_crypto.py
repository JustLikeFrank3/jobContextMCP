"""Tests for lib/crypto.py — application-level secret encryption.

Covers:
  - round-trip encrypt -> decrypt with a configured key
  - ciphertext is prefixed and is not the plaintext
  - no-op when no key is configured (legacy plaintext behaviour)
  - legacy plaintext (no prefix) passes through decrypt unchanged
  - empty values are never wrapped
  - idempotent: encrypting an already-encrypted value does not double-wrap
  - wrong / missing key fails closed on decrypt
  - a malformed key disables encryption rather than crashing
"""
from __future__ import annotations

import importlib

import pytest

from cryptography.fernet import Fernet


@pytest.fixture()
def crypto_mod():
    import lib.crypto as crypto
    return importlib.reload(crypto)


@pytest.fixture()
def key(monkeypatch):
    k = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", k)
    return k


# ── round-trip ───────────────────────────────────────────────────────────────

def test_round_trip_with_key(crypto_mod, key):
    secret = "oura_access_token_abc123"
    enc = crypto_mod.encrypt_secret(secret)
    assert enc != secret
    assert enc.startswith("enc:v1:")
    assert crypto_mod.decrypt_secret(enc) == secret


def test_encryption_enabled_reflects_key(crypto_mod, key):
    assert crypto_mod.encryption_enabled() is True


def test_ciphertext_does_not_contain_plaintext(crypto_mod, key):
    secret = "super-secret-refresh-token"
    enc = crypto_mod.encrypt_secret(secret)
    assert secret not in enc


# ── no-key (legacy) behaviour ────────────────────────────────────────────────

def test_no_key_is_noop(crypto_mod, monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    # Ensure config fallback is also empty.
    import lib.config as cfg
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")

    assert crypto_mod.encryption_enabled() is False
    assert crypto_mod.encrypt_secret("plain") == "plain"
    assert crypto_mod.decrypt_secret("plain") == "plain"


def test_legacy_plaintext_passes_through_decrypt(crypto_mod, key):
    # A value stored before encryption was enabled has no prefix.
    assert crypto_mod.decrypt_secret("legacy_plaintext_value") == "legacy_plaintext_value"


def test_empty_values_never_wrapped(crypto_mod, key):
    assert crypto_mod.encrypt_secret("") == ""
    assert crypto_mod.decrypt_secret("") == ""


# ── idempotence / safety ─────────────────────────────────────────────────────

def test_encrypt_is_idempotent(crypto_mod, key):
    enc = crypto_mod.encrypt_secret("token")
    assert crypto_mod.encrypt_secret(enc) == enc  # not double-wrapped


def test_wrong_key_fails_closed(crypto_mod, monkeypatch):
    # Encrypt under key A
    key_a = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key_a)
    enc = crypto_mod.encrypt_secret("token-under-key-A")
    # Swap to key B and attempt decrypt
    key_b = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key_b)
    with pytest.raises(RuntimeError):
        crypto_mod.decrypt_secret(enc)


def test_encrypted_value_without_key_raises(crypto_mod, monkeypatch):
    key_a = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key_a)
    enc = crypto_mod.encrypt_secret("token")
    # Remove the key entirely; an encrypted value can no longer be read.
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    import lib.config as cfg
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setitem(cfg._cfg, "app_encryption_key", "")
    with pytest.raises(RuntimeError):
        crypto_mod.decrypt_secret(enc)


def test_malformed_key_disables_encryption(crypto_mod, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    assert crypto_mod.encryption_enabled() is False
    # Falls back to no-op rather than crashing.
    assert crypto_mod.encrypt_secret("plain") == "plain"


def test_config_fallback_key(crypto_mod, monkeypatch):
    """When the env var is unset, the config.json key is used."""
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    k = Fernet.generate_key().decode("ascii")
    import lib.config as cfg
    monkeypatch.setattr(cfg, "APP_ENCRYPTION_KEY", k, raising=False)

    enc = crypto_mod.encrypt_secret("via-config")
    assert enc.startswith("enc:v1:")
    assert crypto_mod.decrypt_secret(enc) == "via-config"
