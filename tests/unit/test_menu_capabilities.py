from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.read_models import MenuCapability
from jll.read_service import OrderReadService


class FakeRepository:
    def __init__(self, rows: list[Mapping[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.parameters: list[Sequence[Any]] = []

    def fetchall(
        self,
        query: str,
        params: Sequence[Any] = (),
    ) -> list[Mapping[str, Any]]:
        self.queries.append(str(query))
        self.parameters.append(params)
        return self.rows


def capabilities(rows: list[Mapping[str, Any]]) -> dict[str, tuple[int, ...]]:
    repository = FakeRepository(rows)
    return OrderReadService._load_menu_capabilities(
        repository,  # type: ignore[arg-type]
        "KAT2",
        ["Oběd-A", "Svačina"],
        date(2026, 9, 3),
    )


def test_allowed_menu_numbers_are_contiguous_range_from_pocetmenu() -> None:
    result = capabilities(
        [
            {"typstravy": "Oběd-A", "pocetmenu": 3},
            {"typstravy": "Svačina", "pocetmenu": 1},
        ]
    )
    assert result == {"Oběd-A": (1, 2, 3), "Svačina": (1,)}


def test_missing_sazby_row_means_no_allowed_menu() -> None:
    result = capabilities([{"typstravy": "Svačina", "pocetmenu": 1}])
    assert "Oběd-A" not in result
    assert result["Svačina"] == (1,)


def test_zero_or_null_pocetmenu_is_empty_not_defaulted() -> None:
    result = capabilities(
        [
            {"typstravy": "Oběd-A", "pocetmenu": 0},
            {"typstravy": "Svačina", "pocetmenu": None},
        ]
    )
    assert result == {"Oběd-A": (), "Svačina": ()}


def test_query_is_scoped_by_category_meal_types_and_day() -> None:
    repository = FakeRepository([])
    OrderReadService._load_menu_capabilities(
        repository,  # type: ignore[arg-type]
        "KAT2",
        ["Oběd-A"],
        date(2026, 9, 3),
    )
    query = repository.queries[0]
    assert "public.sazby" in query
    assert "pocetmenu" in query
    assert "platnostod" in query and "platnostdo" in query
    assert repository.parameters[0][0] == "KAT2"
    assert repository.parameters[0][1] == ["Oběd-A"]
    assert repository.parameters[0][2] == date(2026, 9, 3)


def test_no_meal_types_does_not_query_database() -> None:
    repository = FakeRepository([{"typstravy": "Oběd-A", "pocetmenu": 1}])
    result = OrderReadService._load_menu_capabilities(
        repository,  # type: ignore[arg-type]
        "KAT2",
        [],
        date(2026, 9, 3),
    )
    assert result == {}
    assert repository.queries == []


def test_ambiguous_overlapping_sazby_fails_closed() -> None:
    with pytest.raises(OrderBusinessError) as captured:
        capabilities(
            [
                {"typstravy": "Oběd-A", "pocetmenu": 1},
                {"typstravy": "Oběd-A", "pocetmenu": 2},
            ]
        )
    assert captured.value.code is ErrorCode.RELATION_CONFIG_INVALID


def test_menu_count_above_single_digit_fails_closed() -> None:
    with pytest.raises(OrderBusinessError) as captured:
        capabilities([{"typstravy": "Oběd-A", "pocetmenu": 10}])
    assert captured.value.code is ErrorCode.RELATION_CONFIG_INVALID


def test_capability_model_reports_count_from_numbers() -> None:
    capability = MenuCapability("Oběd-A", (1, 2))
    assert capability.allowed_menu_count == 2
