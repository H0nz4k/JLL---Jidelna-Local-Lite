"""Unit tests: HOME today overview models + sorting helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from jll.policy import Permission, SessionPolicy
from jll.read_models import (
    HomeMealSummary,
    HomeTodayOverview,
    portions_cs,
    workplace_display_name,
)
from jll.read_service import OrderReadService


def test_portions_cs_inflection() -> None:
    assert portions_cs(0) == "0 porcí"
    assert portions_cs(1) == "1 porce"
    assert portions_cs(2) == "2 porce"
    assert portions_cs(4) == "4 porce"
    assert portions_cs(5) == "5 porcí"
    assert portions_cs(12) == "12 porcí"


def test_workplace_display_name() -> None:
    assert workplace_display_name("JAROV") == "Jarov"
    assert workplace_display_name("Jarov") == "Jarov"
    assert workplace_display_name("") == "—"


def test_home_overview_total_and_labels() -> None:
    meals = (
        HomeMealSummary("Oběd-A", 1, 2, "Rizoto", True),
        HomeMealSummary("Oběd-A", 2, 3, None, False),
        HomeMealSummary("Svačina", 1, 1, "Bábovka", True),
    )
    overview = HomeTodayOverview(
        workplace_name="Jarov",
        organization_name="Scio Kuchyně",
        target_date=date(2026, 9, 8),
        is_cooking_day=True,
        next_cooking_day=None,
        total_portions=sum(m.portions for m in meals),
        meals=meals,
    )
    assert overview.total_portions == 6
    assert overview.date_label.startswith("Úterý")
    assert meals[1].name_line == "Jídelníček není zveřejněn"
    assert meals[0].title_line == "Oběd-A · Menu 1"


def test_home_non_cooking_empty_meals() -> None:
    overview = HomeTodayOverview(
        workplace_name="Jarov",
        organization_name="Scio",
        target_date=date(2026, 9, 12),
        is_cooking_day=False,
        next_cooking_day=date(2026, 9, 14),
        total_portions=0,
        meals=(),
    )
    assert overview.is_cooking_day is False
    assert overview.next_cooking_day == date(2026, 9, 14)


def test_load_home_requires_diners_view() -> None:
    policy = SessionPolicy(
        user_identity="x",
        allowed_categories=frozenset({"1JARO"}),
        permissions=frozenset(),
    )
    service = OrderReadService(
        lambda: MagicMock(),
        MagicMock(business_timezone="Europe/Prague", statement_timeout_ms=5000),
        lambda: policy,
    )
    with pytest.raises(Exception):
        service.load_home_today_overview(
            workplace_name="JAROV",
            organization_name="Scio",
        )


def test_load_home_uses_diners_view_not_reports() -> None:
    """Dokumentační kontrakt: HOME permission je DINERS_VIEW."""

    source = OrderReadService.load_home_today_overview.__doc__ or ""
    assert "DINERS_VIEW" in source
    assert Permission.DINERS_VIEW.value == "diners.view"
