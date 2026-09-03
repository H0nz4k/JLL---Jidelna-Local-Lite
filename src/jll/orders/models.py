from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class OrderAction(StrEnum):
    MENU_ADD = "menu_add"
    MENU_DELETE = "menu_delete"
    MENU_CHANGE = "menu_change"


class TransitionReason(StrEnum):
    PRIMARY = "primary"
    SPOLECNES = "spolecnes"
    VYLOUCENOS = "vyloucenos"


@dataclass(frozen=True, slots=True)
class OrderCommand:
    action: OrderAction
    evidcislo: int
    datum: date
    typstravy: str
    menu: int
    allowed_categories: frozenset[str]
    actor: str
    client_version: str

    def __post_init__(self) -> None:
        try:
            action = (
                self.action
                if isinstance(self.action, OrderAction)
                else OrderAction(self.action)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Neplatná objednávková akce.") from exc
        object.__setattr__(self, "action", action)

        if isinstance(self.evidcislo, bool) or not isinstance(self.evidcislo, int):
            raise ValueError("evidcislo musí být celé číslo.")
        if not -(2**31) <= self.evidcislo < 2**31:
            raise ValueError("evidcislo je mimo PostgreSQL integer.")
        if not isinstance(self.datum, date) or isinstance(self.datum, datetime):
            raise ValueError("datum musí být date bez časové složky.")
        if isinstance(self.menu, bool) or not isinstance(self.menu, int):
            raise ValueError("menu musí být celé číslo.")
        if not 1 <= self.menu <= 9:
            raise ValueError("menu musí být v rozsahu 1..9.")

        typstravy = self.typstravy.strip()
        actor = self.actor.strip()
        version = self.client_version.strip()
        categories = frozenset(
            value.strip()
            for value in self.allowed_categories
            if isinstance(value, str) and value.strip()
        )
        if not typstravy or len(typstravy) > 20:
            raise ValueError("typstravy musí mít 1 až 20 znaků.")
        if not actor or len(actor) > 25:
            raise ValueError("actor musí mít 1 až 25 znaků.")
        if not version or len(version) > 10:
            raise ValueError("client_version musí mít 1 až 10 znaků.")
        if not categories:
            raise ValueError("allowed_categories nesmí být prázdné.")
        if any(len(value) > 5 for value in categories):
            raise ValueError("Kategorie musí odpovídat varchar(5).")
        if len(categories) != len(self.allowed_categories):
            raise ValueError("allowed_categories obsahuje neplatné hodnoty.")

        object.__setattr__(self, "typstravy", typstravy)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "client_version", version)
        object.__setattr__(self, "allowed_categories", categories)


@dataclass(frozen=True, slots=True)
class OrderServiceSettings:
    environment: str
    db_host: str
    db_name: str
    expected_system_identifier: str
    business_timezone: str
    strict_config_lock: bool = True
    lock_timeout_ms: int = 5_000
    statement_timeout_ms: int = 30_000
    max_retries: int = 2

    def __post_init__(self) -> None:
        if (
            not self.expected_system_identifier
            or not self.expected_system_identifier.isdigit()
        ):
            raise ValueError("expected_system_identifier musí být číselný.")
        if not self.business_timezone.strip():
            raise ValueError("business_timezone nesmí být prázdná.")
        if self.lock_timeout_ms <= 0 or self.statement_timeout_ms <= 0:
            raise ValueError("Timeouty musí být kladné.")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries musí být v rozsahu 0..5.")


@dataclass(frozen=True, slots=True)
class Diner:
    evidcislo: int
    kategorie: str
    hromadny: bool
    preplatekmm: Any
    platittm: Any
    platitpm: Any
    platbatm: Any
    platbabm: Any


@dataclass(frozen=True, slots=True)
class MealType:
    typstravy: str
    kod: str
    prihlasdo: Any
    prihlasdnu: Any
    menudo: Any
    menudnu: Any
    odhlasdo: Any
    odhlasdnu: Any
    spolecnes: str | None
    vyloucenos: str | None


@dataclass(frozen=True, slots=True)
class OrderRow:
    stravnik: int
    typsluzby: str
    rok: int
    mesic: int
    poradiprihl: int
    state: str | None
    cena: Decimal
    pocet: int

    @property
    def pk(self) -> tuple[int, str, int, int, int]:
        return (
            self.stravnik,
            self.typsluzby,
            self.rok,
            self.mesic,
            self.poradiprihl,
        )


@dataclass(frozen=True, slots=True)
class Transition:
    typstravy: str
    before_state: str
    after_state: str
    before_price: Decimal
    after_price: Decimal
    reason: TransitionReason
    poradiprihl: int

    @property
    def financial_delta(self) -> Decimal:
        return self.after_price - self.before_price

    @property
    def count_delta(self) -> int:
        before = 1 if self.before_state.isdigit() else 0
        after = 1 if self.after_state.isdigit() else 0
        return after - before


@dataclass(frozen=True, slots=True)
class OrderPlan:
    transitions: tuple[Transition, ...]
    current_credit: Decimal
    minimum_balance: Decimal

    @property
    def planned_financial_delta(self) -> Decimal:
        return sum(
            (item.financial_delta for item in self.transitions),
            start=Decimal(0),
        )

    @property
    def projected_balance(self) -> Decimal:
        return self.current_credit - self.planned_financial_delta


@dataclass(frozen=True, slots=True)
class FinancialSnapshot:
    order_price: Decimal
    order_count: int
    prescribed: Decimal
    penden_amount: Decimal
    penden_count: int
    penden_by_type: tuple[tuple[str, Decimal, int], ...]


@dataclass(frozen=True, slots=True)
class OrderMetrics:
    advisory_lock_wait_ms: float = 0.0
    config_lock_wait_ms: float = 0.0
    transaction_ms: float = 0.0
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class OrderResult:
    success: bool
    action: OrderAction
    evidcislo: int
    datum: date
    committed_transitions: tuple[Transition, ...]
    committed_at: datetime
    metrics: OrderMetrics = field(default_factory=OrderMetrics)
