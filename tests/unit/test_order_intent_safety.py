"""P0-1: UI intent se nesmí invertovat podle fresh DB."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from jll.application import OrderApplicationService, determine_action
from jll.identity import ActorContext
from jll.orders.concurrency import OrderVersionToken, PrihlasCapabilities
from jll.orders.errors import ErrorCode
from jll.orders.models import OrderAction
from jll.policy import Permission, SessionPolicy
from jll.read_models import (
    ActionAvailability,
    DinerDay,
    DinerDetail,
    MealDay,
    MenuOption,
)


def _availability() -> tuple[ActionAvailability, ...]:
    return tuple(ActionAvailability(action, True) for action in OrderAction)


def _meal(
    *,
    name: str,
    state: str | None,
) -> MealDay:
    return MealDay(
        code=name[-1] if name else "A",
        meal_type=name,
        display_order=1,
        current_state=state,
        options=(
            MenuOption(1, "První", Decimal("20")),
            MenuOption(2, "Druhé", Decimal("21")),
            MenuOption(3, "Třetí", Decimal("22")),
        ),
        availability=_availability(),
        exclusive_codes=frozenset(),
        allowed_menus=(1, 2, 3),
    )


def _day_with_meal(meal: MealDay) -> DinerDay:
    return DinerDay(
        diner=DinerDetail(123, "LAB Test", "KAT2", "8.A", Decimal("1000")),
        target_date=date(2026, 9, 4),
        server_now=datetime(2026, 9, 3, 8),
        meals=(meal,),
    )


class _FakeRead:
    def __init__(self, view: DinerDay) -> None:
        self.view = view
        self.load_calls = 0

    def load_diner_day(self, _evidcislo: int, _target: date) -> DinerDay:
        self.load_calls += 1
        return self.view


class _FakeWrite:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    def read_version(self, evidcislo: int, year: int, month: int, meal_types=None):
        del meal_types
        return OrderVersionToken(
            evidcislo=evidcislo,
            year=year,
            month=month,
            capabilities=PrihlasCapabilities(False, False, False),
            rows=(),
        )

    def execute(self, command: Any) -> Any:
        self.commands.append(command)
        return object()


def _policy() -> SessionPolicy:
    return SessionPolicy(
        "tester",
        frozenset({"KAT2"}),
        frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.ORDERS_VIEW,
                Permission.ORDERS_CHANGE,
            }
        ),
    )


def _actor() -> ActorContext:
    return ActorContext(
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        user_id="tester",
        short_code="TST",
        session_id="session-1",
        client_version="0.6.0",
    )


def _empty_version() -> OrderVersionToken:
    return OrderVersionToken(
        evidcislo=123,
        year=2026,
        month=9,
        capabilities=PrihlasCapabilities(False, False, False),
        rows=(),
    )


def test_rendered_add_external_same_menu_is_stale_never_delete() -> None:
    """Rendered ADD; external orders menu 1; click still ADD → STALE, no DELETE."""

    rendered = _day_with_meal(
        MealDay(
            code="A",
            meal_type="Oběd-A",
            display_order=1,
            current_state="N",
            options=(MenuOption(1, "První", Decimal("20")),),
            availability=_availability(),
            exclusive_codes=frozenset(),
            allowed_menus=(1,),
        )
    )
    assert determine_action(rendered.meals[0], 1) is OrderAction.MENU_ADD
    assert rendered.meals[0].ordered_menu is None

    fresh = _day_with_meal(
        MealDay(
            code="A",
            meal_type="Oběd-A",
            display_order=1,
            current_state="1",
            options=(MenuOption(1, "První", Decimal("20")),),
            availability=_availability(),
            exclusive_codes=frozenset(),
            allowed_menus=(1,),
        )
    )
    assert determine_action(fresh.meals[0], 1) is OrderAction.MENU_DELETE

    read = _FakeRead(fresh)
    write = _FakeWrite()
    app = OrderApplicationService(write, read, _policy(), _actor)  # type: ignore[arg-type]
    outcome = app.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-A",
        1,
        expected_action=OrderAction.MENU_ADD,
        expected_version=_empty_version(),
        expected_ordered_menu=None,
    )
    assert not outcome.succeeded
    assert outcome.error is not None
    assert outcome.error.code == ErrorCode.ORDER_STALE_STATE.value
    assert write.commands == []
    assert outcome.action is OrderAction.MENU_ADD


def test_rendered_delete_external_already_unsubscribed_is_stale() -> None:
    rendered_ordered = MealDay(
        code="A",
        meal_type="Oběd-A",
        display_order=1,
        current_state="1",
        options=(MenuOption(1, "První", Decimal("20")),),
        availability=_availability(),
        exclusive_codes=frozenset(),
        allowed_menus=(1,),
    )
    assert determine_action(rendered_ordered, 1) is OrderAction.MENU_DELETE

    fresh_empty = MealDay(
        code="A",
        meal_type="Oběd-A",
        display_order=1,
        current_state="N",
        options=(MenuOption(1, "První", Decimal("20")),),
        availability=_availability(),
        exclusive_codes=frozenset(),
        allowed_menus=(1,),
    )
    read = _FakeRead(_day_with_meal(fresh_empty))
    write = _FakeWrite()
    app = OrderApplicationService(write, read, _policy(), _actor)  # type: ignore[arg-type]
    outcome = app.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-A",
        1,
        expected_action=OrderAction.MENU_DELETE,
        expected_version=_empty_version(),
        expected_ordered_menu=1,
    )
    assert not outcome.succeeded
    assert outcome.error is not None
    assert outcome.error.code == ErrorCode.ORDER_STALE_STATE.value
    assert write.commands == []


def test_rendered_change_a_to_b_external_a_to_c_is_stale() -> None:
    fresh = MealDay(
        code="A",
        meal_type="Oběd-A",
        display_order=1,
        current_state="3",
        options=(
            MenuOption(1, "První", Decimal("20")),
            MenuOption(2, "Druhé", Decimal("21")),
            MenuOption(3, "Třetí", Decimal("22")),
        ),
        availability=_availability(),
        exclusive_codes=frozenset(),
        allowed_menus=(1, 2, 3),
    )
    # Fresh would still be CHANGE 3→2, but ordered_menu no longer 1.
    assert determine_action(fresh, 2) is OrderAction.MENU_CHANGE
    assert fresh.ordered_menu == 3

    read = _FakeRead(_day_with_meal(fresh))
    write = _FakeWrite()
    app = OrderApplicationService(write, read, _policy(), _actor)  # type: ignore[arg-type]
    outcome = app.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-A",
        2,
        expected_action=OrderAction.MENU_CHANGE,
        expected_version=_empty_version(),
        expected_ordered_menu=1,
    )
    assert not outcome.succeeded
    assert outcome.error is not None
    assert outcome.error.code == ErrorCode.ORDER_STALE_STATE.value
    assert write.commands == []
