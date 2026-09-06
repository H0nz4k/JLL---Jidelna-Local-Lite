"""Integrační parity testy mise 0.2.1."""

from __future__ import annotations

from datetime import date

import pytest
from psycopg import sql

from jll.legacy_users import LegacyUserRepository, LegacyUserRow
from jll.orders import (
    ErrorCode,
    OrderAction,
    OrderBusinessError,
    OrderCommand,
    OrderService,
    OrderServiceSettings,
)
from jll.policy import Permission, SessionPolicy
from jll.read_service import OrderReadService
from jll.serving_service import ServingService
from jll.setup_probe import probe_lab_database
from jll.write_gates import SERVING_WRITE_GATES, require_proven

from conftest import LabDatabase

TARGET = date(2026, 9, 10)
EVIDCISLO = 29
CATEGORY = "3"
OBED_A = "Oběd-A"

pytestmark = pytest.mark.integration


def _settings(database: LabDatabase) -> OrderServiceSettings:
    return OrderServiceSettings(
        environment="lab",
        db_host=database.host,
        db_name=database.name,
        expected_system_identifier=database.system_identifier,
        business_timezone="Europe/Prague",
        lock_timeout_ms=2_000,
        statement_timeout_ms=15_000,
        max_retries=0,
    )


def _policy(categories: frozenset[str]) -> SessionPolicy:
    return SessionPolicy(
        user_identity="LAB",
        allowed_categories=categories,
        permissions=frozenset(Permission),
        bypass_order_deadlines=True,
    )


def _order_service(database: LabDatabase, categories: frozenset[str]) -> OrderService:
    return OrderService(
        lambda: database.connect(autocommit=True),
        _settings(database),
        scope_provider=lambda _command: categories,
    )


def test_period_category_profile_scope_and_report_grouping(
    lab_database: LabDatabase,
) -> None:
    with lab_database.connect() as connection:
        diner = connection.execute(
            "SELECT kategorie FROM public.stravnik WHERE evidcislo = %s",
            (EVIDCISLO,),
        ).fetchone()
        assert diner is not None
        current = str(diner[0]).strip()
        alt = connection.execute(
            """
            SELECT btrim(oznaceni) FROM public.kategor
            WHERE btrim(oznaceni) <> %s
            ORDER BY oznaceni LIMIT 1
            """,
            (current,),
        ).fetchone()
        assert alt is not None
        period = str(alt[0])
        connection.execute(
            """
            UPDATE public.prihlas
            SET kategorie = %s
            WHERE stravnik = %s AND rok = %s AND mesic = %s AND typsluzby = %s
            """,
            (period, EVIDCISLO, TARGET.year, TARGET.month, OBED_A),
        )
        connection.execute(
            sql.SQL(
                """
                UPDATE public.prihlas SET {day} = '1'
                WHERE stravnik = %s AND rok = %s AND mesic = %s AND typsluzby = %s
                """
            ).format(day=sql.Identifier(f"d{TARGET.day:02d}")),
            (EVIDCISLO, TARGET.year, TARGET.month, OBED_A),
        )

    read = OrderReadService(
        lab_database.connect,
        _settings(lab_database),
        lambda: _policy(frozenset({current})),
    )
    profile = read.load_diner_profile(EVIDCISLO)
    assert profile.category == current

    report = read.load_daily_report(TARGET)
    named = [row for row in report.diners if row.evidcislo == EVIDCISLO]
    assert named
    assert all(row.category == period for row in named)

    # Scope zůstává na stravnik.kategorie — period samotná nestačí.
    out = OrderReadService(
        lab_database.connect,
        _settings(lab_database),
        lambda: _policy(frozenset({period})),
    )
    with pytest.raises(OrderBusinessError) as exc:
        out.load_diner_profile(EVIDCISLO)
    assert exc.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE


def test_menu_delete_after_unpublish_allows_delete_blocks_add(
    lab_database: LabDatabase,
) -> None:
    svc = _order_service(lab_database, frozenset({CATEGORY}))
    # zajisti čistý start
    with lab_database.connect() as connection:
        connection.execute(
            sql.SQL(
                """
                UPDATE public.prihlas SET {day} = 'N'
                WHERE stravnik = %s AND rok = %s AND mesic = %s AND typsluzby = %s
                """
            ).format(day=sql.Identifier(f"d{TARGET.day:02d}")),
            (EVIDCISLO, TARGET.year, TARGET.month, OBED_A),
        )
        connection.execute(
            """
            UPDATE public.jidelnicek SET zverejneny = true
            WHERE datum = %s AND typstravy = %s
            """,
            (TARGET, OBED_A),
        )

    svc.execute(
        OrderCommand(
            action=OrderAction.MENU_ADD,
            evidcislo=EVIDCISLO,
            datum=TARGET,
            typstravy=OBED_A,
            menu=1,
            allowed_categories=frozenset({CATEGORY}),
            actor="JLL-LAB",
            client_version="0.2.1",
        )
    )
    with lab_database.connect() as connection:
        connection.execute(
            """
            UPDATE public.jidelnicek SET zverejneny = false
            WHERE datum = %s AND typstravy = %s
            """,
            (TARGET, OBED_A),
        )

    svc.execute(
        OrderCommand(
            action=OrderAction.MENU_DELETE,
            evidcislo=EVIDCISLO,
            datum=TARGET,
            typstravy=OBED_A,
            menu=1,
            allowed_categories=frozenset({CATEGORY}),
            actor="JLL-LAB",
            client_version="0.2.1",
        )
    )
    with pytest.raises(OrderBusinessError) as exc:
        svc.execute(
            OrderCommand(
                action=OrderAction.MENU_ADD,
                evidcislo=EVIDCISLO,
                datum=TARGET,
                typstravy=OBED_A,
                menu=1,
                allowed_categories=frozenset({CATEGORY}),
                actor="JLL-LAB",
                client_version="0.2.1",
            )
        )
    assert exc.value.code is ErrorCode.MENU_NOT_AVAILABLE


