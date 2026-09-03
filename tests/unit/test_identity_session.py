from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher, Type
from PySide6.QtWidgets import QMessageBox

from jll.admin_service import AdminReauthenticationRequired, AdminService
from jll.config import LabConfig
from jll.gui.login_dialog import LoginDialog
from jll.gui.setup_wizard import SetupWizard
from jll.identity_store import (
    AuthenticationError,
    IdentityStore,
    IdentityStoreError,
)
from jll.orders.errors import OrderBusinessError
from jll.policy import Permission
from jll.session import AuthService, SessionManager


def fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )


def config() -> LabConfig:
    return LabConfig(
        site_name="DEMO LAB",
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        allowed_categories=frozenset({"KAT2"}),
        host="127.0.0.1",
        port=5433,
        database="jll_test",
        user="postgres",
        environment="lab",
        expected_system_identifier="1000000000000000001",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
    )


def initialized_store(path: Path) -> IdentityStore:
    store = IdentityStore(path, password_hasher=fast_hasher())
    store.initialize(
        [
            (
                "admin",
                "LAB Admin",
                "ADM",
                "2468",
                frozenset(Permission),
            ),
            (
                "user",
                "LAB User",
                "USR",
                "1357",
                frozenset(
                    {Permission.DINERS_VIEW, Permission.ORDERS_VIEW}
                ),
            ),
        ]
    )
    return store


def test_identity_store_hashes_pin_and_keeps_last_admin(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    store = initialized_store(path)
    raw = path.read_text(encoding="utf-8")
    assert '"2468"' not in raw
    assert "$argon2id$" in raw
    assert store.authenticate("admin", "2468").short_code == "ADM"
    with pytest.raises(AuthenticationError):
        store.authenticate("admin", "wrong")

    with pytest.raises(IdentityStoreError, match="Posledního"):
        store.set_active(actor="TEST:ADM", user_id="admin", active=False)
    assert store.get_user("admin").active  # type: ignore[union-attr]


def test_authentication_rate_limit_is_time_bounded(tmp_path: Path) -> None:
    store = initialized_store(tmp_path / "users.json")
    now = [10.0]
    auth = AuthService(
        store,
        max_attempts=2,
        window_seconds=30,
        clock=lambda: now[0],
    )
    for _ in range(2):
        with pytest.raises(AuthenticationError, match="Neplatný"):
            auth.authenticate("admin", "wrong")
    with pytest.raises(AuthenticationError, match="dočasně"):
        auth.authenticate("admin", "2468")
    now[0] += 31
    assert auth.authenticate("admin", "2468").user_id == "admin"


def test_session_policy_refresh_and_actor_context(tmp_path: Path) -> None:
    store = initialized_store(tmp_path / "users.json")
    session = SessionManager(config(), store)
    session.start(store.authenticate("user", "1357"))
    assert Permission.ORDERS_CHANGE not in session.current_policy().permissions

    store.set_permissions(
        actor="DEMO-LAB01:ADM",
        user_id="user",
        permissions=frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.ORDERS_VIEW,
                Permission.ORDERS_CHANGE,
            }
        ),
    )

    assert Permission.ORDERS_CHANGE in session.current_policy().permissions
    actor = session.current_actor()
    assert actor.audit_actor == "DEMO-LAB01:USR"
    assert actor.audit_actor != "JLL"
    assert actor.session_id


def test_admin_requires_reauth_and_audits_permission_change(
    tmp_path: Path,
) -> None:
    store = initialized_store(tmp_path / "users.json")
    session = SessionManager(config(), store)
    session.start(store.authenticate("admin", "2468"))
    now = [100.0]
    admin = AdminService(
        session,
        AuthService(store),
        store,
        reauth_seconds=10,
        clock=lambda: now[0],
    )
    with pytest.raises(AdminReauthenticationRequired):
        admin.list_users()
    admin.reauthenticate("2468")
    admin.set_permissions(
        "user",
        frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.ORDERS_VIEW,
                Permission.ORDERS_CHANGE,
            }
        ),
    )
    assert any(
        event["action"] == "user.permissions_changed"
        and event["actor"] == "DEMO-LAB01:ADM"
        for event in admin.audit_events()
    )
    now[0] += 11
    with pytest.raises(AdminReauthenticationRequired):
        admin.list_users()


def test_reader_diagnostics_requires_specific_permission(tmp_path: Path) -> None:
    store = initialized_store(tmp_path / "users.json")
    session = SessionManager(config(), store)
    session.start(store.authenticate("admin", "2468"))
    admin = AdminService(session, AuthService(store), store)
    admin.reauthenticate("2468")
    store.set_permissions(
        actor="DEMO-LAB01:ADM",
        user_id="admin",
        permissions=frozenset(Permission) - {Permission.ADMIN_READER},
    )
    with pytest.raises(OrderBusinessError, match="oprávnění"):
        admin.require_reader_diagnostics()


def test_login_dialog_authenticates_concrete_user(
    tmp_path: Path,
    qtbot: Any,
) -> None:
    store = initialized_store(tmp_path / "users.json")
    dialog = LoginDialog(config(), AuthService(store))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.user_combo.setCurrentIndex(
        dialog.user_combo.findData("admin")
    )
    dialog.pin_edit.setText("2468")
    with qtbot.waitSignal(dialog.accepted, timeout=3_000):
        dialog.login_button.click()
    assert dialog.selected_user is not None
    assert dialog.selected_user.user_id == "admin"


def test_setup_wizard_fails_closed_before_database_probe(
    tmp_path: Path,
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    wizard = SetupWizard(
        tmp_path / "lab.json",
        tmp_path / "users.json",
        None,
    )
    qtbot.addWidget(wizard)
    wizard.show()
    qtbot.waitUntil(lambda: wizard.currentId() == SetupWizard.PAGE_DATABASE)
    assert not wizard.validateCurrentPage()
    assert warnings == ["Nejprve úspěšně otestujte databázi."]
    with pytest.raises(ValueError, match="loopback"):
        wizard._probe_database(
            ("production.example", "5432", "jll_prod", "user", "")
        )
