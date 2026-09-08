"""Structural tests for JLL 0.4.3 UI layout polish."""

from __future__ import annotations

import pytest

from jll.flet_ui import theme
from jll.flet_ui.screens.diners import DinersScreen


def test_admin_content_widths_matrix() -> None:
    assert theme.ADMIN_CONTENT_WIDTH["Kategorie"] <= 700
    assert theme.ADMIN_CONTENT_WIDTH["Vzhled"] <= 760
    assert theme.ADMIN_CONTENT_WIDTH["Čtečka"] <= 820
    assert theme.ADMIN_CONTENT_WIDTH["Uživatelé"] >= 900
    assert theme.ADMIN_CONTENT_WIDTH["Oprávnění"] >= 900
    assert theme.CONTENT_BORDER_WIDTH == 1
    assert theme.BLOCK_BORDER_WIDTH == 2


def test_text_scale_labels_are_percentages() -> None:
    labels = [scale.label_cs for scale in theme.TextScale]
    assert labels == ["100 %", "115 %", "130 %", "150 %"]
    theme.assert_four_roles()


def test_chip_actions_for_status_relevance() -> None:
    # DinersScreen methods are instance methods; call unbound via type.
    assert DinersScreen._chip_actions_for_status(None, None) == ["assign"]
    assert DinersScreen._chip_actions_for_status(None, "P") == ["return", "block", "lost"]
    assert DinersScreen._chip_actions_for_status(None, "B") == ["unblock"]
    assert DinersScreen._chip_actions_for_status(None, "Z") == ["assign"]
    assert DinersScreen._chip_actions_for_status(None, "V") == ["assign"]


def test_diner_source_has_no_main_chip_action_row() -> None:
    from pathlib import Path

    text = Path("src/jll/flet_ui/screens/diners.py").read_text(encoding="utf-8")
    # Main header must not permanently expose chip lifecycle TextButtons.
    assert 'ft.TextButton(\n                    "Přidělit"' not in text
    assert 'ft.TextButton(\n                    "Ztracený"' not in text
    assert "_chip_actions_for_status" in text
    assert 'chip_bit = f"Čip' in text or "Bez čipu" in text


def test_default_app_typography_matches_0_5_1_effective() -> None:
    from pathlib import Path

    from jll.flet_ui.state import AppState
    from jll.typography_settings import DEFAULT_TYPOGRAPHY

    state = AppState(config_path=Path("x"), identity_path=Path("y"))
    assert state.typography == DEFAULT_TYPOGRAPHY
    assert state.typography.body.size == pytest.approx(19.5)


def test_appearance_help_hides_internal_roles() -> None:
    from pathlib import Path

    text = Path("src/jll/flet_ui/screens/admin.py").read_text(encoding="utf-8")
    assert "Role: PRIMARY" not in text
    assert "Upravte čtyři styly používané v celé aplikaci." in text
    assert "ROLE_LABELS_CS" in text
    assert "Aktuální vzhled" in text
    assert "Po uložení:" in text
    assert "_content_card" in text
    assert "_rebuild_nav" in text
    assert "on_typography_save" in text
    assert 'ft.Radio(' not in text.split("def _render_appearance")[1].split("def ")[0]
