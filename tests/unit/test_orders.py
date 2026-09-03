from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

import psycopg
import pytest

from jll.orders.audit import audit_price, transition_note
from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import (
    Diner,
    OrderAction,
    OrderCommand,
    OrderMetrics,
    OrderPlan,
    OrderResult,
    OrderServiceSettings,
    Transition,
    TransitionReason,
)
from jll.orders.preflight import (
    assert_affordable,
    assert_deadline,
    calculate_credit,
    calculate_minimum_balance,
    deadline_fields,
    decimal_from_db,
    monthly_advisory_key,
)
from jll.orders.service import OrderService

SYSTEM_IDENTIFIER = "123456789"
BUSINESS_TIMEZONE = "Europe/Prague"


def command(**overrides: object) -> OrderCommand:
    values: dict[str, object] = {
        "action": OrderAction.MENU_ADD,
        "evidcislo": 123,
        "datum": date(2026, 9, 10),
        "typstravy": "Oběd-A",
        "menu": 1,
        "allowed_categories": frozenset({"KAT1"}),
        "actor": "LAB",
        "client_version": "0.1.0",
    }
    values.update(overrides)
    return OrderCommand(**values)  # type: ignore[arg-type]


def transition(
    before: str,
    after: str,
    before_price: str = "0",
    after_price: str = "80",
) -> Transition:
    return Transition(
        typstravy="Oběd-A",
        before_state=before,
        after_state=after,
        before_price=Decimal(before_price),
        after_price=Decimal(after_price),
        reason=TransitionReason.PRIMARY,
        poradiprihl=1,
    )


def test_command_normalizes_action_and_categories() -> None:
    result = command(
        action="menu_delete",
        allowed_categories=frozenset({" KAT1 ", "KAT2"}),
    )
    assert result.action is OrderAction.MENU_DELETE
    assert result.allowed_categories == frozenset({"KAT1", "KAT2"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"menu": 0},
        {"menu": 10},
        {"evidcislo": 2**31},
        {"allowed_categories": frozenset()},
        {"actor": ""},
        {"typstravy": "x" * 21},
    ],
)
def test_command_rejects_invalid_input(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        command(**overrides)


def test_monthly_advisory_key_is_same_within_month_and_distinct_across_months() -> None:
    first = monthly_advisory_key(123, date(2026, 9, 1))
    assert first == monthly_advisory_key(123, date(2026, 9, 30))
    assert first != monthly_advisory_key(123, date(2026, 10, 1))
    assert first != monthly_advisory_key(124, date(2026, 9, 1))


def test_monthly_advisory_key_is_unique_and_bigint_safe_at_supported_bounds() -> None:
    evid_numbers = [-(2**31), -1, 0, 1, 2**31 - 1]
    months = [
        date(1, 1, 1),
        date(2026, 9, 1),
        date(9999, 12, 1),
    ]
    keys = {
        monthly_advisory_key(evidcislo, month)
        for evidcislo in evid_numbers
        for month in months
    }
    assert len(keys) == len(evid_numbers) * len(months)
    assert all(-(2**63) <= key < 2**63 for key in keys)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "x"])
def test_decimal_rejects_invalid_values(value: str) -> None:
    with pytest.raises(OrderBusinessError) as caught:
        decimal_from_db(
            value,
            field="credit",
            null_is_zero=False,
            error_code=ErrorCode.CREDIT_DATA_INVALID,
        )
    assert caught.value.code is ErrorCode.CREDIT_DATA_INVALID


def test_credit_preserves_source_null_as_zero() -> None:
    diner = Diner(
        evidcislo=1,
        kategorie="KAT1",
        hromadny=False,
        preplatekmm=Decimal("100"),
        platittm=Decimal("20"),
        platitpm=None,
        platbatm=Decimal("5"),
        platbabm=None,
    )
    assert calculate_credit(diner) == Decimal("85")
    assert calculate_minimum_balance(Decimal("-200")) == Decimal("-200")
    assert calculate_minimum_balance(None) == Decimal(0)


def test_financial_plan_checks_total_net_delta() -> None:
    refund = Transition(
        "Oběd-A",
        "1",
        "N",
        Decimal("80"),
        Decimal(0),
        TransitionReason.VYLOUCENOS,
        1,
    )
    add = Transition(
        "Oběd-B",
        "N",
        "1",
        Decimal(0),
        Decimal("90"),
        TransitionReason.PRIMARY,
        1,
    )
    plan = OrderPlan((refund, add), Decimal("-190"), Decimal("-200"))
    assert plan.planned_financial_delta == Decimal("10")
    assert plan.projected_balance == Decimal("-200")
    assert_affordable(plan)


def test_financial_plan_rejects_total_delta_below_limit() -> None:
    plan = OrderPlan(
        (transition("N", "1", "0", "80"),),
        current_credit=Decimal("-150"),
        minimum_balance=Decimal("-200"),
    )
    with pytest.raises(OrderBusinessError) as caught:
        assert_affordable(plan)
    assert caught.value.code is ErrorCode.INSUFFICIENT_CREDIT


