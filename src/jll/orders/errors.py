from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    ORDERING_CLOSED = "ORDERING_CLOSED"
    OUT_OF_SCOPE_OR_INACTIVE = "OUT_OF_SCOPE_OR_INACTIVE"
    HOUSEHOLD_ACCOUNT_UNSUPPORTED = "HOUSEHOLD_ACCOUNT_UNSUPPORTED"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    NON_COOKING_DAY = "NON_COOKING_DAY"
    MENU_NOT_AVAILABLE = "MENU_NOT_AVAILABLE"
    PRICE_INVALID = "PRICE_INVALID"
    PRICE_PATH_MISMATCH = "PRICE_PATH_MISMATCH"
    CREDIT_DATA_INVALID = "CREDIT_DATA_INVALID"
    INSUFFICIENT_CREDIT = "INSUFFICIENT_CREDIT"
    AMBIGUOUS_ORDER_ROW = "AMBIGUOUS_ORDER_ROW"
    ORDER_ROW_MISSING = "ORDER_ROW_MISSING"
    ORDER_STATE_CONFLICT = "ORDER_STATE_CONFLICT"
    RELATION_CONFIG_INVALID = "RELATION_CONFIG_INVALID"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    LAB_GUARD_FAILED = "LAB_GUARD_FAILED"


class OrderBusinessError(RuntimeError):
    """Expected fail-closed order rejection that must roll back the transaction."""

    def __init__(
        self,
        code: ErrorCode,
        safe_message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.context = context or {}

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code.value!r}, "
            f"safe_message={self.safe_message!r})"
        )
