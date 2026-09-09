"""Unit tests: order multi-writer snapshot / probe helpers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from jll.orders.concurrency import (
    IntendedDayState,
    PrihlasCapabilities,
    ProbeStatus,
    RowVersion,
    build_version_token,
    evaluate_post_commit,
    versions_match,
)


CAPS = PrihlasCapabilities(has_seq=True, has_updated_dt=True, has_id=True)


def _row(
    typ: str,
    *,
    day15: str = "N",
    seq: int = 1,
    cena: str = "45.00",
) -> dict:
    days = {f"d{day:02d}": "N" for day in range(1, 32)}
    days["d15"] = day15
    return {
        "typsluzby": typ,
        "poradiprihl": 1,
        "rok": 2026,
        "mesic": 9,
        "kategorie": "KAT1",
        "cena": Decimal(cena),
        "pocet": 0 if day15 in {"N", "S"} else 1,
        "seq": seq,
        "updated_dt": datetime(2026, 9, 9, 12, 0, 0),
        "id": 10,
        **days,
    }


def test_fingerprint_changes_when_day_changes() -> None:
    a = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[_row("Oběd-A", day15="N")],
    )
    b = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[_row("Oběd-A", day15="1", seq=2)],
    )
    assert a.fingerprint() != b.fingerprint()
    assert not versions_match(a, b)


def test_versions_match_same_material_and_seq() -> None:
    rows = [_row("Oběd-A", day15="1", seq=7)]
    a = build_version_token(
        evidcislo=1, year=2026, month=9, capabilities=CAPS, rows=rows
    )
    b = build_version_token(
        evidcislo=1, year=2026, month=9, capabilities=CAPS, rows=rows
    )
    assert versions_match(a, b)


def test_post_commit_conflict_when_intended_lost() -> None:
    before = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[_row("Oběd-A", day15="1", seq=2)],
    )
    after = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[_row("Oběd-A", day15="N", seq=3)],
    )
    probe = evaluate_post_commit(
        before=before,
        after=after,
        intended=[IntendedDayState("Oběd-A", 15, "1")],
    )
    assert probe.status is ProbeStatus.CONFLICT
    assert probe.violated


def test_post_commit_external_ok_other_day() -> None:
    before = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[_row("Oběd-A", day15="1", seq=2)],
    )
    other = _row("Oběd-A", day15="1", seq=3)
    other["d10"] = "2"
    after = build_version_token(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=CAPS,
        rows=[other],
    )
    probe = evaluate_post_commit(
        before=before,
        after=after,
        intended=[IntendedDayState("Oběd-A", 15, "1")],
    )
    assert probe.status is ProbeStatus.EXTERNAL_OK


def test_row_version_material_is_deterministic() -> None:
    row = RowVersion(
        typsluzby="Oběd-A",
        poradiprihl=1,
        rok=2026,
        mesic=9,
        kategorie="KAT1",
        cena="45.00",
        pocet=1,
        day_states=tuple("1" if day == 15 else "N" for day in range(1, 32)),
        seq=1,
    )
    assert row.material_fingerprint == row.material_fingerprint
    assert len(row.material_fingerprint) == 64
