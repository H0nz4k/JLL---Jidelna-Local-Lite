"""Diners workspace viewmodel."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...application import OrderApplicationService
from ...policy import Permission
from ...read_models import DinerDay, DinerSummary
from ...read_service import OrderReadService
from ..state import AppState


@dataclass(frozen=True)
class MonthCell:
    day: int
    state: str | None
    is_cooking: bool
    is_selected: bool
    is_ordered: bool


@dataclass(frozen=True)
class MonthRow:
    meal_type: str
    display_order: int
    cells: tuple[MonthCell, ...]
    allowed_menus: tuple[int, ...]


class DinersViewModel:
    def __init__(self, state: AppState) -> None:
        self.state = state

    @property
    def read(self) -> OrderReadService:
        assert self.state.read_service is not None
        return self.state.read_service

    @property
    def orders(self) -> OrderApplicationService:
        assert self.state.application_service is not None
        return self.state.application_service

    def search(self, query: str) -> list[DinerSummary]:
        self.state.search_query = query
        text = query.strip()
        if len(text) < 2:
            self.state.diner_results = []
            return []
        results = list(self.read.search_diners(text))
        self.state.diner_results = results
        return results

    def select_diner(self, evidcislo: int) -> DinerDay:
        self.state.selected_evidcislo = evidcislo
        target = self.state.selected_day or self.read.server_today()
        self.state.selected_day = target
        return self.read.load_diner_day(evidcislo, target)

    def set_day(self, target: date) -> DinerDay | None:
        self.state.selected_day = target
        if self.state.selected_evidcislo is None:
            return None
        return self.read.load_diner_day(self.state.selected_evidcislo, target)

    def month_rows(self, diner_day: DinerDay) -> list[MonthRow]:
        days_in_month = calendar.monthrange(
            diner_day.target_date.year, diner_day.target_date.month
        )[1]
        selected_day = diner_day.target_date.day
        rows: list[MonthRow] = []
        for meal in diner_day.meals:
            cells = []
            for day in range(1, days_in_month + 1):
                state = (
                    meal.month_states[day - 1]
                    if day <= len(meal.month_states)
                    else None
                )
                cells.append(
                    MonthCell(
                        day=day,
                        state=state,
                        is_cooking=day in meal.cooking_days,
                        is_selected=day == selected_day,
                        is_ordered=bool(state) and state not in {"*", "-"},
                    )
                )
            rows.append(
                MonthRow(
                    meal_type=meal.meal_type,
                    display_order=meal.display_order,
                    cells=tuple(cells),
                    allowed_menus=meal.allowed_menus,
                )
            )
        return rows

    def format_credit(self, value: Decimal) -> str:
        quantized = f"{value:.2f}"
        whole, frac = quantized.split(".")
        return f"{whole},{frac} Kč"

    def can_view(self) -> bool:
        return self.state.has_perm(Permission.DINERS_VIEW)

    def can_change_orders(self) -> bool:
        return self.state.has_perm(Permission.ORDERS_CHANGE)

    def apply_menu(self, evidcislo: int, target: date, meal_type: str, menu: int):
        return self.orders.execute_selection(evidcislo, target, meal_type, menu)

    def unsubscribe(self, evidcislo: int, target: date, meal_type: str, ordered_menu: int):
        """Explicitní Odhlásit – klik na objednané menu sám o sobě nemaže."""

        return self.orders.execute_selection(
            evidcislo, target, meal_type, ordered_menu
        )
