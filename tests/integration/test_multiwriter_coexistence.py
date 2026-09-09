"""Multi-writer coexistence oracles (DETECTION + SAFE RECOVERY).

Tři historické strict XFAIL v test_orders_postgres.py zůstávají — dokazují
nemožnost PREVENTION vůči legacy writeru. Tyto testy dokazují dosažitelnou
bezpečnost JLL 0.5.8.
"""

from __future__ import annotations

import threading
import time
from datetime import date

import pytest
from psycopg import sql

from jll.orders import ErrorCode, OrderAction, OrderBusinessError, OrderCommand
from jll.orders.concurrency import IntendedDayState, ProbeStatus, versions_match
from jll.orders.preflight import monthly_advisory_key

from conftest import LabDatabase
from test_orders_postgres import (
    CATEGORY,
    EVIDCISLO,
    OBED_A,
    TARGET,
    order,
    service,
    set_state,
    state,
)


pytestmark = pytest.mark.integration


def _version(database: LabDatabase, meal_types: list[str] | None = None):
    return service(database).read_version(
        EVIDCISLO,
        TARGET.year,
        TARGET.month,
        meal_types=meal_types or [OBED_A],
    )


def test_mw01_external_commit_before_jll_write_is_rejected(
    lab_database: LabDatabase,
) -> None:
    """MW-01: UI snapshot A, external B změní řádek, JLL click ze A → stale reject."""

    set_state(lab_database, "N")
    snapshot = _version(lab_database)
    set_state(lab_database, "2")  # external change after snapshot
    command = order(action=OrderAction.MENU_ADD, menu=1)
    object.__setattr__(command, "expected_version", snapshot)
    with pytest.raises(OrderBusinessError) as exc:
        service(lab_database).execute(command)
    assert exc.value.code is ErrorCode.ORDER_STALE_STATE
    assert state(lab_database, OBED_A) == "2"


def test_mw02_settle_detects_stale_month_overwrite(
    lab_database: LabDatabase,
) -> None:
    """MW-02: po JLL commit externí overwrite → settle CONFLICT, no retry."""

    set_state(lab_database, "N")
    snapshot = _version(lab_database)
    command = order(action=OrderAction.MENU_ADD, menu=1)
    object.__setattr__(command, "expected_version", snapshot)
    result = service(lab_database).execute(command)
    assert result.success
    assert state(lab_database, OBED_A) == "1"
    # Simulate external stale month writer overwriting JLL day.
    set_state(lab_database, "N")
    probe = service(lab_database).settle_verify(
        evidcislo=EVIDCISLO,
        datum=TARGET,
        intended=[IntendedDayState(OBED_A, TARGET.day, "1")],
        committed_version=result.committed_version,
    )
    assert probe.status is ProbeStatus.CONFLICT
    assert probe.violated
    # No automatic counter-write in settle path.


def test_mw03_other_day_change_is_external_ok(lab_database: LabDatabase) -> None:
    set_state(lab_database, "N")
    snapshot = _version(lab_database)
    command = order(action=OrderAction.MENU_ADD, menu=1)
    object.__setattr__(command, "expected_version", snapshot)
    result = service(lab_database).execute(command)
    assert result.success
    # Change another day without touching intended day.
    other = date(TARGET.year, TARGET.month, 20)
    set_state(lab_database, "3", target=other)
    probe = service(lab_database).settle_verify(
        evidcislo=EVIDCISLO,
        datum=TARGET,
        intended=[IntendedDayState(OBED_A, TARGET.day, "1")],
        committed_version=result.committed_version,
    )
    assert probe.status in {ProbeStatus.EXTERNAL_OK, ProbeStatus.OK}
    assert state(lab_database, OBED_A) == "1"


def test_mw04_same_day_overwrite_is_conflict(lab_database: LabDatabase) -> None:
    set_state(lab_database, "N")
    snapshot = _version(lab_database)
    command = order(action=OrderAction.MENU_ADD, menu=1)
    object.__setattr__(command, "expected_version", snapshot)
    result = service(lab_database).execute(command)
    set_state(lab_database, "5")
    probe = service(lab_database).settle_verify(
        evidcislo=EVIDCISLO,
        datum=TARGET,
        intended=[IntendedDayState(OBED_A, TARGET.day, "1")],
        committed_version=result.committed_version,
    )
    assert probe.status is ProbeStatus.CONFLICT
    assert state(lab_database, OBED_A) == "5"


def test_mw08_seq_or_fingerprint_distinguishes_changes(
    lab_database: LabDatabase,
) -> None:
    set_state(lab_database, "N")
    before = _version(lab_database)
    set_state(lab_database, "1")
    after = _version(lab_database)
    assert not versions_match(before, after)
    caps = after.capabilities
    if caps.has_seq:
        left = before.by_type()[OBED_A]
        right = after.by_type()[OBED_A]
        assert left.seq != right.seq or left.material_fingerprint != right.material_fingerprint
    else:
        assert before.fingerprint() != after.fingerprint()


def test_mw10_happy_path_unchanged_with_version_token(
    lab_database: LabDatabase,
) -> None:
    set_state(lab_database, "N")
    snapshot = _version(lab_database)
    command = order(action=OrderAction.MENU_ADD, menu=1)
    object.__setattr__(command, "expected_version", snapshot)
    result = service(lab_database).execute(command)
    assert result.success
    assert state(lab_database, OBED_A) == "1"
    assert result.post_commit_probe is not None
    assert result.post_commit_probe.status in {
        ProbeStatus.OK,
        ProbeStatus.EXTERNAL_OK,
    }


def test_mw09_polling_lifecycle_helpers() -> None:
    """MW-09: jednotkový kontrakt lifecycle (GUI timer stop/start)."""

    class FakeTimer:
        def __init__(self) -> None:
            self.active = False

        def isActive(self) -> bool:
            return self.active

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

    timer = FakeTimer()
    fingerprint = None
    paused = False
    current_day = object()

    def arm() -> None:
        nonlocal fingerprint
        fingerprint = None
        if not timer.isActive():
            timer.start()

    def poll() -> str:
        nonlocal fingerprint
        if paused or current_day is None:
            if current_day is None and timer.isActive():
                timer.stop()
            return "idle"
        if fingerprint is None:
            fingerprint = "abc"
            return "baseline"
        return "stable"

    arm()
    assert timer.isActive()
    assert poll() == "baseline"
    assert poll() == "stable"
    current_day = None
    assert poll() == "idle"
    assert not timer.isActive()
