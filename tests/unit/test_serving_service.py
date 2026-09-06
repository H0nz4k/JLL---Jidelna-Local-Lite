"""Unit testy ServingService: settings, scope, write gate, evidcislo."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import OrderServiceSettings
from jll.policy import Permission, SessionPolicy
from jll.serving_repository import ServingRepository
from jll.serving_service import ServingService
from jll.write_gates import SERVING_WRITE_GATES, require_proven

SYSTEM_IDENTIFIER = "123456789"
BUSINESS_TIMEZONE = "Europe/Prague"


def lab_settings() -> OrderServiceSettings:
    return OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
    )


def policy(*, categories: frozenset[str] = frozenset({"KAT1"})) -> SessionPolicy:
    return SessionPolicy(
        user_identity="LAB",
        allowed_categories=categories,
        permissions=frozenset(
            {
                Permission.ORDERS_CHANGE,
                Permission.CHIPS_VIEW,
                Permission.PICKUP_STATUS_VIEW,
            }
        ),
    )


class FakeCursor:
    def __init__(self, owner: "_FakeConnection") -> None:
        self._owner = owner
        self._row: Any = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, sql: str, params: object | None = None) -> None:
        text = " ".join(str(sql).split())
        if "lab_identity" in text or "current_database()" in text:
            self._row = {
                "database_name": "jll_demo_lab",
                "server_address": "127.0.0.1",
                "server_port": 5432,
                "system_identifier": SYSTEM_IDENTIFIER,
                "server_version": "PostgreSQL",
            }
            return
        if "FROM public.prihlas" in text:
            self._row = self._owner.prihlas_row
            return
        if "zapis_odber" in text:
            self._row = (True,)
            return
        self._row = None

    def fetchone(self) -> Any:
        return self._row


class _FakeConnection:
    def __init__(self, prihlas_row: tuple[int, str] | None) -> None:
        self.prihlas_row = prihlas_row
        self.autocommit = True

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def transaction(self) -> Any:
        return nullcontext()

    def cursor(self, row_factory: object | None = None) -> FakeCursor:
        return FakeCursor(self)


def make_service(
    *,
    prihlas_row: tuple[int, str] | None = (10, "KAT1"),
    settings: OrderServiceSettings | None = None,
    session: SessionPolicy | None = None,
) -> ServingService:
    conn = _FakeConnection(prihlas_row)

    def factory() -> _FakeConnection:
        return conn

    return ServingService(
        factory,
        lambda: session or policy(),
        settings if settings is not None else lab_settings(),
    )


def test_serving_service_requires_settings_on_construction() -> None:
    with pytest.raises(TypeError):
        ServingService(lambda: None, lambda: policy())  # type: ignore[call-arg]


def test_record_pickup_out_of_scope_category_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ServingRepository,
        "lab_identity",
        lambda self: {
            "database_name": "jll_demo_lab",
            "server_address": "127.0.0.1",
            "system_identifier": SYSTEM_IDENTIFIER,
        },
    )
    service = make_service(prihlas_row=(10, "OTHER"))
    with pytest.raises(OrderBusinessError) as caught:
        service.record_pickup(1, evidcislo=10)
    assert caught.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE


def test_require_proven_record_pickup_gate_enabled() -> None:
    assert SERVING_WRITE_GATES["record_pickup"].enabled is True
    require_proven(SERVING_WRITE_GATES, "record_pickup")


def test_record_pickup_rejects_mismatched_evidcislo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ServingRepository,
        "lab_identity",
        lambda self: {
            "database_name": "jll_demo_lab",
            "server_address": "127.0.0.1",
            "system_identifier": SYSTEM_IDENTIFIER,
        },
    )
    zapis = MagicMock(return_value=True)
    monkeypatch.setattr(ServingRepository, "zapis_odber", zapis)
    service = make_service(prihlas_row=(10, "KAT1"))
    with pytest.raises(OrderBusinessError) as caught:
        service.record_pickup(1, evidcislo=99)
    assert caught.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
    assert "nepatří" in caught.value.safe_message.casefold()
    zapis.assert_not_called()