def test_serving_lab_guard_and_out_of_scope(lab_database: LabDatabase) -> None:
    require_proven(SERVING_WRITE_GATES, "record_pickup")
    settings = _settings(lab_database)
    bad_settings = OrderServiceSettings(
        environment="lab",
        db_host=lab_database.host,
        db_name=lab_database.name,
        expected_system_identifier="9999999999999999999",
        business_timezone="Europe/Prague",
    )
    policy = lambda: _policy(frozenset({CATEGORY}))
    with pytest.raises(OrderBusinessError) as exc:
        ServingService(lab_database.connect, policy, bad_settings).record_pickup(1)
    assert exc.value.code is ErrorCode.LAB_GUARD_FAILED

    with pytest.raises(OrderBusinessError) as exc2:
        ServingService(lab_database.connect, policy, settings).record_pickup(
            9_999_999_999
        )
    assert exc2.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE

    with lab_database.connect() as connection:
        row = connection.execute(
            """
            SELECT p.id
            FROM public.prihlas AS p
            JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
            WHERE s.kategorie = %s AND s.stav = 'A'
            ORDER BY p.id LIMIT 1
            """,
            (CATEGORY,),
        ).fetchone()
    assert row is not None
    with pytest.raises(OrderBusinessError) as exc3:
        ServingService(
            lab_database.connect,
            lambda: _policy(frozenset({"__NONE__"})),
            settings,
        ).record_pickup(int(row[0]))
    assert exc3.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE


def test_legacy_user_clone_from_ved_rollback(lab_database: LabDatabase) -> None:
    with lab_database.connect(autocommit=False) as connection:
        repo = LegacyUserRepository(connection)
        ved = repo.get_user("VED")
        assert ved is not None and ved.legacy_id is not None
        created = repo.create_user_from_template(
            code="JLLT1",
            display_name="Test Operátor",
            template=LegacyUserRow(
                code=ved.code,
                display_name=ved.display_name,
                is_admin=False,
                typ=ved.typ or "INTERNI",
                disabled=False,
                prava=ved.prava,
                prava1=ved.prava1,
                has_password=False,
                legacy_id=ved.legacy_id,
            ),
        )
        assert created.legacy_id is not None
        assert created.legacy_id != ved.legacy_id
        assert created.has_password is False
        assert created.is_admin is False
        assert created.disabled is False
        second = repo.create_user_from_template(
            code="JLLT2",
            display_name="Druhý",
            template=LegacyUserRow(
                code=ved.code,
                display_name=ved.display_name,
                is_admin=False,
                typ=ved.typ or "INTERNI",
                disabled=False,
                prava=ved.prava,
                prava1=ved.prava1,
                has_password=False,
                legacy_id=ved.legacy_id,
            ),
        )
        assert second.legacy_id != created.legacy_id
        with pytest.raises(ValueError):
            repo.create_user_from_template(
                code="JLLT1",
                display_name="Dup",
                template=ved,
            )
        connection.rollback()

    with lab_database.connect() as connection:
        gone = connection.execute(
            "SELECT 1 FROM public.uzivatel WHERE uzivatel IN ('JLLT1','JLLT2')"
        ).fetchone()
        assert gone is None
        ved_after = LegacyUserRepository(connection).get_user("VED")
        assert ved_after is not None
        assert ved_after.legacy_id == ved.legacy_id


def test_setup_probe_includes_kategor_without_diners(
    lab_database: LabDatabase,
) -> None:
    with lab_database.connect() as connection:
        empty = connection.execute(
            """
            SELECT btrim(k.oznaceni)
            FROM public.kategor AS k
            WHERE NOT EXISTS (
              SELECT 1 FROM public.stravnik AS s
              WHERE btrim(s.kategorie) = btrim(k.oznaceni)
                AND s.stav = 'A'
                AND COALESCE(s.deleted, false) = false
            )
            ORDER BY k.oznaceni
            LIMIT 1
            """
        ).fetchone()
        assert empty is not None, "LAB template nemá kategorii bez aktivních strávníků"
        code = str(empty[0])

    probe = probe_lab_database(
        host=lab_database.host,
        port=lab_database.port,
        database=lab_database.name,
        user=lab_database.user,
        password="",
    )
    assert code in probe.categories
    # Ověření: stará DISTINCT-stravnik logika by tuto kategorii nenabídla.
    with lab_database.connect() as connection:
        occupied = {
            str(row[0]).strip()
            for row in connection.execute(
                """
                SELECT DISTINCT btrim(kategorie)
                FROM public.stravnik
                WHERE stav = 'A'
                  AND COALESCE(deleted, false) = false
                  AND kategorie IS NOT NULL
                """
            ).fetchall()
        }
    assert code not in occupied
