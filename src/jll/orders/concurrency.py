"""Multi-writer coexistence: snapshot, version token, post-commit probe.

JLL nemůže zabránit neparticipujícímu writeru (JidelnaSQL / e-jídelníček),
který drží stale měsíční obraz, aby po JLL COMMITu zapsal. Cíl této vrstvy:

- PREVENTION: odmítnout zápis ze zastaralého UI snapshotu
- DETECTION: po COMMITu / settle poznat cizí přepsání
- SAFE RECOVERY: refresh autoritativního stavu, žádný retry war
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping, Sequence


DAY_COLUMNS: tuple[str, ...] = tuple(f"d{day:02d}" for day in range(1, 32))


class ProbeStatus(StrEnum):
    OK = "OK"  # intended state platí, markery beze změny
    EXTERNAL_OK = "EXTERNAL_OK"  # cizí změna, ale JLL záměr stále platí
    CONFLICT = "CONFLICT"  # JLL intended state byl přepsán
    CONSISTENCY = "CONSISTENCY"  # finance/vztahová nekonzistence


@dataclass(frozen=True, slots=True)
class PrihlasCapabilities:
    """Capability probe — bez migrací zákaznické DB."""

    has_seq: bool
    has_updated_dt: bool
    has_id: bool


@dataclass(frozen=True, slots=True)
class RowVersion:
    typsluzby: str
    poradiprihl: int
    rok: int
    mesic: int
    kategorie: str
    cena: str
    pocet: int
    day_states: tuple[str | None, ...]
    seq: int | None = None
    updated_dt: datetime | None = None
    row_id: int | None = None

    @property
    def material_fingerprint(self) -> str:
        payload = {
            "typsluzby": self.typsluzby,
            "poradiprihl": self.poradiprihl,
            "rok": self.rok,
            "mesic": self.mesic,
            "kategorie": self.kategorie,
            "cena": self.cena,
            "pocet": self.pocet,
            "days": list(self.day_states),
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OrderVersionToken:
    evidcislo: int
    year: int
    month: int
    capabilities: PrihlasCapabilities
    rows: tuple[RowVersion, ...]

    def fingerprint(self) -> str:
        parts = [
            f"{row.typsluzby}:{row.poradiprihl}:{row.seq}:{_iso(row.updated_dt)}:{row.material_fingerprint}"
            for row in sorted(self.rows, key=lambda item: item.typsluzby)
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def by_type(self) -> dict[str, RowVersion]:
        return {row.typsluzby: row for row in self.rows}


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """Stav, který uživatel skutečně viděl před klikem."""

    evidcislo: int
    datum: date
    version: OrderVersionToken
    focus_typstravy: str
    focus_day_state: str | None


@dataclass(frozen=True, slots=True)
class IntendedDayState:
    typstravy: str
    day: int
    expected_state: str


@dataclass(frozen=True, slots=True)
class PostCommitProbe:
    status: ProbeStatus
    message: str
    before_fingerprint: str
    after_fingerprint: str
    intended: tuple[IntendedDayState, ...]
    violated: tuple[IntendedDayState, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderPostCommitExpectations:
    """Očekávání zachycená při JLL COMMITu pro settle bez UI business rules."""

    intended: tuple[IntendedDayState, ...]
    exclusive_peers: Mapping[str, frozenset[str]]
    financial_fingerprint: str
    finance_meal_types: tuple[str, ...]
    allowed_categories: frozenset[str]


def financial_snapshot_fingerprint(
    *,
    order_price: Decimal | Any,
    order_count: int,
    prescribed: Decimal | Any,
    penden_amount: Decimal | Any,
    penden_count: int,
    penden_by_type: Sequence[tuple[str, Decimal | Any, int]],
) -> str:
    """Stabilní fingerprint finančního stavu známého z OrderService."""

    def _dec(value: Decimal | Any) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        return str(value)

    payload = {
        "order_price": _dec(order_price),
        "order_count": int(order_count),
        "prescribed": _dec(prescribed),
        "penden_amount": _dec(penden_amount),
        "penden_count": int(penden_count),
        "penden_by_type": [
            [str(typ), _dec(amount), int(count)]
            for typ, amount, count in penden_by_type
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_exclusive_peers(
    target_kod: str,
    vyloucene_codes: set[str] | frozenset[str],
) -> dict[str, frozenset[str]]:
    """Mapa vyloučených peerů z applicable vyloucenos cílového typu."""

    codes = {code for code in vyloucene_codes if code}
    if not codes:
        return {}
    group = frozenset({target_kod} | codes)
    return {code: frozenset(group - {code}) for code in group}


def _iso(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else ""


def decimal_as_text(value: Decimal | Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def row_version_from_mapping(
    row: Mapping[str, Any],
    *,
    capabilities: PrihlasCapabilities,
) -> RowVersion:
    days: list[str | None] = []
    for column in DAY_COLUMNS:
        raw = row.get(column)
        if raw is None:
            days.append(None)
        else:
            text = str(raw).strip()
            days.append(text or None)
    seq = None
    if capabilities.has_seq and row.get("seq") is not None:
        seq = int(row["seq"])
    updated = None
    if capabilities.has_updated_dt and row.get("updated_dt") is not None:
        updated = row["updated_dt"]
        if not isinstance(updated, datetime):
            updated = None
    row_id = None
    if capabilities.has_id and row.get("id") is not None:
        row_id = int(row["id"])
    return RowVersion(
        typsluzby=str(row["typsluzby"]).strip(),
        poradiprihl=int(row["poradiprihl"]),
        rok=int(row["rok"]),
        mesic=int(row["mesic"]),
        kategorie=str(row.get("kategorie") or "").strip(),
        cena=decimal_as_text(row["cena"]),
        pocet=int(row["pocet"]),
        day_states=tuple(days),
        seq=seq,
        updated_dt=updated,
        row_id=row_id,
    )


def build_version_token(
    *,
    evidcislo: int,
    year: int,
    month: int,
    capabilities: PrihlasCapabilities,
    rows: Sequence[Mapping[str, Any]],
) -> OrderVersionToken:
    versions = tuple(
        sorted(
            (
                row_version_from_mapping(row, capabilities=capabilities)
                for row in rows
            ),
            key=lambda item: item.typsluzby,
        )
    )
    return OrderVersionToken(
        evidcislo=evidcislo,
        year=year,
        month=month,
        capabilities=capabilities,
        rows=versions,
    )


def versions_match(expected: OrderVersionToken, actual: OrderVersionToken) -> bool:
    if (
        expected.evidcislo != actual.evidcislo
        or expected.year != actual.year
        or expected.month != actual.month
    ):
        return False
    left = expected.by_type()
    right = actual.by_type()
    # Extra rows v actual (např. related typy pod lockem) nejsou stale UI.
    for key, exp in left.items():
        got = right.get(key)
        if got is None:
            return False
        if exp.poradiprihl != got.poradiprihl:
            return False
        if exp.material_fingerprint != got.material_fingerprint:
            return False
        if expected.capabilities.has_seq and actual.capabilities.has_seq:
            if exp.seq != got.seq:
                return False
        elif (
            expected.capabilities.has_updated_dt
            and actual.capabilities.has_updated_dt
            and exp.updated_dt != got.updated_dt
        ):
            return False
    return True


def evaluate_post_commit(
    *,
    before: OrderVersionToken,
    after: OrderVersionToken,
    intended: Sequence[IntendedDayState],
    exclusive_peers: Mapping[str, frozenset[str]] | None = None,
    finance_consistent: bool | None = None,
    committed_finance_fingerprint: str | None = None,
    current_finance_fingerprint: str | None = None,
) -> PostCommitProbe:
    after_map = after.by_type()
    violated: list[IntendedDayState] = []
    for item in intended:
        row = after_map.get(item.typstravy)
        if row is None or item.day < 1 or item.day > 31:
            violated.append(item)
            continue
        actual_state = row.day_states[item.day - 1]
        if actual_state != item.expected_state:
            violated.append(item)

    markers_changed = before.fingerprint() != after.fingerprint()
    finance_known = (
        committed_finance_fingerprint is not None
        and current_finance_fingerprint is not None
    )
    finance_stuck = (
        finance_known
        and committed_finance_fingerprint == current_finance_fingerprint
    )
    finance_drifted = (
        finance_known
        and committed_finance_fingerprint != current_finance_fingerprint
    )

    if violated:
        # Automatický finance oracle: order přepsán, finance zůstaly u JLL commit.
        if finance_stuck:
            return PostCommitProbe(
                status=ProbeStatus.CONSISTENCY,
                message=(
                    "Po uložení byla zjištěna nekonzistence objednávky "
                    "(order/finance nekonzistence po cizím zápisu). "
                    "Zobrazuji aktuální stav databáze. Automatická oprava se neprovádí."
                ),
                before_fingerprint=before.fingerprint(),
                after_fingerprint=after.fingerprint(),
                intended=tuple(intended),
                violated=tuple(violated),
            )
        return PostCommitProbe(
            status=ProbeStatus.CONFLICT,
            message=(
                "Objednávka byla během ukládání změněna v jiné aplikaci. "
                "Zobrazuji aktuální stav databáze."
            ),
            before_fingerprint=before.fingerprint(),
            after_fingerprint=after.fingerprint(),
            intended=tuple(intended),
            violated=tuple(violated),
        )

    consistency_reasons: list[str] = []
    if exclusive_peers:
        for item in intended:
            day_idx = item.day - 1
            ordered_types = {
                typ: row
                for typ, row in after_map.items()
                if 0 <= day_idx < len(row.day_states)
                and row.day_states[day_idx] is not None
                and str(row.day_states[day_idx]).isdigit()
            }
            for typ in ordered_types:
                peers = exclusive_peers.get(typ, frozenset())
                clash = sorted(peer for peer in peers if peer in ordered_types)
                if clash:
                    consistency_reasons.append(
                        f"vyloucenos konflikt: {typ} vs {', '.join(clash)}"
                    )
                    break
            if consistency_reasons:
                break
    if finance_consistent is False:
        consistency_reasons.append("order/finance nekonzistence po cizím zápisu")
    elif finance_drifted:
        consistency_reasons.append("finance drift při platném intended stavu")

    if consistency_reasons:
        return PostCommitProbe(
            status=ProbeStatus.CONSISTENCY,
            message=(
                "Po uložení byla zjištěna nekonzistence objednávky "
                f"({'; '.join(consistency_reasons)}). "
                "Zobrazuji aktuální stav databáze. Automatická oprava se neprovádí."
            ),
            before_fingerprint=before.fingerprint(),
            after_fingerprint=after.fingerprint(),
            intended=tuple(intended),
        )

    if markers_changed:
        return PostCommitProbe(
            status=ProbeStatus.EXTERNAL_OK,
            message="Stav aktualizován z databáze.",
            before_fingerprint=before.fingerprint(),
            after_fingerprint=after.fingerprint(),
            intended=tuple(intended),
        )
    return PostCommitProbe(
        status=ProbeStatus.OK,
        message="",
        before_fingerprint=before.fingerprint(),
        after_fingerprint=after.fingerprint(),
        intended=tuple(intended),
    )
