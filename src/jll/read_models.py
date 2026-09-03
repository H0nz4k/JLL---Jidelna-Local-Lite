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


CHIP_NOT_FOUND = "Čip nebyl nalezen."
CHIP_OWNER_UNAVAILABLE = "Čip nemá dostupného vlastníka."
CHIP_OUT_OF_SCOPE = "Čip není pro tuto provozovnu dostupný."


@dataclass(frozen=True, slots=True)
class ChipIdentification:
    """Výsledek scope-safe identifikace čipu.

    Pro vlastníka mimo `allowed_categories` se nikdy nevrací identita, pouze
    `owner_restricted`. Stav čipu se nedopočítává, přebírá se z `public.cipy`.
    """

    code: str
    exists: bool
    status_code: str | None = None
    status_label: str = "Stav neuveden"
    owner: DinerSummary | None = None
    owner_restricted: bool = False

    @property
    def opens_card(self) -> bool:
        return self.owner is not None

    @property
    def message(self) -> str:
        if not self.exists:
            return CHIP_NOT_FOUND
        if self.owner is not None:
            return f"Čip {self.code} — {self.status_label}"
        if self.owner_restricted:
            return CHIP_OUT_OF_SCOPE
        return CHIP_OWNER_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class DinerFinance:
    """Pouze doložené finanční hodnoty.

    `available_credit` je stejný výpočet, který používá objednávkový
    preflight; `minimum_balance` je doložený limit z `public.kategor`.
    Nedoložené sloupce se záměrně nezobrazují.
    """

    available_credit: Decimal
    minimum_balance: Decimal

    @property
    def headroom(self) -> Decimal:
        return self.available_credit - self.minimum_balance


@dataclass(frozen=True, slots=True)
class DinerProfile:
    """Read-only detail strávníka bez tajných a nedoložených hodnot."""

    evidcislo: int
    name: str
    category: str
    category_name: str | None
    category_norm: str | None
    class_name: str
    birth_date: date | None
    variable_symbol: str | None
    payment_method: str | None
    state_code: str | None
    state_label: str
    note: str | None
    finance: DinerFinance
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


MISSING_MEAL_NAME = "[název v jídelníčku nenalezen]"
MISSING_NORM = "[bez normy]"
DEFAULT_NORMS: tuple[str, ...] = ("A", "B", "C", "D")


@dataclass(frozen=True, slots=True)
class NamedOrderRow:
    """Jedna objednávka jednoho strávníka pro jeden typ stravy."""

    evidcislo: int
    name: str
    category: str
    category_name: str | None
    norm: str | None
    meal_type: str
    menu: int
    meal_name: str | None

    @property
    def category_label(self) -> str:
        return self.category_name or self.category

    @property
    def meal_label(self) -> str:
        return self.meal_name or MISSING_MEAL_NAME

    @property
    def norm_label(self) -> str:
        return self.norm or MISSING_NORM


@dataclass(frozen=True, slots=True)
class CategoryOrderSummary:
    category: str
    category_name: str | None
    norm: str | None
    orders: int

    @property
    def category_label(self) -> str:
        return self.category_name or self.category


@dataclass(frozen=True, slots=True)
class NormMenuSummary:
    meal_type: str
    norm: str | None
    menu: int
    portions: int

    @property
    def norm_label(self) -> str:
        return self.norm or MISSING_NORM


@dataclass(frozen=True, slots=True)
class DailyReport:
    """Kompletní denní sestava pro jeden den a jeden scope."""

    target_date: date
    subject_name: str | None
    menus: tuple[OrderReportRow, ...]
    categories: tuple[CategoryOrderSummary, ...]
    norms: tuple[NormMenuSummary, ...]
    diners: tuple[NamedOrderRow, ...]

    @property
    def total_portions(self) -> int:
        return sum(item.portions for item in self.menus)

    @property
    def total_orders(self) -> int:
        return len(self.diners)
