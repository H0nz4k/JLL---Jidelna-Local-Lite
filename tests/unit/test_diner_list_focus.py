"""Unit tests: diner list keyboard focus (search ↔ rows)."""

from __future__ import annotations

from jll.flet_ui.screens.diners import _SEARCH_FOCUS, next_list_focus


def test_empty_search_stays_in_search_until_arrow_down() -> None:
    assert next_list_focus(_SEARCH_FOCUS, 1, 5) == 0
    assert next_list_focus(_SEARCH_FOCUS, -1, 5) == _SEARCH_FOCUS


def test_arrow_up_from_first_returns_to_search() -> None:
    assert next_list_focus(0, -1, 5) == _SEARCH_FOCUS


def test_arrow_clamps_at_last_row() -> None:
    assert next_list_focus(4, 1, 5) == 4
    assert next_list_focus(3, 1, 5) == 4


def test_empty_list_stays_in_search() -> None:
    assert next_list_focus(0, 1, 0) == _SEARCH_FOCUS
    assert next_list_focus(_SEARCH_FOCUS, 1, 0) == _SEARCH_FOCUS


def test_home_celkem_row_uses_expand_for_right_align() -> None:
    from pathlib import Path

    text = Path("src/jll/flet_ui/components/home_overview.py").read_text(
        encoding="utf-8"
    )
    assert 'theme.text("Celkem", theme.TextRole.ACTION, expand=True)' in text
    assert "portions_cs(overview.total_portions)" in text
