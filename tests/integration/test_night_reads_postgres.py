"""Scope-safe čtení pro identifikaci čipu, kartu strávníka a sestavy.

Testy běží proti klonu LAB databáze, protože jde právě o to, co fake
service neumí prokázat: skutečné schéma, scope filtr a chování na reálných
datech.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import OrderServiceSettings
from jll.policy import Permission, SessionPolicy
from jll.read_models import CHIP_OUT_OF_SCOPE, DEFAULT_NORMS
from jll.read_service import DAY_COLUMNS, OrderReadService

pytestmark = pytest.mark.integration

PERMISSIONS = frozenset(
    {
        Permission.DINERS_VIEW,
        Permission.CHIPS_VIEW,
        Permission.ORDERS_VIEW,
        Permission.PICKUP_STATUS_VIEW,
        Permission.REPORTS_VIEW,
    }
)


def build_service(lab_database, categories: frozenset[str]) -> OrderReadService:
    return OrderReadService(
        lab_database.connect,
        OrderServiceSettings(
            environment="lab",
            db_host=lab_database.host,
            db_name=lab_database.name,
            expected_system_identifier=lab_database.system_identifier,
            business_timezone="Europe/Prague",
        ),
        SessionPolicy("integration", categories, PERMISSIONS),
    )


def two_categories(connection) -> tuple[str, str]:
    rows = connection.execute(
        """
        SELECT kategorie, count(*)
        FROM public.stravnik
        WHERE stav = 'A'
          AND COALESCE(deleted, false) = false
          AND hromadny IS NOT TRUE
        GROUP BY kategorie
        HAVING count(*) > 0
        ORDER BY count(*) DESC
        LIMIT 2
        """
    ).fetchall()
    assert len(rows) == 2
    return str(rows[0][0]).strip(), str(rows[1][0]).strip()


def assigned_chip(connection, category: str):
    return connection.execute(
        """
        SELECT btrim(c.cislo) AS code, c.stravnik
        FROM public.cipy AS c
        JOIN public.stravnik AS s ON s.evidcislo = c.stravnik
        WHERE s.kategorie = %s
          AND s.stav = 'A'
          AND COALESCE(s.deleted, false) = false
          AND s.hromadny IS NOT TRUE
          AND c.stav = 'P'
        ORDER BY c.cislo
        LIMIT 1
        """,
        (category,),
    ).fetchone()


def cooking_flag(connection, day: date) -> bool:
    """True, pokud je den v `public.varnedny` označený jako varný."""

    row = connection.execute(
        f"""
        SELECT bool_or(btrim({DAY_COLUMNS[day.day - 1]}) = 'A')
        FROM public.varnedny
        WHERE rok = %s AND mesic = %s
        """,
        (day.year, day.month),
    ).fetchone()
    return bool(row is not None and row[0])


def test_identify_chip_returns_owner_only_inside_scope(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, forbidden = two_categories(connection)
        mine = assigned_chip(connection, allowed)
        foreign = assigned_chip(connection, forbidden)
    if mine is None or foreign is None:
        pytest.skip("LAB data neobsahují přidělené čipy ve dvou kategoriích.")

    service = build_service(lab_database, frozenset({allowed}))

    identified = service.identify_chip(str(mine[0]))
    assert identified.exists
    assert identified.owner is not None
    assert identified.owner.evidcislo == int(mine[1])
    assert identified.owner.category == allowed
    assert identified.status_code == "P"
    assert identified.status_label == "Přidělen"
    assert identified.opens_card

    blocked = service.identify_chip(str(foreign[0]))
    assert blocked.exists
    assert blocked.owner is None
    assert blocked.owner_restricted
    assert not blocked.opens_card
    assert blocked.message == CHIP_OUT_OF_SCOPE


def test_identify_chip_accepts_reader_zero_padding(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, _forbidden = two_categories(connection)
        mine = assigned_chip(connection, allowed)
    if mine is None:
        pytest.skip("LAB data neobsahují přidělený čip ve scope.")
    code = str(mine[0])

    service = build_service(lab_database, frozenset({allowed}))
    stripped = code.lstrip("0") or code
    identified = service.identify_chip(stripped)

    assert identified.exists
    assert identified.owner is not None
    assert identified.owner.evidcislo == int(mine[1])


def test_identify_chip_reports_unknown_code_without_owner(
    lab_database,
) -> None:
    with lab_database.connect() as connection:
        allowed, _forbidden = two_categories(connection)
        free = connection.execute(
            """
            SELECT 1 FROM public.cipy
            WHERE lower(btrim(cislo)) = lower(%s)
            """,
            ("0000000000098765",),
        ).fetchone()
    if free is not None:
        pytest.skip("Zvolený syntetický kód v LAB datech existuje.")

    service = build_service(lab_database, frozenset({allowed}))
    result = service.identify_chip("0000000000098765")

    assert not result.exists
    assert result.owner is None
    assert not result.owner_restricted


def test_diner_profile_is_scope_safe_and_secret_free(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, forbidden = two_categories(connection)
        mine = connection.execute(
            """
            SELECT s.evidcislo, btrim(s.jmeno), btrim(s.kategorie),
                   NULLIF(upper(btrim(k.norma)), '')
            FROM public.stravnik AS s
            LEFT JOIN public.kategor AS k ON k.oznaceni = s.kategorie
            WHERE s.kategorie = %s AND s.stav = 'A'
              AND COALESCE(s.deleted, false) = false
              AND s.hromadny IS NOT TRUE
            ORDER BY s.evidcislo LIMIT 1
            """,
            (allowed,),
        ).fetchone()
        theirs = connection.execute(
            """
            SELECT evidcislo FROM public.stravnik
            WHERE kategorie = %s AND stav = 'A'
              AND COALESCE(deleted, false) = false
              AND hromadny IS NOT TRUE
            ORDER BY evidcislo LIMIT 1
            """,
            (forbidden,),
        ).fetchone()
    assert mine is not None and theirs is not None

    service = build_service(lab_database, frozenset({allowed}))
    profile = service.load_diner_profile(int(mine[0]))

    assert profile.evidcislo == int(mine[0])
    assert profile.name == str(mine[1]).strip()
    assert profile.category == allowed
    assert profile.category_norm == (mine[3] or None)
    assert profile.state_label == "Aktivní"
    assert profile.finance.minimum_balance <= 0
    assert profile.finance.headroom == (
        profile.finance.available_credit - profile.finance.minimum_balance
    )
    assert all(chip.code and chip.status_label for chip in profile.chips)

    with pytest.raises(OrderBusinessError) as blocked:
        service.load_diner_profile(int(theirs[0]))
    assert blocked.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE


def test_profile_credit_matches_order_preflight(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, _forbidden = two_categories(connection)
        mine = connection.execute(
            """
            SELECT evidcislo FROM public.stravnik
            WHERE kategorie = %s AND stav = 'A'
              AND COALESCE(deleted, false) = false
              AND hromadny IS NOT TRUE
            ORDER BY evidcislo LIMIT 1
            """,
            (allowed,),
        ).fetchone()
    assert mine is not None

    service = build_service(lab_database, frozenset({allowed}))
    evidcislo = int(mine[0])
    profile = service.load_diner_profile(evidcislo)
    day = service.load_diner_day(evidcislo, service.server_today())

    assert profile.finance.available_credit == day.diner.available_credit
    assert profile.chips == day.diner.chips


def test_next_cooking_day_comes_from_varnedny(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, _forbidden = two_categories(connection)
    service = build_service(lab_database, frozenset({allowed}))
    reference = service.server_today()
    found = service.next_cooking_day(reference)
    if found is None:
        pytest.skip("LAB kalendář varných dnů nemá další varný den.")

    assert found > reference
    # `varnedny.dNN` je varchar; varný den je označený hodnotou 'A'.
    day_after = reference + timedelta(days=1)
    with lab_database.connect() as connection:
        marked = cooking_flag(connection, found)
        skipped = cooking_flag(connection, day_after)
    assert marked is True
    if found > day_after:
        assert skipped is not True


def test_daily_report_stays_inside_scope_and_matches_summaries(
    lab_database,
) -> None:
    with lab_database.connect() as connection:
        allowed, forbidden = two_categories(connection)
    service = build_service(lab_database, frozenset({allowed}))
    target = service.server_today()
    report = service.load_daily_report(target)
    orders = service.load_order_report(target)

    assert report.target_date == target
    assert {row.category for row in report.diners} <= {allowed}
    assert {row.category for row in report.categories} <= {allowed}
    assert forbidden not in {row.category for row in report.diners}
    assert {
        (row.meal_type, row.menu): row.portions for row in report.menus
    } == {
        (row.meal_type, row.menu): row.portions for row in orders
    }
    assert report.total_portions == sum(row.portions for row in orders)
    assert len(report.diners) == report.total_orders
    assert sum(row.portions for row in report.norms) == sum(
        row.portions for row in report.menus
    )
    assert all(
        row.norm is None or row.norm in DEFAULT_NORMS for row in report.norms
    )
    for row in report.diners:
        assert row.menu >= 1
        assert row.meal_type
        assert row.name


def test_report_and_profile_require_their_permissions(lab_database) -> None:
    with lab_database.connect() as connection:
        allowed, _forbidden = two_categories(connection)
    service = OrderReadService(
        lab_database.connect,
        OrderServiceSettings(
            environment="lab",
            db_host=lab_database.host,
            db_name=lab_database.name,
            expected_system_identifier=lab_database.system_identifier,
            business_timezone="Europe/Prague",
        ),
        SessionPolicy(
            "integration",
            frozenset({allowed}),
            frozenset({Permission.ORDERS_VIEW}),
        ),
    )

    for call in (
        lambda: service.load_diner_profile(1),
        lambda: service.load_daily_report(date(2026, 9, 4)),
        lambda: service.identify_chip("0000000000098765"),
        lambda: service.next_cooking_day(date(2026, 9, 4)),
    ):
        with pytest.raises(OrderBusinessError) as blocked:
            call()
        assert blocked.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
