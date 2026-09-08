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


def test_display_chip_code_prefers_assigned_cipy_over_empty_legacy() -> None:
    from types import SimpleNamespace

    from jll.flet_ui.screens.diners import DinersScreen
    from jll.read_models import DinerChip

    diner = SimpleNamespace(
        chip_number=None,
        chips=(
            DinerChip(code="0000000018243940", status_code="P", status_label="Přidělen"),
        ),
    )
    assert DinersScreen._display_chip_code(None, diner) == "0000000018243940"

    empty = SimpleNamespace(chip_number=None, chips=())
    assert DinersScreen._display_chip_code(None, empty) is None

    legacy = SimpleNamespace(chip_number="LEGACY", chips=())
    assert DinersScreen._display_chip_code(None, legacy) == "LEGACY"


def test_month_grid_equal_day_columns_contract() -> None:
    """Day columns must not size to cell glyphs (S wider than *)."""

    from pathlib import Path

    text = Path("src/jll/flet_ui/screens/diners.py").read_text(encoding="utf-8")
    assert "horizontal_alignment=ft.CrossAxisAlignment.STRETCH" in text
    assert "expand=1" in text
    assert "clip_behavior=ft.ClipBehavior.HARD_EDGE" in text
    # Grid Rows must not expand vertically inside scroll Column (grey block bug).
    assert "ft.Row(header_cells, spacing=1, expand=True)" not in text
    assert "ft.Row(cells, spacing=1, expand=True)" not in text
    # detail_host must not Align-loose the width again
    assert "alignment=ft.alignment.top_left" not in text.split("detail_host")[1].split("if not self.vm.can_view")[0]


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
