"""Tests for the Home greeting name derivation (transport/http/routes/dashboard/api.py).

The mobile app authenticates by PAT, which identifies the user by OID but
carries no display name — so the greeting fell back to "there" and the
avatar rendered a confusing "T". These pin the fix: a real name wins; a
placeholder identity falls back to the tenant's contact name.
"""
from __future__ import annotations

import pytest

from transport.http.routes.dashboard.api import _first_name, _welcome
from transport.http.security import User


class TestFirstName:
    def test_real_name(self):
        assert _first_name(User(id="x", name="Frank MacBride")) == "Frank"

    @pytest.mark.parametrize("placeholder", ["api-key", "Admin", "admin", "", "API-KEY"])
    def test_placeholders_yield_there(self, placeholder):
        assert _first_name(User(id="x", name=placeholder)) == "there"


class TestWelcome:
    def test_real_name_wins(self, monkeypatch):
        name, is_default = _welcome(User(id="x", name="Frank MacBride"))
        assert (name, is_default) == ("Frank", False)

    def test_pat_falls_back_to_contact_name(self, monkeypatch):
        # cloud PAT request: name "api-key", OID known — should greet by the
        # tenant's contact name rather than "there".
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {"name": "Frank MacBride"})
        name, is_default = _welcome(User(id="oid-123", name="api-key"))
        assert (name, is_default) == ("Frank", False)

    def test_admin_synthetic_falls_back_to_contact_name(self, monkeypatch):
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {"name": "Frank MacBride"})
        name, is_default = _welcome(User(id="admin", name="Admin"))
        assert (name, is_default) == ("Frank", False)

    def test_no_name_anywhere_is_placeholder(self, monkeypatch):
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {"name": ""})
        monkeypatch.setattr(
            "lib.app_dirs.is_desktop_mode", lambda: False, raising=False
        )
        name, is_default = _welcome(User(id="oid", name="api-key"))
        assert (name, is_default) == ("there", True)


class TestBackfillContactName:
    def test_real_name_backfills_empty_contact(self, tmp_path, monkeypatch):
        from transport.http.routes.dashboard.api import _backfill_contact_name
        import lib.config as cfg
        import lib.user_context as uc
        import json

        (tmp_path / "config.json").write_text(json.dumps({"contact": {"name": ""}}), encoding="utf-8")
        monkeypatch.setattr(uc, "get_data_folder_override", lambda: tmp_path, raising=False)
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {"name": ""})
        monkeypatch.setattr(cfg, "update_runtime_config", lambda *a, **k: None)

        _backfill_contact_name(User(id="oid", name="Frank MacBride"))
        written = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert written["contact"]["name"] == "Frank MacBride"

    def test_placeholder_name_does_not_write(self, tmp_path, monkeypatch):
        from transport.http.routes.dashboard.api import _backfill_contact_name
        import lib.user_context as uc
        import json

        (tmp_path / "config.json").write_text(json.dumps({"contact": {"name": ""}}), encoding="utf-8")
        monkeypatch.setattr(uc, "get_data_folder_override", lambda: tmp_path, raising=False)

        _backfill_contact_name(User(id="oid", name="api-key"))
        written = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert written["contact"]["name"] == ""  # untouched

    def test_existing_contact_not_overwritten(self, tmp_path, monkeypatch):
        from transport.http.routes.dashboard.api import _backfill_contact_name
        import lib.config as cfg
        import lib.user_context as uc

        monkeypatch.setattr(uc, "get_data_folder_override", lambda: tmp_path, raising=False)
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {"name": "Existing Name"})
        # no config file created — if it tried to write it would fail; it must short-circuit
        _backfill_contact_name(User(id="oid", name="Someone Else"))
        assert not (tmp_path / "config.json").exists()

    def test_never_raises(self, monkeypatch):
        from transport.http.routes.dashboard.api import _backfill_contact_name
        import lib.user_context as uc

        def boom():
            raise RuntimeError("context blew up")
        monkeypatch.setattr(uc, "get_data_folder_override", boom, raising=False)
        _backfill_contact_name(User(id="oid", name="Frank"))  # must not raise