def test_refund_is_never_blocked_by_credit() -> None:
    plan = OrderPlan(
        (transition("1", "N", "80", "0"),),
        current_credit=Decimal("-999"),
        minimum_balance=Decimal(0),
    )
    assert_affordable(plan)


def test_deadline_uses_strict_cutoff() -> None:
    calendars = {(2026, 9): {3: True}}
    with pytest.raises(OrderBusinessError) as caught:
        assert_deadline(
            server_now=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
            target=date(2026, 9, 3),
            day_offset=0,
            cutoff=time(9, 0),
            target_is_cooking=True,
            calendars=calendars,
        )
    assert caught.value.code is ErrorCode.DEADLINE_EXPIRED


def test_deadline_allows_time_strictly_before_cutoff() -> None:
    assert_deadline(
        server_now=datetime(2026, 9, 3, 8, 59, 59, tzinfo=timezone.utc),
        target=date(2026, 9, 3),
        day_offset=0,
        cutoff=time(9, 0),
        target_is_cooking=True,
        calendars={(2026, 9): {3: True}},
    )


def test_deadline_allows_one_millisecond_before_cutoff() -> None:
    assert_deadline(
        server_now=datetime(
            2026,
            9,
            3,
            8,
            59,
            59,
            999_000,
            tzinfo=timezone.utc,
        ),
        target=date(2026, 9, 3),
        day_offset=0,
        cutoff=time(9, 0),
        target_is_cooking=True,
        calendars={(2026, 9): {3: True}},
    )


@pytest.mark.parametrize(
    "server_now",
    [
        datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 3, 9, 0, 0, 1_000, tzinfo=timezone.utc),
    ],
)
def test_deadline_rejects_exactly_at_and_one_millisecond_after_cutoff(
    server_now: datetime,
) -> None:
    with pytest.raises(OrderBusinessError) as caught:
        assert_deadline(
            server_now=server_now,
            target=date(2026, 9, 3),
            day_offset=0,
            cutoff=time(9, 0),
            target_is_cooking=True,
            calendars={(2026, 9): {3: True}},
        )
    assert caught.value.code is ErrorCode.DEADLINE_EXPIRED


@pytest.mark.parametrize(
    ("action", "expected_days", "expected_cutoff"),
    [
        (OrderAction.MENU_ADD, 1, time(8, 1)),
        (OrderAction.MENU_CHANGE, 2, time(8, 2)),
        (OrderAction.MENU_DELETE, 3, time(8, 3)),
    ],
)
def test_action_uses_its_own_deadline_fields(
    action: OrderAction,
    expected_days: int,
    expected_cutoff: time,
) -> None:
    assert deadline_fields(
        action,
        prihlasdnu=1,
        prihlasdo=time(8, 1),
        menudnu=2,
        menudo=time(8, 2),
        odhlasdnu=3,
        odhlasdo=time(8, 3),
    ) == (expected_days, expected_cutoff)


def test_deadline_uses_minimum_calendar_offset_then_first_cooking_day() -> None:
    calendars = {(2026, 9): {4: False, 5: False, 6: True, 7: True}}
    assert_deadline(
        server_now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
        target=date(2026, 9, 7),
        day_offset=1,
        cutoff=time(9, 0),
        target_is_cooking=True,
        calendars=calendars,
    )
    with pytest.raises(OrderBusinessError):
        assert_deadline(
            server_now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
            target=date(2026, 9, 5),
            day_offset=1,
            cutoff=time(9, 0),
            target_is_cooking=True,
            calendars=calendars,
        )


def test_non_cooking_target_is_rejected() -> None:
    with pytest.raises(OrderBusinessError) as caught:
        assert_deadline(
            server_now=datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc),
            target=date(2026, 9, 3),
            day_offset=0,
            cutoff=time(9, 0),
            target_is_cooking=False,
            calendars={(2026, 9): {3: False}},
        )
    assert caught.value.code is ErrorCode.NON_COOKING_DAY


def test_audit_uses_real_transition_and_integral_menu_price() -> None:
    item = transition("1", "2", "80", "90")
    assert transition_note(item) == "1->2"
    assert audit_price(item) == 90


def test_audit_does_not_round_fractional_price() -> None:
    assert audit_price(transition("N", "1", "0", "80.50")) is None


class IdentityRepository:
    def __init__(
        self,
        database: str,
        address: str | None,
        system_identifier: str = SYSTEM_IDENTIFIER,
    ) -> None:
        self.database = database
        self.address = address
        self.system_identifier = system_identifier

    def lab_identity(self) -> dict[str, object]:
        return {
            "database_name": self.database,
            "server_address": self.address,
            "server_port": 5433,
            "system_identifier": self.system_identifier,
            "server_version": "PostgreSQL LAB",
        }


