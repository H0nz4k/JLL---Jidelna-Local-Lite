from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .orders.errors import ErrorCode
from .orders.models import OrderAction


@dataclass(frozen=True, slots=True)
class DinerSummary:
    evidcislo: int
    name: str
    category: str
    class_name: str


@dataclass(frozen=True, slots=True)
class DinerChip:
    code: str
    status_code: str | None
    status_label: str


@dataclass(frozen=True, slots=True)
class DinerDetail(DinerSummary):
    available_credit: Decimal
    chip_number: str | None = None
    chips: tuple[DinerChip, ...] = ()


@dataclass(frozen=True, slots=True)
class MenuOption:
    menu: int
    dish_name: str
    price: Decimal
    published: bool = True


@dataclass(frozen=True, slots=True)
class MenuCapability:
    """Povolená čísla menu jednoho typu stravy podle `public.sazby`."""

    meal_type: str
    allowed_menus: tuple[int, ...]

    @property
    def allowed_menu_count(self) -> int:
        return len(self.allowed_menus)


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    action: OrderAction
    allowed: bool
    error_code: ErrorCode | None = None


@dataclass(frozen=True, slots=True)
class MealDay:
    code: str
    meal_type: str
    display_order: int
    current_state: str | None
    options: tuple[MenuOption, ...]
    availability: tuple[ActionAvailability, ...]
    exclusive_codes: frozenset[str]
    allowed_menus: tuple[int, ...] = ()
    month_states: tuple[str | None, ...] = ()
    cooking_days: frozenset[int] = frozenset()

    @property
    def allowed_menu_count(self) -> int:
        return len(self.allowed_menus)

    @property
    def ordered_menu(self) -> int | None:
        value = self.current_state
        if value is not None and len(value) == 1 and "1" <= value <= "9":
            return int(value)
        return None

    def can(self, action: OrderAction) -> bool:
        return next(
            (item.allowed for item in self.availability if item.action is action),
            False,
        )


@dataclass(frozen=True, slots=True)
class DinerDay:
    diner: DinerDetail
    target_date: date
    server_now: datetime
    meals: tuple[MealDay, ...]


@dataclass(frozen=True, slots=True)
class LabDiagnostics:
    database_name: str
    server_address: str
    server_port: int
    system_identifier: str
    business_timezone: str


@dataclass(frozen=True, slots=True)
class PickupStatusRow:
    meal_type: str
    menu: int
    ordered: int
    picked_up: int

    @property
    def remaining(self) -> int:
        return self.ordered - self.picked_up


@dataclass(frozen=True, slots=True)
class OrderReportRow:
    meal_type: str
    menu: int
    portions: int
    meal_name: str | None


@dataclass(frozen=True, slots=True)
class DinerReportRow:
    evidcislo: int
    name: str
    category: str
    class_name: str
