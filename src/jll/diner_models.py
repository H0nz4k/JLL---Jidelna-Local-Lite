"""Command / result modely pro diner a chip writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping


# Explicitní whitelist personal edit (ne kategorie / finance / čip / stav).
PERSONAL_EDIT_FIELDS: frozenset[str] = frozenset(
    {
        "jmeno",
        "trida",
        "ulice",
        "psc",
        "mesto",
        "poznamka",
        "poznamkaam",
        "poznamkabm",
        "email",
        "vzkaz",
        "stredisko",
        "datumnarozeni",
    }
)

FORBIDDEN_PERSONAL_EDIT_FIELDS: frozenset[str] = frozenset(
    {
        "evidcislo",
        "kategorie",
        "stav",
        "deleted",
        "cip",
        "pin",
        "preplatekmm",
        "platittm",
        "platitpm",
        "platbatm",
        "platbabm",
        "preplatek",
        "zaloha",
        "uctpreplatek",
        "preplatek_sluzby",
        "zpusobplatby",
        "ucet",
        "varsymb",
        "banka",
        "hromadny",
    }
)


@dataclass(frozen=True, slots=True)
class CreateDinerCommand:
    jmeno: str
    kategorie: str
    trida: str = ""
    actor: str = ""
    client_version: str = ""


@dataclass(frozen=True, slots=True)
class EditDinerPersonalCommand:
    evidcislo: int
    expected_updated_dt: datetime | None
    fields: Mapping[str, str | date | None]
    actor: str = ""
    client_version: str = ""


@dataclass(frozen=True, slots=True)
class DinerWriteResult:
    evidcislo: int
    jmeno: str
    kategorie: str


@dataclass(frozen=True, slots=True)
class ChipHistoryEntry:
    code: str
    status_code: str | None
    status_label: str
    owner_evidcislo: int | None
    issued_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChipCommand:
    chip_code: str
    evidcislo: int
    actor: str = ""
    client_version: str = ""
    allow_reassign_lost: bool = False
