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
    updated_dt: datetime | None = None
    ulice: str = ""
    psc: str = ""
    mesto: str = ""
    poznamka: str = ""
    email: str = ""
    stredisko: str = ""
    vzkaz: str = ""
    poznamkaam: str = ""
    poznamkabm: str = ""
    datumnarozeni: date | None = None


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
    month_pickups: tuple[bool, ...] = ()
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

    def picked_up_on(self, day: int) -> bool:
        if day < 1 or day > len(self.month_pickups):
            return False
        return bool(self.month_pickups[day - 1])

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
class BusinessCalendar:
    """Kalendář jídelny.

    - `today` = datum ze serveru (`clock_timestamp` v business timezone)
    - `period_month` / `period_year` = `TentoMesic` / `TentoRok` z `parametry`
    """

    today: date
    period_month: int
    period_year: int

    _WEEKDAYS = (
        "pondělí",
        "úterý",
        "středa",
        "čtvrtek",
        "pátek",
        "sobota",
        "neděle",
    )
    _MONTHS = (
        "",
        "leden",
        "únor",
        "březen",
        "duben",
        "květen",
        "červen",
        "červenec",
        "srpen",
        "září",
        "říjen",
        "listopad",
        "prosinec",
    )

    @property
    def period_label(self) -> str:
        name = (
            self._MONTHS[self.period_month]
            if 1 <= self.period_month <= 12
            else str(self.period_month)
        )
        return f"AM {name} {self.period_year}"

    @property
    def today_label(self) -> str:
        weekday = self._WEEKDAYS[self.today.weekday()]
        return f"{weekday} {self.today.strftime('%d.%m.%Y')}"

    @property
    def header_label(self) -> str:
        """Formát hlavičky: `neděle 06.09.2026 - - AM září 2026`."""

        return f"{self.today_label} - - {self.period_label}"

    @classmethod
    def month_name_cs(cls, month: int, *, title: bool = False) -> str:
        name = cls._MONTHS[month] if 1 <= month <= 12 else str(month)
        if title and name:
            return name[:1].upper() + name[1:]
        return name

    @property
    def next_period_month(self) -> int:
        return 1 if self.period_month == 12 else self.period_month + 1

    @property
    def next_period_year(self) -> int:
        return self.period_year + 1 if self.period_month == 12 else self.period_year

    def date_in_period(self, *, future: bool, day: int | None = None) -> date:
        """Vrátí den v aktuálním nebo budoucím účetním měsíci."""

        import calendar as cal

        year = self.next_period_year if future else self.period_year
        month = self.next_period_month if future else self.period_month
        last = cal.monthrange(year, month)[1]
        if day is None:
            day = self.today.day if not future else 1
        return date(year, month, min(max(1, day), last))


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
class HomeMealSummary:
    """Jeden řádek HOME: typ stravy × menu × objednané porce."""

    meal_type: str
    menu: int
    portions: int
    meal_name: str | None
    menu_published: bool

    @property
    def title_line(self) -> str:
        return f"{self.meal_type} · Menu {self.menu}"

    @property
    def name_line(self) -> str:
        if self.meal_name:
            return self.meal_name
        return "Jídelníček není zveřejněn"


@dataclass(frozen=True, slots=True)
class HomeTodayOverview:
    """Read model HOME / Dnešní objednávky (bez Flet závislostí)."""

    workplace_name: str
    organization_name: str
    target_date: date
    is_cooking_day: bool
    next_cooking_day: date | None
    total_portions: int
    meals: tuple[HomeMealSummary, ...]
    load_error: str | None = None

    @property
    def date_label(self) -> str:
        weekday = BusinessCalendar._WEEKDAYS[self.target_date.weekday()]
        month = BusinessCalendar._MONTHS[self.target_date.month]
        titled = weekday[:1].upper() + weekday[1:]
        return f"{titled} {self.target_date.day}. {month} {self.target_date.year}"


def portions_cs(count: int) -> str:
    """České skloňování porce/porce/porcí."""

    n = abs(int(count))
    if n == 1:
        return "1 porce"
    if 2 <= n <= 4:
        return f"{n} porce"
    return f"{n} porcí"


def workplace_display_name(instance_id: str) -> str:
    """Lidský název stanice z `LabConfig.instance_id` (např. JAROV → Jarov)."""

    raw = (instance_id or "").strip()
    if not raw:
        return "—"
    if raw.isupper() and all(ch.isalnum() or ch in "-_" for ch in raw):
        return raw[:1] + raw[1:].lower()
    return raw


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


def chip_status_label(value: object) -> str:
    code = str(value).strip() if value is not None else ""
    if code == "P":
        return "Přidělen"
    if code == "V":
        return "Volný"
    if code == "Z":
        return "Ztracen"
    if code == "B":
        return "Blokován"
    if not code:
        return "Stav neuveden"
    return f"Stav {code} (význam nedoložen)"
