"""Unit testy ChipFinancialConfig."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from jll.chip_financial_config import (
    ChipFinancialConfig,
    load_chip_financial_config,
    require_zero_chip_deposit,
)
from jll.orders.errors import ErrorCode, OrderBusinessError


class _FakeCursor:
    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = list(batches)
        self._current: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: object = None) -> None:
        self._current = self._batches.pop(0) if self._batches else []

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._current)


class _FakeConnection:
    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = batches

    def cursor(self, row_factory: object = None) -> _FakeCursor:
        return _FakeCursor(self._batches)


def test_config_zero_deposit() -> None:
    conn = _FakeConnection(
        [
            [{"sekce": "BACKUP", "parametr": "CenaZaPrvniCip", "hodnota": "0"}],
            [{"hodnota": "0"}],
        ]
    )
    cfg = load_chip_financial_config(conn)
    assert cfg.first_chip_deposit == Decimal("0")
    assert not cfg.requires_payment


def test_config_positive_deposit_blocks_assign() -> None:
    conn = _FakeConnection(
        [
            [{"sekce": "BACKUP", "parametr": "CenaZaPrvniCip", "hodnota": "100"}],
            [{"hodnota": "0"}],
        ]
    )
    with pytest.raises(OrderBusinessError) as exc:
        require_zero_chip_deposit(conn, operation="assign")
    assert exc.value.code is ErrorCode.RELATION_CONFIG_INVALID
    assert "100,00" in str(exc.value)
    assert "nebyl přidělen" in str(exc.value)


def test_missing_parameter_fail_closed() -> None:
    conn = _FakeConnection([[]])
    with pytest.raises(OrderBusinessError) as exc:
        load_chip_financial_config(conn)
    assert "Nelze bezpečně určit zálohu" in str(exc.value)


def test_invalid_and_negative_fail_closed() -> None:
    for raw in ("abc", "-1", "1.234"):
        conn = _FakeConnection(
            [[{"sekce": "BACKUP", "parametr": "CenaZaPrvniCip", "hodnota": raw}]]
        )
        with pytest.raises(OrderBusinessError):
            load_chip_financial_config(conn)


def test_conflicting_values_fail_closed() -> None:
    conn = _FakeConnection(
        [
            [
                {"sekce": "BACKUP", "parametr": "CenaZaPrvniCip", "hodnota": "0"},
                {"sekce": "BACKUP", "parametr": "CenaZaPrvniCip", "hodnota": "50"},
            ]
        ]
    )
    with pytest.raises(OrderBusinessError):
        load_chip_financial_config(conn)


def test_assign_blocked_message_format() -> None:
    cfg = ChipFinancialConfig(first_chip_deposit=Decimal("50.5"))
    assert "50,50" in cfg.assign_blocked_message()
