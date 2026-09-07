"""Modely plateb / peněžního deníku."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal


#: Historie „Platby“ na kartě strávníka — platby + zálohy/vratky čipu.
#: Rozpisy (`R`) a poplatky (`O`) sem nepatří. LAB typ `Z` se nevyskytuje.
PAYMENT_HISTORY_TYPES: frozenset[str] = frozenset({"P", "C"})

LEDGER_TYPE_LABELS: dict[str, str] = {
    "P": "Platba",
    "C": "Čip",
    "R": "Rozpis",
    "O": "Poplatek",
}


@dataclass(frozen=True, slots=True)
class PaymentLedgerEntry:
    id: int
    evidcislo: int
    booked_on: date
    booked_at: time | None
    amount: Decimal
    ledger_type: str
    ledger_type_label: str
    payment_method_code: str
    payment_method_label: str
    account: str
    service_type: str
    note: str
    period_month: int
    period_year: int
    category_snapshot: str
    class_snapshot: str


@dataclass(frozen=True, slots=True)
class PaymentHistoryPage:
    evidcislo: int
    items: tuple[PaymentLedgerEntry, ...]
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class ManualPaymentCommand:
    evidcislo: int
    amount: Decimal
    payment_method_code: str
    account: str
    service_type: str
    period_month: int
    note: str
    actor: str
    client_version: str


@dataclass(frozen=True, slots=True)
class PaymentMethodOption:
    code: str
    label: str


@dataclass(frozen=True, slots=True)
class AccountOption:
    code: str
    label: str


@dataclass(frozen=True, slots=True)
class PaymentPostResult:
    penden_id: int
    amount: Decimal
    ledger_type: str
    period_month: int
    period_year: int
