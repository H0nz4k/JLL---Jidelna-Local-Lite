"""BusinessSession: provozní režim vždy bypassuje klientské termíny."""

from __future__ import annotations

from pathlib import Path

from jll.business_session import (
    DEFAULT_SUP,
    DEFAULT_VED,
    VED_DEFAULT_PERMISSIONS,
    BusinessSession,
)
from jll.identity_store import IdentityStore
from jll.legacy_users import LegacyUserRow
from jll.policy import Permission
from jll.sup_secret import SupSecretStore


def test_current_policy_bypass_order_deadlines_regardless_of_code(
    tmp_path: Path,
) -> None:
    identity = IdentityStore(tmp_path / "users.json")
    users = {
        "VED": LegacyUserRow(
            code="VED",
            display_name="Vedoucí",
            is_admin=False,
            typ="INTERNI",
            disabled=False,
            prava="ABC",
            prava1="XYZ",
            has_password=True,
        ),
        "KUCH": LegacyUserRow(
            code="KUCH",
            display_name="Kuchyň",
            is_admin=False,
            typ="INTERNI",
            disabled=False,
            prava="ABC",
            prava1="XYZ",
            has_password=False,
        ),
    }

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeRepo:
        def __init__(self, _conn):
            pass

        def get_user(self, code):
            return users.get(code.upper())

        def list_users(self, include_disabled=True):
            return tuple(users.values())

    from jll import business_session as bs_mod
    from jll import legacy_users as lu_mod

    original_lu = lu_mod.LegacyUserRepository
    original_bs = bs_mod.LegacyUserRepository
    lu_mod.LegacyUserRepository = FakeRepo  # type: ignore[misc]
    bs_mod.LegacyUserRepository = FakeRepo  # type: ignore[misc]
    try:
        session = object.__new__(BusinessSession)
        session.config = type(
            "C",
            (),
            {
                "site_id": "TEST",
                "instance_id": "STAN1",
                "allowed_categories": frozenset({"1JARO"}),
            },
        )()
        session.identity_store = identity
        session.connection_factory = lambda: FakeConn()
        session.sup_store = SupSecretStore("STAN1", fallback_dir=tmp_path)
        session.client_version = "0.1.0"
        session.current_code = DEFAULT_VED
        session._sup_until = 0.0
        session._session_id = "abc"
        identity.initialize(
            [
                (
                    "usr_aaaaaaaaaaaa",
                    "Vedoucí",
                    DEFAULT_VED,
                    "unused-pin-aaaa",
                    VED_DEFAULT_PERMISSIONS,
                ),
                (
                    "usr_bbbbbbbbbbbb",
                    "Kuchyň",
                    "KUCH",
                    "unused-pin-bbbb",
                    VED_DEFAULT_PERMISSIONS,
                ),
                (
                    "usr_cccccccccccc",
                    "Admin SUP",
                    DEFAULT_SUP,
                    "unused-pin-cccc",
                    frozenset(Permission),
                ),
            ]
        )
        session.bootstrap_ved()
        assert session.current_policy().bypass_order_deadlines is True
        session.switch_user("KUCH")
        assert session.current_code == "KUCH"
        assert session.current_policy().bypass_order_deadlines is True
    finally:
        lu_mod.LegacyUserRepository = original_lu  # type: ignore[misc]
        bs_mod.LegacyUserRepository = original_bs  # type: ignore[misc]
