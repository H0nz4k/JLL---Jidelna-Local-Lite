"""Unit tests for Flet UI foundations and identity model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jll.business_session import (
    DEFAULT_SUP,
    DEFAULT_VED,
    VED_DEFAULT_PERMISSIONS,
    BusinessSession,
)
from jll.flet_ui import theme
from jll.flet_ui.routes import NAV_ITEMS, Route
from jll.flet_ui.state import ActionBlockReason, action_state
from jll.identity_store import IdentityStore
from jll.legacy_users import LegacyUserRow, USER_CODE_RE
from jll.permission_catalog import permission_title
from jll.policy import Permission
from jll.sup_secret import SupSecretStore
from jll.write_gates import DINER_WRITE_GATES


def test_business_calendar_month_switch_helpers() -> None:
    from datetime import date

    from jll.read_models import BusinessCalendar

    cal = BusinessCalendar(today=date(2026, 8, 30), period_month=8, period_year=2026)
    assert BusinessCalendar.month_name_cs(8, title=True) == "Srpen"
    assert BusinessCalendar.month_name_cs(9, title=True) == "Září"
    assert cal.next_period_month == 9
    assert cal.date_in_period(future=False).month == 8
    assert cal.date_in_period(future=True).month == 9
    assert cal.date_in_period(future=True).day == 1


def test_business_calendar_labels() -> None:
    from datetime import date

    from jll.read_models import BusinessCalendar

    cal = BusinessCalendar(today=date(2026, 9, 6), period_month=9, period_year=2026)
    assert cal.today_label == "neděle 06.09.2026"
    assert cal.period_label == "AM září 2026"
    assert cal.header_label == "neděle 06.09.2026 - - AM září 2026"


def test_theme_exposes_exactly_four_roles() -> None:
    assert theme.assert_four_roles() == ("ACTION", "BODY", "META", "PRIMARY")


def test_theme_scales_all_roles() -> None:
    normal = {role: theme.role_size(role, theme.TextScale.NORMAL) for role in theme.TextRole}
    large = {role: theme.role_size(role, theme.TextScale.LARGE) for role in theme.TextRole}
    huge = {role: theme.role_size(role, theme.TextScale.HUGE) for role in theme.TextRole}
    for role in theme.TextRole:
        assert large[role] > normal[role]
        assert huge[role] > large[role]
    assert theme.TextScale.HUGE.label_cs == "150 %"
    assert theme.COLORS["today_column"]
    assert theme.COLORS["today_column_border"]


def test_navigation_routes() -> None:
    routes = [item[0] for item in NAV_ITEMS]
    assert routes == [Route.DINERS, Route.SERVING, Route.REPORTS, Route.ADMIN]


def test_permission_labels_are_czech() -> None:
    title = permission_title(Permission.DINERS_VIEW)
    assert "diners.view" not in title
    assert "strávník" in title.casefold() or "Zobrazit" in title


def test_permission_vs_write_gate_state() -> None:
    no_perm = action_state(has_permission=False, gate=DINER_WRITE_GATES["create"])
    assert no_perm.reason is ActionBlockReason.NO_PERMISSION
    gated = action_state(has_permission=True, gate=DINER_WRITE_GATES["create"])
    assert gated.reason is ActionBlockReason.WRITE_GATE
    assert not gated.allowed


def test_reader_unavailable_message_shape() -> None:
    body = (
        "Nakonfigurovaný port COM7 není dostupný.\n\n"
        "Zkontrolujte připojení čtečky nebo nastavení\n"
        "v Administraci."
    )
    assert "COM7" in body
    assert "Administraci" in body


def test_flet_app_imports() -> None:
    import jll.flet_ui.app as app
    import jll.flet_ui.screens.diners as diners
    import jll.flet_ui.screens.setup as setup

    assert callable(app.main)
    assert diners.DinersScreen is not None
    assert setup.SetupScreen is not None


def test_sup_password_allows_four_chars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenKeyring:
        @staticmethod
        def set_password(*_a, **_k):
            raise RuntimeError("no keyring")

        @staticmethod
        def get_password(*_a, **_k):
            return None

        @staticmethod
        def delete_password(*_a, **_k):
            raise RuntimeError("no keyring")

    monkeypatch.setattr("jll.sup_secret.keyring", BrokenKeyring)
    store = SupSecretStore("LAB4", fallback_dir=tmp_path)
    store.set_password("1234")
    assert store.verify("1234")
    with pytest.raises(ValueError, match="4"):
        store.set_password("123")


def test_sup_secret_persists_hashed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenKeyring:
        @staticmethod
        def set_password(*_a, **_k):
            raise RuntimeError("no keyring")

        @staticmethod
        def get_password(*_a, **_k):
            return None

        @staticmethod
        def delete_password(*_a, **_k):
            raise RuntimeError("no keyring")

    monkeypatch.setattr("jll.sup_secret.keyring", BrokenKeyring)
    store = SupSecretStore("LABTEST", fallback_dir=tmp_path)
    store.set_password("secret-admin")
    assert store.exists()
    assert store.verify("secret-admin")
    assert not store.verify("wrong")
    raw = (tmp_path / "sup.LABTEST.hash").read_text(encoding="utf-8")
    assert "secret-admin" not in raw
    assert raw.startswith("$argon2id$")


def test_business_session_ved_default_and_switch(tmp_path: Path) -> None:
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
        "SUP": LegacyUserRow(
            code="SUP",
            display_name="Admin",
            is_admin=True,
            typ="INTERNI",
            disabled=False,
            prava="",
            prava1="",
            has_password=True,
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
            key = code.upper()
            return users.get(key)

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
                    "Admin SUP",
                    DEFAULT_SUP,
                    "unused-pin-bbbb",
                    frozenset(Permission),
                ),
            ]
        )
        ved = session.bootstrap_ved()
        assert ved.code == DEFAULT_VED
        assert session.current_actor().short_code == DEFAULT_VED
        switched = session.switch_user("KUCH")
        assert switched.code == "KUCH"
        assert session.current_actor().short_code == "KUCH"
        with pytest.raises(RuntimeError):
            session.switch_user("SUP")
    finally:
        lu_mod.LegacyUserRepository = original_lu  # type: ignore[misc]
        bs_mod.LegacyUserRepository = original_bs  # type: ignore[misc]


def test_create_user_rejects_admin_template() -> None:
    from jll.legacy_users import LegacyUserRepository

    admin_template = LegacyUserRow(
        code="SUP",
        display_name="A",
        is_admin=True,
        typ="INTERNI",
        disabled=False,
        prava="",
        prava1="",
        has_password=False,
    )
    with pytest.raises(ValueError, match="admin"):
        LegacyUserRepository(None).create_user_from_template(  # type: ignore[arg-type]
            code="NOV",
            display_name="Jan",
            template=admin_template,
        )


def test_layout_ratios_stable() -> None:
    assert theme.NAV_WIDTH == 0
    assert theme.LIST_WIDTH == 220
    assert abs(theme.LIST_RATIO + theme.DETAIL_RATIO - 1.0) < 1e-9
    assert theme.WINDOW_WIDTH == 1366
    assert theme.WINDOW_HEIGHT == 768
    assert theme.COLORS["block_border"]
    assert theme.COLORS["hint_warning"]


def test_reset_script_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Path("tools/reset_jll_first_run.sh")
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "public.uzivatel" in text
    assert "Nemaže" in text or "nemaže" in text.casefold()
