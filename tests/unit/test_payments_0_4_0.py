"""Unit tests for payment models / gates (no DB)."""

from __future__ import annotations

from jll.payment_models import LEDGER_TYPE_LABELS, PAYMENT_HISTORY_TYPES
from jll.policy import Permission
from jll.permission_catalog import permission_title
from jll.business_session import VED_DEFAULT_PERMISSIONS


def test_payment_history_types_are_p_and_c() -> None:
    assert PAYMENT_HISTORY_TYPES == frozenset({"P", "C"})
    assert LEDGER_TYPE_LABELS["P"] == "Platba"
    assert LEDGER_TYPE_LABELS["C"] == "Čip"


def test_payment_permissions_in_ved_defaults() -> None:
    assert Permission.PAYMENTS_VIEW in VED_DEFAULT_PERMISSIONS
    assert Permission.PAYMENTS_POST in VED_DEFAULT_PERMISSIONS
    assert permission_title(Permission.PAYMENTS_VIEW) == "Zobrazit platby"
    assert permission_title(Permission.PAYMENTS_POST) == "Zaúčtovat platbu"
