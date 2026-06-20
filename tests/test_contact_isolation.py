"""Regression tests for multi-tenant contact info isolation.

Verifies that the owner's contact block (stored in the base config) never
leaks to a per-user session that has no config.json of its own.
"""
import json
import importlib

import pytest

import lib.config as cfg_module
import lib.user_context as uctx


@pytest.fixture(autouse=True)
def _reset_context():
    """Ensure context vars are clean before and after each test."""
    yield
    # Reset data folder and active config overrides
    _DATA_FOLDER_CTX = uctx._DATA_FOLDER_CTX
    token = _DATA_FOLDER_CTX.set("")
    _DATA_FOLDER_CTX.reset(token)
    active_token = cfg_module._ACTIVE_CONFIG_CTX.set(None)
    cfg_module._ACTIVE_CONFIG_CTX.reset(active_token)


def _patch_base_cfg(monkeypatch, contact: dict):
    """Inject a fake base _cfg with the given contact block."""
    fake_cfg = {"contact": contact, "resume_folder": "", "data_folder": ""}
    monkeypatch.setattr(cfg_module, "_cfg", fake_cfg)


class TestContactIsolation:
    def test_owner_contact_not_leaked_to_unregistered_user(self, monkeypatch, tmp_path):
        """A beta user with no config.json must get empty contact info, not the owner's."""
        _patch_base_cfg(monkeypatch, {
            "name": "Owner Name",
            "email": "owner@example.com",
            "phone": "555-000-0000",
            "github": "OwnerGitHub",
        })

        # Simulate a per-user data folder that has no config.json
        user_data_dir = tmp_path / "users" / "beta-user-oid"
        user_data_dir.mkdir(parents=True)

        token = uctx.set_data_folder(str(user_data_dir))
        try:
            result = cfg_module.get_contact_info()
        finally:
            uctx.reset_data_folder(token)

        assert result == {}, (
            f"Owner contact block leaked to unconfigured user: {result}"
        )

    def test_owner_contact_not_leaked_to_contact_name(self, monkeypatch, tmp_path):
        """get_contact_name() must return empty string for an unconfigured user."""
        _patch_base_cfg(monkeypatch, {
            "name": "Owner Name",
            "email": "owner@example.com",
        })

        user_data_dir = tmp_path / "users" / "beta-user-oid"
        user_data_dir.mkdir(parents=True)

        token = uctx.set_data_folder(str(user_data_dir))
        try:
            name = cfg_module.get_contact_name("")
        finally:
            uctx.reset_data_folder(token)

        assert name == "", f"Owner name leaked to unconfigured user: {name!r}"

    def test_user_own_contact_returned_when_config_present(self, monkeypatch, tmp_path):
        """A beta user who HAS a config.json gets their own contact block."""
        _patch_base_cfg(monkeypatch, {
            "name": "Owner Name",
            "email": "owner@example.com",
        })

        user_data_dir = tmp_path / "users" / "beta-user-oid"
        user_data_dir.mkdir(parents=True)
        user_cfg = {"contact": {"name": "Beta User", "email": "beta@example.com"}}
        (user_data_dir / "config.json").write_text(json.dumps(user_cfg), encoding="utf-8")

        token = uctx.set_data_folder(str(user_data_dir))
        try:
            result = cfg_module.get_contact_info()
        finally:
            uctx.reset_data_folder(token)

        assert result["name"] == "Beta User"
        assert result["email"] == "beta@example.com"
        assert "Owner Name" not in str(result)

    def test_owner_session_gets_own_contact(self, monkeypatch):
        """When no per-user override is active, base config contact is returned normally."""
        _patch_base_cfg(monkeypatch, {
            "name": "Owner Name",
            "email": "owner@example.com",
        })

        result = cfg_module.get_contact_info()
        assert result["name"] == "Owner Name"
