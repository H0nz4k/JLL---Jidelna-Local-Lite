from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import ErrorCode, OrderBusinessError
from .models import Diner, OrderAction, OrderPlan

CENT = Decimal("0.01")


def decimal_from_db(
    value: Any,
    *,
    field: str,
    null_is_zero: bool,
    error_code: ErrorCode,
) -> Decimal:
    if value is None or value == "":
        if null_is_zero:
            return Decimal(0)
        raise OrderBusinessError(error_code, f"Chybí hodnota {field}.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OrderBusinessError(
            error_code,
            f"Hodnota {field} není platné číslo.",
        ) from exc
    if not result.is_finite():
        raise OrderBusinessError(error_code, f"Hodnota {field} není konečná.")
    return result


def calculate_credit(diner: Diner) -> Decimal:
    values = {
        "preplatekmm": diner.preplatekmm,
        "platittm": diner.platittm,
        "platitpm": diner.platitpm,
        "platbatm": diner.platbatm,
        "platbabm": diner.platbabm,
    }
    parsed = {
        key: decimal_from_db(
            value,
            field=key,
            null_is_zero=True,
            error_code=ErrorCode.CREDIT_DATA_INVALID,
        )
        for key, value in values.items()
    }
    result = (
        parsed["preplatekmm"]
        - parsed["platittm"]
        - parsed["platitpm"]
        + parsed["platbatm"]
        + parsed["platbabm"]
    )
    if not result.is_finite():
        raise OrderBusinessError(
            ErrorCode.CREDIT_DATA_INVALID,
            "Výsledný kredit není konečný.",
        )
    return result


def calculate_minimum_balance(limit_value: Any) -> Decimal:
    limit = decimal_from_db(
        limit_value,
        field="limitprihlasky",
        null_is_zero=True,
        error_code=ErrorCode.CREDIT_DATA_INVALID,
    )
    return -abs(limit)


def assert_affordable(plan: OrderPlan) -> None:
    if (
        plan.planned_financial_delta > 0
        and plan.projected_balance < plan.minimum_balance
    ):
        raise OrderBusinessError(
            ErrorCode.INSUFFICIENT_CREDIT,
            "Nedostatečný kredit pro celou plánovanou operaci.",
            context={
                "planned_financial_delta": str(plan.planned_financial_delta),
                "projected_balance": str(plan.projected_balance),
                "minimum_balance": str(plan.minimum_balance),
            },
        )


def monthly_advisory_key(evidcislo: int, target: date) -> int:
    return evidcislo * 1_000_000 + target.year * 100 + target.month


def is_ordered_state(value: str | None) -> bool:
    return value is not None and len(value) == 1 and "1" <= value <= "9"


def parse_day_offset(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový denní limit není platný.",
        ) from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový denní limit není nezáporné celé číslo.",
        )
    return parsed


def parse_cutoff(value: Any) -> time:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if value is None:
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový časový limit chybí.",
        )
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový časový limit není platný.",
        )
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError) as exc:
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový časový limit není platný.",
        ) from exc


def deadline_fields(
    action: OrderAction,
    *,
    prihlasdnu: Any,
    prihlasdo: Any,
    menudnu: Any,
    menudo: Any,
    odhlasdnu: Any,
    odhlasdo: Any,
) -> tuple[int, time]:
    if action is OrderAction.MENU_ADD:
        raw_days, raw_time = prihlasdnu, prihlasdo
    elif action is OrderAction.MENU_CHANGE:
        raw_days, raw_time = menudnu, menudo
    else:
        raw_days, raw_time = odhlasdnu, odhlasdo
    return parse_day_offset(raw_days), parse_cutoff(raw_time)


def assert_deadline(
    *,
    server_now: datetime,
    target: date,
    day_offset: int,
    cutoff: time,
    target_is_cooking: bool,
    calendars: Mapping[tuple[int, int], Mapping[int, bool]],
) -> None:
    if not target_is_cooking:
        raise OrderBusinessError(
            ErrorCode.NON_COOKING_DAY,
            "Cílový den není varný den.",
        )

    current = server_now.date()
    if day_offset == 0:
        operation_date = current
    else:
        operation_date = None
        next_month = 1 if current.month == 12 else current.month + 1
        next_year = current.year + 1 if current.month == 12 else current.year
        allowed_months = {
            (current.year, current.month),
            (next_year, next_month),
        }
        day_count = 1
        while True:
            candidate = current + timedelta(days=day_count)
            key = (candidate.year, candidate.month)
            if key not in allowed_months:
                break
            if (
                day_count >= day_offset
                and calendars.get(key, {}).get(candidate.day) is True
            ):
                operation_date = candidate
                break
            day_count += 1
        if operation_date is None:
            raise OrderBusinessError(
                ErrorCode.DEADLINE_EXPIRED,
                "Nelze určit povolený objednávkový termín.",
            )

    if target < operation_date:
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový termín již uplynul.",
        )
    if target > operation_date:
        return

    now_value = (
        server_now.hour,
        server_now.minute,
        server_now.second,
        server_now.microsecond,
    )
    cutoff_value = (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond)
    if not now_value < cutoff_value:
        raise OrderBusinessError(
            ErrorCode.DEADLINE_EXPIRED,
            "Objednávkový termín již uplynul.",
        )


def assert_price_delta(actual: Decimal, expected: Decimal, message: str) -> None:
    if abs(actual - expected) >= CENT:
        raise OrderBusinessError(
            ErrorCode.POSTCONDITION_FAILED,
            message,
            context={"actual": str(actual), "expected": str(expected)},
        )
