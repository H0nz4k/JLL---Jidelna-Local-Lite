"""Diners workspace viewmodel."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...application import OrderApplicationService
from ...policy import Permission
from ...read_models import BusinessCalendar, DinerDay, DinerSummary
from ...read_service import OrderReadService
from ..state import AppState


@dataclass(frozen=True)
class MonthOption:
    year: int
    month: int
    label: str
    is_current: bool
    is_future: bool


@dataclass(frozen=True)
class MonthCell:
    day: int
    state: str | None
    is_cooking: bool
    is_selected: bool
    is_ordered: bool
    is_subscribed: bool

    @property
    def is_menu_number(self) -> bool:
        return bool(self.state) and len(self.state) == 1 and self.state.isdigit()


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

    def _calendar(self) -> BusinessCalendar | None:
        return self.state.business_calendar

    def default_target(self) -> date:
        cal = self._calendar()
        if cal is not None:
            return cal.today
        return self.read.server_today()

    def today_for_open(self) -> date:
        """Aktuální serverové „dnes“ (čerstvě ze DB, ne z denobjednavky)."""

        try:
            return self.read.server_today()
        except Exception:
            return self.default_target()

    def month_options(self) -> tuple[MonthOption, MonthOption]:
        cal = self._calendar()
        if cal is not None:
            current = MonthOption(
                year=cal.period_year,
                month=cal.period_month,
                label=BusinessCalendar.month_name_cs(cal.period_month, title=True),
                is_current=True,
                is_future=False,
            )
            future = MonthOption(
                year=cal.next_period_year,
                month=cal.next_period_month,
                label=BusinessCalendar.month_name_cs(cal.next_period_month, title=True),
                is_current=False,
                is_future=True,
            )
            return current, future
        today = self.default_target()
        if today.month == 12:
            next_year, next_month = today.year + 1, 1
        else:
            next_year, next_month = today.year, today.month + 1
        return (
            MonthOption(
                today.year,
                today.month,
                BusinessCalendar.month_name_cs(today.month, title=True),
                True,
                False,
            ),
            MonthOption(
                next_year,
                next_month,
                BusinessCalendar.month_name_cs(next_month, title=True),
                False,
                True,
            ),
        )

    def format_month_year(self, target: date) -> str:
        return (
            f"{BusinessCalendar.month_name_cs(target.month, title=True)} {target.year}"
        )

    def format_day_month(self, target: date) -> str:
        return (
            f"{target.day}. {BusinessCalendar.month_name_cs(target.month)}"
        )

    def list_initial(self) -> list[DinerSummary]:
        """Úvodní seznam bez filtru (scope + search_limit)."""

        results = list(self.read.list_diners())
        self.state.diner_results = results
        self.state.search_query = ""
        return results

    def search(self, query: str) -> list[DinerSummary]:
        self.state.search_query = query
        text = query.strip()
        if not text:
            return self.list_initial()
        if len(text) < 2:
            self.state.diner_results = []
            return []
        results = list(self.read.search_diners(text))
        self.state.diner_results = results
        return results

    def select_diner(self, evidcislo: int) -> DinerDay:
        self.state.selected_evidcislo = evidcislo
        # Při každém otevření strávníka (hledání / Enter / klik) vždy dnešek.
        target = self.today_for_open()
        self.state.selected_day = target
        return self.read.load_diner_day(evidcislo, target)

    def switch_month(self, *, future: bool) -> DinerDay | None:
        if self.state.selected_evidcislo is None:
            return None
        cal = self._calendar()
        current_day = self.state.selected_day.day if self.state.selected_day else None
        if cal is not None:
            target = cal.date_in_period(future=future, day=current_day)
        else:
            current, nxt = self.month_options()
            opt = nxt if future else current
            last = calendar.monthrange(opt.year, opt.month)[1]
            day = min(current_day or 1, last)
            target = date(opt.year, opt.month, day)
        return self.set_day(target)

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
                        is_ordered=bool(state)
                        and len(state) == 1
                        and state.isdigit(),
                        is_subscribed=state in {"S", "N"},
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
        return self.format_money(value)

    def format_money(self, value: Decimal) -> str:
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
