"""Parita: MENU_DELETE nevyžaduje zveřejnění původního menu."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import (
    Diner,
    MealType,
    OrderAction,
    OrderCommand,
    OrderRow,
    OrderServiceSettings,
)
from jll.orders.service import OrderService

SYSTEM_IDENTIFIER = "123456789"
BUSINESS_TIMEZONE = "Europe/Prague"


def _settings() -> OrderServiceSettings:
    return OrderServiceSettings(
        "lab",
        "127.0.0.1",
        "jll_demo_lab",
        SYSTEM_IDENTIFIER,
        BUSINESS_TIMEZONE,
    )


def _meal(typstravy: str = "Oběd-A", kod: str = "OA") -> MealType:
    return MealType(
        typstravy=typstravy,
        kod=kod,
        prihlasdo=None,
        prihlasdnu=None,
        menudo=None,
        menudnu=None,
        odhlasdo=None,
        odhlasdnu=None,
        spolecnes=None,
        vyloucenos=None,
    )


def _row(*, state: str = "1") -> OrderRow:
    return OrderRow(
        stravnik=123,
        typsluzby="Oběd-A",
        rok=2026,
        mesic=9,
        poradiprihl=1,
        state=state,
        cena=Decimal("80"),
        pocet=1,
        kategorie="KAT1",
    )


def _diner() -> Diner:
    return Diner(
        evidcislo=123,
        kategorie="KAT1",
        hromadny=False,
        preplatekmm=Decimal("100"),
        platittm=Decimal("0"),
        platitpm=None,
        platbatm=Decimal("0"),
        platbabm=None,
    )


def _command(action: OrderAction) -> OrderCommand:
    return OrderCommand(
        action=action,
        evidcislo=123,
        datum=date(2026, 9, 10),
        typstravy="Oběd-A",
        menu=1,
        allowed_categories=frozenset({"KAT1"}),
        actor="LAB",
        client_version="0.1.0",
    )


def test_menu_delete_does_not_require_exact_menu_available() -> None:
    """Odhlášení (legacy objednavka_minus) smí po skrytí jídelníčku."""

    service = OrderService(
        lambda: None,  # type: ignore[arg-type,return-value]
        _settings(),
        scope_provider=lambda item: item.allowed_categories,
    )
    repository = MagicMock()
    repository.exact_menu_available.return_value = False
    repository.write_path_price.return_value = (Decimal("80"), True)
    repository.get_category_limit.return_value = None
    repository.assert_zero_subsidy = MagicMock()

    meal = _meal()
    plan = service._build_plan(  # noqa: SLF001
        repository=repository,
        command=_command(OrderAction.MENU_DELETE),
        diner=_diner(),
        target_type=meal,
        related={meal.kod: meal},
        spolecne_codes=set(),
        vyloucene_codes=set(),
        rows={meal.typstravy: _row(state="1")},
        use_pricelist=True,
    )

    assert plan.transitions
    assert plan.transitions[0].after_state == "N"
    repository.exact_menu_available.assert_not_called()


def test_menu_add_still_requires_published_menu() -> None:
    service = OrderService(
        lambda: None,  # type: ignore[arg-type,return-value]
        _settings(),
        scope_provider=lambda item: item.allowed_categories,
    )
    repository = MagicMock()
    repository.exact_menu_available.return_value = False

    meal = _meal()
    with pytest.raises(OrderBusinessError) as caught:
        service._build_plan(  # noqa: SLF001
            repository=repository,
            command=_command(OrderAction.MENU_ADD),
            diner=_diner(),
            target_type=meal,
            related={meal.kod: meal},
            spolecne_codes=set(),
            vyloucene_codes=set(),
            rows={meal.typstravy: _row(state="N")},
            use_pricelist=True,
        )
    assert caught.value.code is ErrorCode.MENU_NOT_AVAILABLE
    repository.exact_menu_available.assert_called()