def service(settings: OrderServiceSettings) -> OrderService:
    return OrderService(  # type: ignore[arg-type]
        lambda: None,  # type: ignore[return-value]
        settings,
        scope_provider=lambda command: command.allowed_categories,
    )


def test_lab_guard_accepts_exact_local_lab_identity() -> None:
    settings = OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
    )
    service(settings)._assert_lab_guard(  # noqa: SLF001
        IdentityRepository("jll_demo_lab", "127.0.0.1")  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("settings", "database", "address"),
    [
        (OrderServiceSettings("prod", "127.0.0.1", "jll_demo_lab", SYSTEM_IDENTIFIER, BUSINESS_TIMEZONE), "jll_demo_lab", "127.0.0.1"),
        (OrderServiceSettings("lab", "db.example", "jll_demo_lab", SYSTEM_IDENTIFIER, BUSINESS_TIMEZONE), "jll_demo_lab", "127.0.0.1"),
        (OrderServiceSettings("lab", "127.0.0.1", "demo", SYSTEM_IDENTIFIER, BUSINESS_TIMEZONE), "demo", "127.0.0.1"),
        (OrderServiceSettings("lab", "127.0.0.1", "jll_demo_lab", SYSTEM_IDENTIFIER, BUSINESS_TIMEZONE), "jll_demo_lab", "10.0.0.2"),
        (OrderServiceSettings("lab", "127.0.0.1", "jll_demo_lab", SYSTEM_IDENTIFIER, BUSINESS_TIMEZONE), "other_jll", "127.0.0.1"),
    ],
)
def test_lab_guard_rejects_unsafe_identity(
    settings: OrderServiceSettings,
    database: str,
    address: str,
) -> None:
    with pytest.raises(OrderBusinessError) as caught:
        service(settings)._assert_lab_guard(  # noqa: SLF001
            IdentityRepository(database, address)  # type: ignore[arg-type]
        )
    assert caught.value.code is ErrorCode.LAB_GUARD_FAILED


def test_lab_guard_rejects_different_postgres_cluster() -> None:
    settings = OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
    )
    with pytest.raises(OrderBusinessError) as caught:
        service(settings)._assert_lab_guard(  # noqa: SLF001
            IdentityRepository(
                "jll_demo_lab",
                "127.0.0.1",
                system_identifier="999999",
            )  # type: ignore[arg-type]
        )
    assert caught.value.code is ErrorCode.LAB_GUARD_FAILED


def test_command_scope_cannot_authorize_itself() -> None:
    settings = OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
    )
    opened = False

    def connect() -> None:
        nonlocal opened
        opened = True
        return None

    target_service = OrderService(  # type: ignore[arg-type]
        connect,  # type: ignore[arg-type]
        settings,
        scope_provider=lambda _command: frozenset({"KAT2"}),
    )
    with pytest.raises(OrderBusinessError) as caught:
        target_service.execute(command(allowed_categories=frozenset({"KAT1"})))
    assert caught.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
    assert opened is False


def test_scope_provider_is_rechecked_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
        max_retries=1,
    )
    provider_calls = 0
    transaction_calls = 0

    def scope_provider(_command: OrderCommand) -> frozenset[str]:
        nonlocal provider_calls
        provider_calls += 1
        return frozenset({"KAT1"} if provider_calls == 1 else {"KAT2"})

    target_service = OrderService(
        lambda: None,  # type: ignore[arg-type,return-value]
        settings,
        scope_provider=scope_provider,
        sleeper=lambda _seconds: None,
    )

    def execute_once(_command: OrderCommand) -> OrderResult:
        nonlocal transaction_calls
        transaction_calls += 1
        raise psycopg.errors.DeadlockDetected("synthetic deadlock")

    monkeypatch.setattr(target_service, "_execute_once", execute_once)

    with pytest.raises(OrderBusinessError) as caught:
        target_service.execute(command())

    assert caught.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
    assert provider_calls == 2
    assert transaction_calls == 1


def test_deadlock_is_retried_with_a_fresh_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
        max_retries=1,
    )
    target_service = OrderService(
        lambda: None,  # type: ignore[arg-type,return-value]
        settings,
        scope_provider=lambda item: item.allowed_categories,
        sleeper=lambda _seconds: None,
    )
    expected = OrderResult(
        success=True,
        action=OrderAction.MENU_ADD,
        evidcislo=123,
        datum=date(2026, 9, 10),
        committed_transitions=(),
        committed_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        metrics=OrderMetrics(),
    )
    attempts = 0

    def execute_once(_command: OrderCommand) -> OrderResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise psycopg.errors.DeadlockDetected("synthetic deadlock")
        return expected

    monkeypatch.setattr(target_service, "_execute_once", execute_once)

    result = target_service.execute(command())

    assert attempts == 2
    assert result.metrics.attempts == 2
