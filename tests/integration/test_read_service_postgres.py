from __future__ import annotations

from datetime import date

import pytest

from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import OrderServiceSettings
from jll.policy import Permission, SessionPolicy
from jll.read_service import OrderReadService

pytestmark = pytest.mark.integration


def test_scoped_read_service_search_detail_and_lab_guard(
    lab_database,
) -> None:
    with lab_database.connect() as connection:
        categories = connection.execute(
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
        assert len(categories) == 2
        allowed = str(categories[0][0])
        forbidden = str(categories[1][0])
        in_scope = connection.execute(
            """
            SELECT evidcislo
            FROM public.stravnik
            WHERE kategorie = %s AND stav = 'A'
              AND COALESCE(deleted, false) = false
              AND hromadny IS NOT TRUE
            ORDER BY evidcislo LIMIT 1
            """,
            (allowed,),
        ).fetchone()
        out_of_scope = connection.execute(
            """
            SELECT evidcislo
            FROM public.stravnik
            WHERE kategorie = %s AND stav = 'A'
              AND COALESCE(deleted, false) = false
              AND hromadny IS NOT TRUE
            ORDER BY evidcislo LIMIT 1
            """,
            (forbidden,),
        ).fetchone()
        assert in_scope is not None and out_of_scope is not None
        in_scope_chip = connection.execute(
            """
            SELECT c.cislo, c.stravnik
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
            (allowed,),
        ).fetchone()
        out_of_scope_chip = connection.execute(
            """
            SELECT c.cislo
            FROM public.cipy AS c
            JOIN public.stravnik AS s ON s.evidcislo = c.stravnik
            WHERE s.kategorie = %s
              AND s.stav = 'A'
              AND COALESCE(s.deleted, false) = false
              AND c.stav = 'P'
            ORDER BY c.cislo
            LIMIT 1
            """,
            (forbidden,),
        ).fetchone()
        connection.execute(
            "UPDATE public.stravnik SET cip = %s WHERE evidcislo = %s",
            ("LEGACYONLY000001", int(in_scope[0])),
        )

    settings = OrderServiceSettings(
        environment="lab",
        db_host=lab_database.host,
        db_name=lab_database.name,
        expected_system_identifier=lab_database.system_identifier,
        business_timezone="Europe/Prague",
    )
    service = OrderReadService(
        lab_database.connect,
        settings,
        SessionPolicy(
            "integration",
            frozenset({allowed}),
            frozenset(
                {
                    Permission.DINERS_VIEW,
                    Permission.CHIPS_VIEW,
                    Permission.ORDERS_VIEW,
                    Permission.PICKUP_STATUS_VIEW,
                    Permission.REPORTS_VIEW,
                }
            ),
        ),
    )

    identity = service.verify_lab()
    assert identity.database_name == lab_database.name
    first_page = service.list_diners()
    assert 0 < len(first_page) <= service.search_limit
    assert {item.category for item in first_page} == {allowed}
    found = service.search_diners(str(in_scope[0]))
    assert len(found) == 1
    assert found[0].category == allowed
    assert service.search_diners(str(out_of_scope[0])) == []
    if out_of_scope_chip is not None:
        assert service.search_diners(str(out_of_scope_chip[0]).strip()) == []
    if in_scope_chip is not None:
        by_chip = service.search_diners(str(in_scope_chip[0]).strip())
        assert [row.evidcislo for row in by_chip] == [int(in_scope_chip[1])]
    assert service.search_diners("legacyonly000001") == []
    target = service.server_today()
    view = service.load_diner_day(int(in_scope[0]), target)
    assert view.diner.category == allowed
    assert all(meal.meal_type for meal in view.meals)
    assert all(
        len(meal.month_states) in {0, 31}
        and all(1 <= day <= 31 for day in meal.cooking_days)
        for meal in view.meals
    )
    with lab_database.connect() as connection:
        expected_rows = connection.execute(
            """
            SELECT btrim(s.typstravy) AS typstravy, s.pocetmenu,
                   array_agg(menu ORDER BY menu) FILTER (WHERE price.ok)
                       AS priced_menus
            FROM public.sazby AS s
            CROSS JOIN LATERAL
                 generate_series(1, COALESCE(s.pocetmenu, 0)) AS menu
            LEFT JOIN LATERAL public.getcenamenuden(
                s.typstravy, s.kategorie, %s, %s, %s, menu
            ) AS price ON true
            WHERE s.kategorie = %s
              AND s.platnostod <= %s
              AND s.platnostdo >= %s
            GROUP BY s.typstravy, s.pocetmenu
            """,
            (
                target.year,
                target.month,
                target.day,
                allowed,
                target,
                target,
            ),
        ).fetchall()
    expected = {
        str(row[0]).strip(): (int(row[1] or 0), tuple(row[2] or ()))
        for row in expected_rows
    }
    capabilities = {
        item.meal_type: item.allowed_menus
        for item in service.get_allowed_menu_numbers(allowed, target)
    }
    for meal in view.meals:
        count, menus = expected.get(meal.meal_type, (0, ()))
        assert meal.allowed_menus == tuple(range(1, count + 1))
        assert capabilities[meal.meal_type] == meal.allowed_menus
        assert tuple(option.menu for option in meal.options) == menus
        assert all(option.menu <= count for option in meal.options)
    pickup = service.load_pickup_status(target)
    orders = service.load_order_report(target)
    assert {
        (row.meal_type, row.menu): row.ordered for row in pickup
    } == {
        (row.meal_type, row.menu): row.portions for row in orders
    }
    assert all(0 <= row.picked_up <= row.ordered for row in pickup)
    diner_report = service.load_diner_report()
    assert diner_report
    assert {row.category for row in diner_report} == {allowed}

    with pytest.raises(OrderBusinessError) as captured:
        service.load_diner_day(int(out_of_scope[0]), date(2026, 9, 3))
    assert captured.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE

    wrong_cluster = OrderReadService(
        lab_database.connect,
        OrderServiceSettings(
            environment="lab",
            db_host=lab_database.host,
            db_name=lab_database.name,
            expected_system_identifier="1",
            business_timezone="Europe/Prague",
        ),
        SessionPolicy(
            "integration",
            frozenset({allowed}),
            frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW}),
        ),
    )
    with pytest.raises(OrderBusinessError) as blocked:
        wrong_cluster.verify_lab()
    assert blocked.value.code is ErrorCode.LAB_GUARD_FAILED


def test_multi_menu_capability_is_read_from_sazby(lab_database) -> None:
    with lab_database.connect() as connection:
        multi = connection.execute(
            """
            SELECT btrim(s.kategorie), s.platnostod, s.pocetmenu
            FROM public.sazby AS s
            JOIN public.typstrav AS t ON t.typstravy = s.typstravy
            WHERE s.pocetmenu > 1
              AND t.typsluzby = 'strava'
              AND t.pouzivatpcbox = true
              AND COALESCE(t.nepouzivat, false) = false
            ORDER BY s.platnostod DESC, s.kategorie
            LIMIT 1
            """
        ).fetchone()
        if multi is None:
            pytest.skip("LAB data neobsahují kategorii s více než jedním menu.")
        category = str(multi[0])
        target = multi[1]
        expected_rows = connection.execute(
            """
            SELECT btrim(s.typstravy), s.pocetmenu
            FROM public.sazby AS s
            JOIN public.typstrav AS t ON t.typstravy = s.typstravy
            WHERE s.kategorie = %s
              AND s.platnostod <= %s
              AND s.platnostdo >= %s
              AND t.typsluzby = 'strava'
              AND t.pouzivatpcbox = true
              AND COALESCE(t.nepouzivat, false) = false
            """,
            (category, target, target),
        ).fetchall()

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
            frozenset({category}),
            frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW}),
        ),
    )

    capabilities = {
        item.meal_type: item.allowed_menus
        for item in service.get_allowed_menu_numbers(category, target)
    }
    expected = {
        str(row[0]).strip(): tuple(range(1, int(row[1] or 0) + 1))
        for row in expected_rows
    }
    assert expected
    assert any(len(menus) > 1 for menus in expected.values())
    for meal_type, menus in expected.items():
        assert capabilities[meal_type] == menus
    assert all(
        capabilities[meal_type] == ()
        for meal_type in capabilities
        if meal_type not in expected
    )

    with pytest.raises(OrderBusinessError) as blocked:
        service.get_allowed_menu_numbers("__mimo_rozsah__", target)
    assert blocked.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
