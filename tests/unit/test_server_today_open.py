"""Otevření strávníka používá serverové dnes, ne účetní měsíc."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from jll.flet_ui.state import AppState
from jll.flet_ui.viewmodels.diners import DinersViewModel
from jll.read_models import BusinessCalendar


def test_diner_open_uses_server_today_not_accounting_month() -> None:
    """Regrese: selected_day = calendar.today / server_today, ne period_month."""

    state = AppState(config_path=Path("cfg.json"), identity_path=Path("id.json"))
    # Účetní období (denobjednavky) je srpen, serverové dnes je září.
    state.business_calendar = BusinessCalendar(
        today=date(2026, 9, 7),
        period_month=8,
        period_year=2026,
    )
    read = MagicMock()
    read.server_today.return_value = date(2026, 9, 7)
    read.load_diner_day.return_value = MagicMock()
    state.read_service = read

    vm = DinersViewModel(state)
    assert vm.default_target() == date(2026, 9, 7)
    assert vm.today_for_open() == date(2026, 9, 7)
    assert state.business_calendar.period_month == 8

    vm.select_diner(42)
    assert state.selected_day == date(2026, 9, 7)
    read.load_diner_day.assert_called_once_with(42, date(2026, 9, 7))
    assert state.selected_day != date(2026, 8, 1)
    assert state.selected_day.month != state.business_calendar.period_month
