from __future__ import annotations

from decimal import Decimal

from .errors import ErrorCode, OrderBusinessError
from .models import OrderCommand, Transition


def audit_price(transition: Transition) -> int | None:
    price = (
        transition.after_price
        if transition.after_state.isdigit()
        else transition.before_price
    )
    integral = price.to_integral_value()
    if price != integral:
        return None
    value = int(integral)
    if not -(2**31) <= value < 2**31:
        return None
    return value


def transition_note(transition: Transition) -> str:
    note = f"{transition.before_state}->{transition.after_state}"
    if len(note) > 50:
        raise OrderBusinessError(
            ErrorCode.AUDIT_FAILED,
            "Auditní poznámka je příliš dlouhá.",
        )
    return note


def validate_audit_command(command: OrderCommand) -> None:
    if len(command.actor) > 25 or len(command.client_version) > 10:
        raise OrderBusinessError(
            ErrorCode.AUDIT_FAILED,
            "Auditní identita nebo verze překračuje DB kontrakt.",
        )
    if len(command.typstravy) > 30:
        raise OrderBusinessError(
            ErrorCode.AUDIT_FAILED,
            "Typ stravy překračuje auditní DB kontrakt.",
        )


def decimal_or_none(value: Decimal) -> Decimal | None:
    return value if value.is_finite() else None
