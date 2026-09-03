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
    wizard.database_probe = probe
    wizard.categories.clear()
    first_category = QListWidgetItem(probe.categories[0])
    first_category.setFlags(first_category.flags() | Qt.ItemIsUserCheckable)
    first_category.setCheckState(Qt.Checked)
    wizard.categories.addItem(first_category)
    wizard.site_name.setText("Integration LAB")
    wizard.site_id.setText("INT")
    wizard.instance_id.setText("INT-LAB01")
    wizard.admin_name.setText("Integration Admin")
    wizard.admin_id.setText("admin")
    wizard.admin_short_code.setText("ADM")
    wizard.admin_pin.setText("2468")
    wizard.admin_pin_confirm.setText("2468")

    wizard._complete_setup()

    config = load_lab_config(config_path)
    assert config.database == lab_database.name
    assert config.allowed_categories == frozenset({probe.categories[0]})
    store = IdentityStore(identity_path)
    admin = store.authenticate("admin", "2468")
    assert Permission.ADMIN_USERS in admin.permissions
    assert "2468" not in identity_path.read_text(encoding="utf-8")

    window = build_window(config_path, identity_path, "admin")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.search_edit.isEnabled(), timeout=5_000)
    qtbot.waitUntil(lambda: window.results.rowCount() > 0, timeout=5_000)
    assert "Integration Admin" in window.user_label.text()
    assert window.admin_button.isEnabled()
    window.close()
    window.connection_pool.close()
