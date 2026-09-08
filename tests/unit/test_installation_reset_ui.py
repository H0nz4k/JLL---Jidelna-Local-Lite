"""Unit tests: app reset → first-run transition contracts."""

from __future__ import annotations

from pathlib import Path


def test_app_exposes_reset_and_enter_first_run() -> None:
    text = Path("src/jll/flet_ui/app.py").read_text(encoding="utf-8")
    assert "def reset_installation" in text
    assert "def enter_first_run" in text
    assert "def _quiesce_runtime" in text
    assert "SetupScreen" in text
    assert "DEFAULT_TYPOGRAPHY" in text
    assert "_reset_in_progress" in text


def test_admin_info_has_reset_action_and_reuses_setup() -> None:
    admin = Path("src/jll/flet_ui/screens/admin.py").read_text(encoding="utf-8")
    assert "Obnovit počáteční nastavení" in admin
    assert "Počáteční nastavení" in admin
    assert "on_installation_reset" in admin
    assert "Zobrazit changelog" in admin
    assert "_open_changelog_dialog" in admin
    assert "ResetWizard" not in admin
    assert "SetupScreen" not in admin  # setup remains in app.py only


def test_no_second_wizard_module() -> None:
    root = Path("src/jll/flet_ui/screens")
    names = {path.name for path in root.glob("*.py")}
    assert "setup.py" in names
    assert "reset_setup.py" not in names
    assert "reset_wizard.py" not in names
