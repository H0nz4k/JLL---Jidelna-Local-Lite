"""Unit tests: order relation applicability (sazby ∩ global relations)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import Diner, MealType, OrderAction, OrderCommand
from jll.orders.service import OrderService


def _meal(kod: str, name: str, *, vyloucenos: str = "", spolecnes: str = "") -> MealType:
    return MealType(
        typstravy=name,
        kod=kod,
        prihlasdo=None,
        prihlasdnu=None,
        menudo=None,
        menudnu=None,
        odhlasdo=None,
        odhlasdnu=None,
        spolecnes=spolecnes or None,
        vyloucenos=vyloucenos or None,
    )


def _diner(category: str = "3JARO") -> Diner:
    return Diner(
        evidcislo=3638,
        kategorie=category,
        hromadny=False,
        preplatekmm=0,
        platittm=0,
        platitpm=0,
        platbatm=0,
        platbabm=0,
    )


def _command(**overrides: object) -> OrderCommand:
    values: dict[str, object] = {
        "action": OrderAction.MENU_ADD,
        "evidcislo": 3638,
        "datum": date(2026, 9, 10),
        "typstravy": "Oběd-A",
        "menu": 1,
        "allowed_categories": frozenset({"3JARO"}),
        "actor": "LAB",
        "client_version": "0.5.4",
    }
    values.update(overrides)
    return OrderCommand(**values)  # type: ignore[arg-type]


def _service() -> OrderService:
    return OrderService(
        lambda: None,  # type: ignore[arg-type, return-value]
        SimpleNamespace(
            environment="lab",
            max_retries=0,
            lock_timeout_ms=1000,
            statement_timeout_ms=1000,
            business_timezone="Europe/Prague",
            strict_config_lock=False,
        ),
        lambda _command: frozenset({"3JARO"}),
    )


class _FakeRelationRepo:
    def __init__(
        self,
        *,
        related: dict[str, MealType],
        period_category: str,
        applicable_names: set[str],
    ) -> None:
        self._related = related
        self._period_category = period_category
        self._applicable_names = applicable_names
        self.filter_calls: list[tuple[str, date, tuple[str, ...]]] = []

    def get_related_types(self, codes):
        wanted = set(codes)
        return {kod: item for kod, item in self._related.items() if kod in wanted}

    def resolve_period_category(self, command, diner):
        return self._period_category

    def filter_applicable_meal_types(self, *, category, target, meal_types):
        names = tuple(item.typstravy for item in meal_types)
        self.filter_calls.append((category, target, names))
        return {
            item.typstravy: item
            for item in meal_types
            if item.typstravy in self._applicable_names
        }


def test_partial_exclusive_group_drops_non_applicable_d() -> None:
    target = _meal("A", "Oběd-A", vyloucenos="BCD")
    related = {
        "B": _meal("B", "Oběd-B"),
        "C": _meal("C", "Oběd-C"),
        "D": _meal("D", "Oběd-D"),
    }
    repo = _FakeRelationRepo(
        related=related,
        period_category="3JARO",
        applicable_names={"Oběd-B", "Oběd-C"},
    )
    service = _service()
    effective, spolecne, vyloucene = service._load_relations(
        repo,  # type: ignore[arg-type]
        target,
        command=_command(),
        diner=_diner(),
    )
    assert set(effective) == {"B", "C"}
    assert vyloucene == {"B", "C"}
    assert spolecne == set()
    assert "D" not in effective
    assert repo.filter_calls[0][0] == "3JARO"


def test_applicable_related_kept_when_sazby_exists() -> None:
    target = _meal("A", "Oběd-A", vyloucenos="BCD")
    related = {
        "B": _meal("B", "Oběd-B"),
        "C": _meal("C", "Oběd-C"),
        "D": _meal("D", "Oběd-D"),
    }
    repo = _FakeRelationRepo(
        related=related,
        period_category="3JARO",
        applicable_names={"Oběd-B", "Oběd-C", "Oběd-D"},
    )
    service = _service()
    effective, _spolecne, vyloucene = service._load_relations(
        repo,  # type: ignore[arg-type]
        target,
        command=_command(),
        diner=_diner(),
    )
    assert set(effective) == {"B", "C", "D"}
    assert vyloucene == {"B", "C", "D"}


def test_spolecnes_also_filtered() -> None:
    target = _meal("A", "Oběd-A", spolecnes="BQ")
    related = {
        "B": _meal("B", "Oběd-B"),
        "Q": _meal("Q", "Svačina"),
    }
    repo = _FakeRelationRepo(
        related=related,
        period_category="3JARO",
        applicable_names={"Oběd-B"},
    )
    service = _service()
    effective, spolecne, vyloucene = service._load_relations(
        repo,  # type: ignore[arg-type]
        target,
        command=_command(),
        diner=_diner(),
    )
    assert set(effective) == {"B"}
    assert spolecne == {"B"}
    assert vyloucene == set()


def test_period_category_from_resolver_not_current_diner_blindly() -> None:
    target = _meal("A", "Oběd-A", vyloucenos="B")
    related = {"B": _meal("B", "Oběd-B")}
    repo = _FakeRelationRepo(
        related=related,
        period_category="3JARO",
        applicable_names={"Oběd-B"},
    )
    service = _service()
    service._load_relations(
        repo,  # type: ignore[arg-type]
        target,
        command=_command(),
        diner=_diner(category="1JARO"),
    )
    assert repo.filter_calls[0][0] == "3JARO"


def test_conflict_config_still_fails() -> None:
    target = _meal("A", "Oběd-A", vyloucenos="AB")
    repo = _FakeRelationRepo(
        related={},
        period_category="3JARO",
        applicable_names=set(),
    )
    service = _service()
    with pytest.raises(OrderBusinessError) as exc:
        service._load_relations(
            repo,  # type: ignore[arg-type]
            target,
            command=_command(),
            diner=_diner(),
        )
    assert exc.value.code is ErrorCode.RELATION_CONFIG_INVALID
