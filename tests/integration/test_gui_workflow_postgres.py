from __future__ import annotations

from datetime import date

import pytest

from jll.application import OrderApplicationService
from jll.identity import ActorContext
from jll.orders.errors import ErrorCode
from jll.orders.models import OrderAction, OrderServiceSettings
from jll.orders.service import OrderService
from jll.policy import Permission, SessionPolicy
from jll.read_service import OrderReadService

pytestmark = pytest.mark.integration

TARGET = date(2026, 9, 10)
EVIDCISLO = 29
CATEGORY = "3"


def state(view, code: str) -> str | None:
    return next(meal.current_state for meal in view.meals if meal.code == code)


def test_gui_end_to_end_add_variant_change_delete_and_refresh(
    lab_database,
) -> None:
    settings = OrderServiceSettings(
        environment="lab",
        db_host=lab_database.host,
        db_name=lab_database.name,
        expected_system_identifier=lab_database.system_identifier,
        business_timezone="Europe/Prague",
        lock_timeout_ms=2_000,
        statement_timeout_ms=15_000,
        max_retries=0,
    )
    read = OrderReadService(
        lab_database.connect,
        settings,
        SessionPolicy(
            "integration",
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
    write = OrderService(
        lambda: lab_database.connect(autocommit=True),
        settings,
        lambda _command: {CATEGORY},
    )
    application = OrderApplicationService(
        write,
        read,
        read.policy,
        lambda: ActorContext(
            site_id="DEMO",
            instance_id="DEMO-LAB01",
            user_id="integration",
            short_code="TST",
            session_id="integration-session",
            client_version="0.1",
        ),
    )

    found = read.search_diners(str(EVIDCISLO))
    assert len(found) == 1
    assert found[0].category == CATEGORY
    initial = read.load_diner_day(EVIDCISLO, TARGET)
    assert state(initial, "A") in {"N", "S"}
    assert state(initial, "B") in {"N", "S"}

    added = application.execute_selection(EVIDCISLO, TARGET, "Oběd-A", 1)
    assert added.succeeded
    assert added.action is OrderAction.MENU_ADD
    assert added.refreshed is not None
    assert state(added.refreshed, "A") == "1"

    changed = application.execute_selection(EVIDCISLO, TARGET, "Oběd-B", 1)
    assert changed.succeeded
    assert changed.action is OrderAction.MENU_ADD
    assert changed.refreshed is not None
    assert state(changed.refreshed, "A") == "N"
    assert state(changed.refreshed, "B") == "1"

    deleted = application.execute_selection(EVIDCISLO, TARGET, "Oběd-B", 1)
    assert deleted.succeeded
    assert deleted.action is OrderAction.MENU_DELETE
    assert deleted.refreshed is not None
    assert state(deleted.refreshed, "B") == "N"

    with lab_database.connect() as connection:
        other = connection.execute(
            """
            SELECT evidcislo
            FROM public.stravnik
            WHERE kategorie <> %s AND stav = 'A'
              AND COALESCE(deleted, false) = false
            ORDER BY evidcislo LIMIT 1
            """,
            (CATEGORY,),
        ).fetchone()
        assert other is not None
        connection.execute(
            """
            UPDATE public.typstrav
            SET prihlasdnu = 7, prihlasdo = '00:00'
            WHERE typstravy = 'Oběd-A'
            """
        )
    assert read.search_diners(str(other[0])) == []

    expired = application.execute_selection(EVIDCISLO, TARGET, "Oběd-A", 1)
    assert not expired.succeeded
    assert expired.error is not None
    assert expired.error.code == ErrorCode.DEADLINE_EXPIRED.value
    assert expired.refreshed is not None
    assert state(expired.refreshed, "A") == "N"
