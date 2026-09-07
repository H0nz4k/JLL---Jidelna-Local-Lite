"""FÁZE 3E – setup identity, stanice a české permissions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QMessageBox

from jll.gui.permission_list import (
    populate_permission_list,
    selected_permissions_from_list,
)
from jll.gui.setup_wizard import SetupWizard
from jll.identity_store import (
    IdentityStore,
    generate_user_id,
)
from jll.permission_catalog import (
    permission_title,
    permissions_in_group,
)
from jll.policy import Permission
from jll.setup_probe import DatabaseProbe, StationOption, derive_site_id
from jll.write_gates import DINER_WRITE_GATES


def fast_hasher():
    from argon2 import PasswordHasher, Type

    return PasswordHasher(
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )


def test_derive_site_id_is_stable_and_safe() -> None:
    assert derive_site_id("Scio Kuchyně") == "SCIO-KUCHYN"
    assert derive_site_id("!!!") == "LAB"
    assert len(derive_site_id("A" * 40)) == 20


def test_generate_user_id_is_unique_and_not_from_name() -> None:
    first = generate_user_id()
    second = generate_user_id(existing={first})
    assert first.startswith("usr_")
    assert second != first
    assert first != "vedouci"
    assert " " not in first


def test_permission_catalog_has_czech_labels_not_raw_values() -> None:
    titles = [permission_title(item) for item in Permission]
    assert "Zobrazit strávníky" in titles
    assert all("." not in permission_title(item) for item in Permission)
    assert permissions_in_group("STRÁVNÍCI")
    assert permissions_in_group("ČIPY")


def test_selected_permissions_reconstructs_enum_from_qt_string(
    qtbot: Any,
) -> None:
    widget = QListWidget()
    qtbot.addWidget(widget)
    populate_permission_list(widget, include_admin=False)
    for index in range(widget.count()):
        item = widget.item(index)
        raw = item.data(Qt.UserRole)
        if raw is None:
            continue
        assert isinstance(raw, str)
        if raw == Permission.DINERS_VIEW.value:
            item.setCheckState(Qt.Checked)
        else:
            item.setCheckState(Qt.Unchecked)
    selected = selected_permissions_from_list(widget)
    assert selected == frozenset({Permission.DINERS_VIEW})
    assert all(isinstance(item, Permission) for item in selected)


def test_setup_hides_technical_identity_fields(qtbot: Any, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel

    wizard = SetupWizard(tmp_path / "lab.json", tmp_path / "users.json")
    qtbot.addWidget(wizard)
    assert not hasattr(wizard, "admin_id")
    assert not hasattr(wizard, "user_id")
    joined = " ".join(label.text() for label in wizard.findChildren(QLabel))
    assert "User ID" not in joined
    assert "Site ID:" not in joined
    assert "Instance ID" not in joined
    assert "Stanice" in joined
    assert "Kód uživatele" in joined
    assert "diners.view" not in joined
    assert "Zobrazit strávníky" in " ".join(
        wizard.permission_list.item(i).text()
        for i in range(wizard.permission_list.count())
    )


def test_setup_regular_user_permissions_survive_identity_store(
    tmp_path: Path,
    qtbot: Any,
) -> None:
    """Regression: Qt UserRole string nesmí spadnout na str.value."""

    wizard = SetupWizard(tmp_path / "lab.json", tmp_path / "users.json")
    qtbot.addWidget(wizard)
    wizard.database_probe = DatabaseProbe(
        system_identifier="1000000000000000001",
        categories=("KAT2",),
        subject_name="DEMO LAB",
        stations=(StationOption(1, "VEDOUCI"),),
    )
    wizard.site_name.setText("DEMO LAB")
    wizard._fill_stations(wizard.database_probe.stations)
    wizard._fill_categories(wizard.database_probe.categories)
    for index in range(wizard.categories.count()):
        wizard.categories.item(index).setCheckState(Qt.Checked)
    wizard.create_regular_user.setChecked(True)
    for index in range(wizard.permission_list.count()):
        item = wizard.permission_list.item(index)
        raw = item.data(Qt.UserRole)
        if raw in {
            Permission.DINERS_VIEW.value,
            Permission.ORDERS_VIEW.value,
            Permission.ORDERS_CHANGE.value,
        }:
            item.setCheckState(Qt.Checked)
        elif raw is not None:
            item.setCheckState(Qt.Unchecked)

    selected = wizard.selected_permissions()
    assert selected == frozenset(
        {
            Permission.DINERS_VIEW,
            Permission.ORDERS_VIEW,
            Permission.ORDERS_CHANGE,
        }
    )
    assert all(isinstance(item, Permission) for item in selected)

    IdentityStore(
        tmp_path / "users.json", password_hasher=fast_hasher()
    ).initialize(
        [
            (
                wizard._admin_user_id,
                "Vedoucí",
                "VED",
                "2468",
                frozenset(Permission),
            ),
            (
                wizard._regular_user_id,
                "Pokladna",
                "SUP",
                "1357",
                selected,
            ),
        ],
        actor="VEDOUCI:SETUP",
    )
    store = IdentityStore(tmp_path / "users.json", password_hasher=fast_hasher())
    user = store.authenticate(wizard._regular_user_id, "1357")
    assert Permission.DINERS_VIEW in user.permissions
    assert user.user_id.startswith("usr_")


def test_setup_builds_config_from_station_and_subject(tmp_path: Path, qtbot: Any) -> None:
    wizard = SetupWizard(tmp_path / "lab.json", tmp_path / "users.json")
    qtbot.addWidget(wizard)
    wizard.db_host.setText("127.0.0.1")
    wizard.db_port.setText("5433")
    wizard.db_name.setText("jll_test")
    wizard.db_user.setText("postgres")
    probe = DatabaseProbe(
        system_identifier="1000000000000000001",
        categories=("KAT2",),
        subject_name="Testovací provoz",
        stations=(StationOption(7, "VEDOUCI"),),
    )
    wizard.database_probe = probe
    wizard.site_name.setText("Testovací provoz")
    wizard._fill_stations(probe.stations)
    wizard._fill_categories(probe.categories)
    wizard.categories.item(0).setCheckState(Qt.Checked)
    config = wizard._build_config()
    assert config.site_name == "Testovací provoz"
    assert config.instance_id == "VEDOUCI"
    assert config.site_id == derive_site_id("Testovací provoz")


def test_write_gate_tooltip_is_user_facing() -> None:
    blocked = DINER_WRITE_GATES["category_change"]
    assert "bezpečnostně blokována" in blocked.tooltip
    assert "diners.edit" not in blocked.tooltip
    assert blocked.badge == "Dosud nepovoleno"
    proven = DINER_WRITE_GATES["edit_personal"]
    assert proven.enabled
    assert proven.badge is None


def test_unexpected_setup_error_is_not_raw_python(
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
    wizard = SetupWizard(tmp_path / "lab.json", tmp_path / "users.json")
    qtbot.addWidget(wizard)

    def boom() -> None:
        raise RuntimeError("boom .value")

    monkeypatch.setattr(wizard, "_complete_setup", boom)
    # Přímé volání větve PAGE_SUMMARY bez navigace wizardem.
    monkeypatch.setattr(wizard, "currentId", lambda: SetupWizard.PAGE_SUMMARY)
    assert not wizard.validateCurrentPage()
    assert warnings
    assert "boom" not in warnings[-1]
    assert "diagnostického logu" in warnings[-1]
