"""Odebraná strava = žlutá buňka v měsíční mřížce."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from jll.flet_ui.viewmodels.diners import DinersViewModel
from jll.flet_ui.state import AppState
from jll.read_models import DinerDay, DinerDetail, MealDay


def _meal(*, states: tuple[str | None, ...], pickups: tuple[bool, ...]) -> MealDay:
    return MealDay(
        code="OB",
        meal_type="Oběd-B",
        display_order=1,
        current_state=states[7] if len(states) >= 8 else None,
        options=(),
        availability=(),
        exclusive_codes=frozenset(),
        allowed_menus=(1,),
        month_states=states,
        month_pickups=pickups,
        cooking_days=frozenset(range(1, 31)),
    )


def test_month_rows_mark_picked_up_cells() -> None:
    states = tuple("N" if day != 8 else "1" for day in range(1, 32))
    pickups = tuple(day == 8 for day in range(1, 32))
    diner = DinerDetail(
        evidcislo=1,
        name="Test",
        category="1JARO",
        class_name="1JARO",
        available_credit=Decimal("0"),
        chip_number=None,
        chips=(),
    )
    day = DinerDay(
        diner=diner,
        target_date=date(2026, 9, 8),
        server_now=datetime(2026, 9, 8, 12, 0, tzinfo=ZoneInfo("Europe/Prague")),
        meals=(_meal(states=states, pickups=pickups),),
    )
    vm = DinersViewModel(
        AppState(config_path=Path("config/lab.json"), identity_path=Path("identity"))
    )
    rows = vm.month_rows(day)
    cell8 = rows[0].cells[7]
    assert cell8.is_ordered is True
    assert cell8.is_picked_up is True
    cell9 = rows[0].cells[8]
    assert cell9.is_picked_up is False


def test_meal_day_picked_up_on() -> None:
    meal = _meal(
        states=tuple("1" if day == 8 else "N" for day in range(1, 32)),
        pickups=tuple(day == 8 for day in range(1, 32)),
    )
    assert meal.picked_up_on(8) is True
    assert meal.picked_up_on(7) is False
    assert meal.picked_up_on(0) is False
