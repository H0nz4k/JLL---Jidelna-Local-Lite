"""Parita: periodická kategorie přihlášky (`prihlas.kategorie`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jll.orders.models import OrderRow
from jll.read_service import (
    _CATEGORY_SUMMARY_SQL,
    _NAMED_LIST_SQL,
    _NORM_SUMMARY_SQL,
)


def test_order_row_requires_kategorie_field() -> None:
    with pytest.raises(TypeError):
        OrderRow(  # type: ignore[call-arg]
            stravnik=1,
            typsluzby="Oběd-A",
            rok=2026,
            mesic=9,
            poradiprihl=1,
            state="1",
            cena=Decimal("80"),
            pocet=1,
        )
    row = OrderRow(
        stravnik=1,
        typsluzby="Oběd-A",
        rok=2026,
        mesic=9,
        poradiprihl=1,
        state="1",
        cena=Decimal("80"),
        pocet=1,
        kategorie="KAT1",
    )
    assert row.kategorie == "KAT1"


def test_report_sql_uses_period_category_and_scope_on_stravnik() -> None:
    for sql in (_CATEGORY_SUMMARY_SQL, _NORM_SUMMARY_SQL, _NAMED_LIST_SQL):
        assert "p.kategorie" in sql or "btrim(p.kategorie)" in sql
        assert "btrim(p.kategorie)" in sql or "p.kategorie" in sql
        assert "s.kategorie = ANY" in sql
