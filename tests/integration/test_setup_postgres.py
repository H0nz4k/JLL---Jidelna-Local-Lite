from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from jll.config import load_lab_config
from jll.gui.app import build_window
from jll.gui.setup_wizard import SetupWizard
from jll.identity_store import IdentityStore
from jll.policy import Permission
from jll.setup_probe import derive_site_id

pytestmark = pytest.mark.integration


def test_setup_wizard_persists_verified_lab_and_hashed_admin(
    lab_database,
    tmp_path,
    qtbot: Any,
) -> None:
    config_path = tmp_path / "lab.json"
    identity_path = tmp_path / "users.json"
    wizard = SetupWizard(config_path, identity_path)
    qtbot.addWidget(wizard)
    wizard.db_host.setText(lab_database.host)
    wizard.db_port.setText(str(lab_database.port))
    wizard.db_name.setText(lab_database.name)
    wizard.db_user.setText(lab_database.user)

    probe = wizard._probe_database(
        (
            lab_database.host,
            str(lab_database.port),
            lab_database.name,
            lab_database.user,
            "",
        )
    )
    assert probe.system_identifier == lab_database.system_identifier
    assert probe.stations, "LAB DB musí obsahovat alespoň jednu stanici"
    wizard.database_probe = probe
    if probe.subject_name:
        wizard.site_name.setText(probe.subject_name)
    else:
        wizard.site_name.setText("Integration LAB")
        wizard.subject_override.setChecked(True)
    wizard._fill_stations(probe.stations)
    wizard._fill_categories(probe.categories)
    wizard.categories.clear()
    first_category = QListWidgetItem(probe.categories[0])
    first_category.setFlags(first_category.flags() | Qt.ItemIsUserCheckable)
    first_category.setCheckState(Qt.Checked)
    wizard.categories.addItem(first_category)
    wizard.admin_name.setText("Integration Admin")
    wizard.admin_short_code.setText("ADM")
    wizard.admin_pin.setText("2468")
    wizard.admin_pin_confirm.setText("2468")

    wizard._complete_setup()

    config = load_lab_config(config_path)
    assert config.database == lab_database.name
    assert config.allowed_categories == frozenset({probe.categories[0]})
    assert config.instance_id == wizard.selected_station()
    assert config.site_name == wizard.site_name.text().strip()
    assert config.site_id == derive_site_id(config.site_name)
    store = IdentityStore(identity_path)
    admin = store.authenticate(wizard._admin_user_id, "2468")
    assert Permission.ADMIN_USERS in admin.permissions
    assert admin.user_id.startswith("usr_")
    assert "2468" not in identity_path.read_text(encoding="utf-8")
    if probe.subject_name:
        assert config.site_name == probe.subject_name

    window = build_window(config_path, identity_path, wizard._admin_user_id)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.search_edit.isEnabled(), timeout=5_000)
    qtbot.waitUntil(lambda: window.results.rowCount() > 0, timeout=5_000)
    assert "Integration Admin" in window.user_label.text()
    assert window.admin_button.isEnabled()
    assert "bezpečnostně blokována" not in window.edit_diner_button.toolTip()
    assert "dostupná" in window.edit_diner_button.toolTip()
    window.close()
    window.connection_pool.close()
