"""The Home-greeting contact backfill must not leak across tenants.

_backfill_contact_name persists a display name into the active tenant's
config.json. Under a per-tenant data-folder override it must write ONLY the
file; mutating the shared in-memory config would leak one tenant's contact
block to every other tenant whose request falls back to the base config.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from lib import config, user_context
from lib.resume_parser import _get_contact_defaults
from transport.http.routes.dashboard.api import _backfill_contact_name


def test_backfill_does_not_mutate_global_in_tenant_mode(tmp_path, monkeypatch):
    before = dict(config._cfg.get("contact", {}))

    a = tmp_path / "users" / "oid-a"
    a.mkdir(parents=True)
    (a / "config.json").write_text(
        json.dumps({"contact": {"name": "", "email": "a@attacker.example"}})
    )
    t1 = user_context.set_data_folder(a)
    t2 = user_context.set_user_oid("oid-a")
    try:
        _backfill_contact_name(SimpleNamespace(name="Alice Attacker"))
    finally:
        user_context.reset_data_folder(t1)
        user_context.reset_user_oid(t2)

    # The tenant's own file was updated...
    assert json.loads((a / "config.json").read_text())["contact"]["name"] == "Alice Attacker"
    # ...but the shared in-memory config was not polluted.
    assert config._cfg.get("contact", {}) == before

    # A different tenant with no config of its own sees nothing from tenant A.
    b = tmp_path / "users" / "oid-b"
    b.mkdir(parents=True)
    t1 = user_context.set_data_folder(b)
    try:
        seen_by_b = _get_contact_defaults()
    finally:
        user_context.reset_data_folder(t1)
    assert "attacker.example" not in seen_by_b.get("email", "")
