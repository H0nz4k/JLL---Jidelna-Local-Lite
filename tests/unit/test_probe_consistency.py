"""Unit coverage for ProbeStatus.CONSISTENCY."""

from __future__ import annotations

from jll.orders.concurrency import (
    IntendedDayState,
    OrderVersionToken,
    PrihlasCapabilities,
    ProbeStatus,
    RowVersion,
    evaluate_post_commit,
)


def _token(*states: tuple[str, str]) -> OrderVersionToken:
    rows = []
    for typ, day_state in states:
        days = tuple([None] * 9 + [day_state] + [None] * 21)
        rows.append(
            RowVersion(
                typsluzby=typ,
                poradiprihl=1,
                rok=2026,
                mesic=9,
                kategorie="3",
                cena="10",
                pocet=1 if day_state and day_state.isdigit() else 0,
                day_states=days,
                seq=1,
            )
        )
    return OrderVersionToken(
        evidcislo=1,
        year=2026,
        month=9,
        capabilities=PrihlasCapabilities(True, False, False),
        rows=tuple(rows),
    )


def test_exclusive_group_violation_returns_consistency() -> None:
    before = _token(("Oběd-A", "1"), ("Oběd-B", "N"))
    after = _token(("Oběd-A", "1"), ("Oběd-B", "1"))
    probe = evaluate_post_commit(
        before=before,
        after=after,
        intended=[IntendedDayState("Oběd-A", 10, "1")],
        exclusive_peers={
            "Oběd-A": frozenset({"Oběd-B"}),
            "Oběd-B": frozenset({"Oběd-A"}),
        },
    )
    assert probe.status is ProbeStatus.CONSISTENCY


def test_finance_inconsistent_flag_returns_consistency() -> None:
    before = _token(("Oběd-A", "1"))
    after = _token(("Oběd-A", "1"))
    probe = evaluate_post_commit(
        before=before,
        after=after,
        intended=[IntendedDayState("Oběd-A", 10, "1")],
        finance_consistent=False,
    )
    assert probe.status is ProbeStatus.CONSISTENCY
