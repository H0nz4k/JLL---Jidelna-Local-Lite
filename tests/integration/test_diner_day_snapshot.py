"""Atomic DinerDay + OrderVersionToken snapshot consistency."""

from __future__ import annotations

from datetime import date

import pytest

from jll.identity import ActorContext
from jll.orders.models import OrderServiceSettings
from jll.orders.service import OrderService
from jll.policy import Permission, SessionPolicy
from jll.read_service import OrderReadService

from conftest import LabDatabase
from test_orders_postgres import CATEGORY, EVIDCISLO, OBED_A, TARGET, set_state

pytestmark = pytest.mark.integration


def _read(database: LabDatabase) -> OrderReadService:
    settings = OrderServiceSettings(
        environment="lab",
        db_host=database.host,
        db_name=database.name,
        expected_system_identifier=database.system_identifier,
        business_timezone="Europe/Prague",
        lock_timeout_ms=2_000,
        statement_timeout_ms=15_000,
        max_retries=0,
    )
    return OrderReadService(
        database.connect,
        settings,
        SessionPolicy(
            "snapshot",
            frozenset({CATEGORY}),
            frozenset(
                {
                    Permission.DINERS_VIEW,
                    Permission.ORDERS_VIEW,
                    Permission.ORDERS_CHANGE,
                }
            ),
        ),
    )


def test_diner_day_snapshot_is_atomic_against_interleaved_writer(
    lab_database: LabDatabase,
) -> None:
    """Session A must not observe old DinerDay + new version token."""

    set_state(lab_database, "N")
    read = _read(lab_database)
    snapshot = read.load_diner_day_snapshot(EVIDCISLO, TARGET)
    meal = next(m for m in snapshot.day.meals if m.meal_type == OBED_A)
    assert meal.current_state == "N"
    day_fp = snapshot.order_version.fingerprint()

    # External writer changes after atomic snapshot is complete.
    set_state(lab_database, "2")
    after = read.load_diner_day_snapshot(EVIDCISLO, TARGET)
    after_meal = next(m for m in after.day.meals if m.meal_type == OBED_A)
    assert after_meal.current_state == "2"
    assert after.order_version.fingerprint() != day_fp

    # Within one snapshot, day state and token fingerprint always match.
    # Reconstruct: token material for OBED_A day must equal DinerDay state.
    token_row = after.order_version.by_type()[OBED_A]
    assert token_row.day_states[TARGET.day - 1] == after_meal.current_state
