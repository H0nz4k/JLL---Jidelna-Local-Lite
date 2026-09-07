"""Integrační parity testy mise 0.2.1 + final hardening."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

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
from jll.serving_repository import ServingRepository
from jll.serving_service import ServingService
from jll.setup_probe import probe_lab_database
from jll.write_gates import (
    SERVING_WRITE_GATES,
    ContractStatus,
    require_proven,
)

from conftest import LabDatabase

TARGET = date(2026, 9, 10)
EVIDCISLO = 29
CATEGORY = "3"
PERIOD_CATEGORY_A = "1"
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


def _today_parts(database: LabDatabase) -> tuple[date, int, int, int]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT current_date::date,
                   extract(year from current_date)::int,
                   extract(month from current_date)::int,
                   extract(day from current_date)::int
            """
        ).fetchone()
    assert row is not None
    return date.fromisoformat(str(row[0])), int(row[1]), int(row[2]), int(row[3])


def _odebral_mark(
    database: LabDatabase,
    *,
    evidcislo: int,
    year: int,
    month: int,
    typstravy: str,
    poradiprihl: int,
    day: int,
) -> str:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(substr(odebral, %s, 1), '.')
            FROM public.odebral
            WHERE stravnik = %s AND rok = %s AND mesic = %s
              AND lower(btrim(typstravy)) = lower(%s)
              AND poradiprihl = %s
            """,
            (day, evidcislo, year, month, typstravy, poradiprihl),
        ).fetchone()
    return str(row[0]) if row is not None else "."


def _prepare_serving_target(
    database: LabDatabase,
) -> tuple[int, int, str, int, int, int, int, str]:
    """Vrátí (prihlaska_id, evidcislo, typstravy, poradiprihl, y, m, d, category)."""

    today, year, month, day = _today_parts(database)
    day_col = sql.Identifier(f"d{day:02d}")
    with database.connect() as connection:
        row = connection.execute(
            sql.SQL(
                """
                SELECT p.id, p.stravnik, btrim(p.typsluzby), p.poradiprihl,
                       btrim(s.kategorie)
                FROM public.prihlas AS p
                JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
                WHERE p.rok = %s AND p.mesic = %s
                  AND p.{day} ~ '^[1-9]$'
                  AND s.stav = 'A'
                  AND COALESCE(s.deleted, false) = false
                ORDER BY p.id
                LIMIT 1
                """
            ).format(day=day_col),
            (year, month),
        ).fetchone()
        assert row is not None, f"Žádná přihláška k výdeji pro {today}"
        prihlaska_id = int(row[0])
        evidcislo = int(row[1])
        typstravy = str(row[2])
        poradiprihl = int(row[3])
        category = str(row[4])
        dots = "." * 31
        cleared = dots[: day - 1] + "." + dots[day:]
        connection.execute(
            """
            INSERT INTO public.odebral
              (stravnik, rok, mesic, typstravy, poradiprihl, odebral)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (evidcislo, year, month, typstravy, poradiprihl, cleared),
        )
        connection.execute(
            """
            UPDATE public.odebral
            SET odebral = overlay(COALESCE(odebral, %s) placing '.' from %s for 1)
            WHERE stravnik = %s AND rok = %s AND mesic = %s
              AND lower(btrim(typstravy)) = lower(%s)
              AND poradiprihl = %s
            """,
            (cleared, day, evidcislo, year, month, typstravy, poradiprihl),
        )
    return prihlaska_id, evidcislo, typstravy, poradiprihl, year, month, day, category


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
    gate = SERVING_WRITE_GATES["record_pickup"]
    if gate.status is ContractStatus.PROVEN:
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

    with pytest.raises((OrderBusinessError, Exception)) as exc2:
        ServingService(lab_database.connect, policy, settings).record_pickup(
            9_999_999_999
        )
    if gate.status is ContractStatus.PROVEN:
        assert isinstance(exc2.value, OrderBusinessError)
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
    with pytest.raises((OrderBusinessError, Exception)) as exc3:
        ServingService(
            lab_database.connect,
            lambda: _policy(frozenset({"__NONE__"})),
            settings,
        ).record_pickup(int(row[0]))
    if gate.status is ContractStatus.PROVEN:
        assert isinstance(exc3.value, OrderBusinessError)
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


def test_legacy_user_role_clone_matches_ved(lab_database: LabDatabase) -> None:
    with lab_database.connect(autocommit=False) as connection:
        ved_row = connection.execute(
            """
            SELECT id, COALESCE(prava,''), COALESCE(prava1,''), typ,
                   COALESCE(is_admin,false), COALESCE(disabled,false)
            FROM public.uzivatel
            WHERE btrim(uzivatel) = 'VED'
            """
        ).fetchone()
        assert ved_row is not None
        ved_id = int(ved_row[0])
        ved_roles = [
            int(r[0])
            for r in connection.execute(
                """
                SELECT role_id FROM public.user_role
                WHERE user_id = %s ORDER BY role_id
                """,
                (ved_id,),
            ).fetchall()
        ]
        repo = LegacyUserRepository(connection)
        ved = repo.get_user("VED")
        assert ved is not None and ved.legacy_id == ved_id
        created = repo.create_user_from_template(
            code="JLLROLE1",
            display_name="Role Clone",
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
        new_row = connection.execute(
            """
            SELECT id, COALESCE(heslo,''), COALESCE(prava,''), COALESCE(prava1,''),
                   typ, COALESCE(is_admin,false), COALESCE(disabled,false)
            FROM public.uzivatel WHERE btrim(uzivatel)='JLLROLE1'
            """
        ).fetchone()
        assert new_row is not None
        new_id = int(new_row[0])
        assert new_id != ved_id
        assert new_row[1] == ""
        assert new_row[2] == ved_row[1]
        assert new_row[3] == ved_row[2]
        assert (new_row[4] or "INTERNI") == (ved.typ or "INTERNI")
        assert new_row[5] is False
        assert new_row[6] is False
        new_roles = [
            int(r[0])
            for r in connection.execute(
                """
                SELECT role_id FROM public.user_role
                WHERE user_id = %s ORDER BY role_id
                """,
                (new_id,),
            ).fetchall()
        ]
        assert new_roles == ved_roles
        connection.rollback()

    with lab_database.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM public.uzivatel WHERE uzivatel='JLLROLE1'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM public.user_role WHERE user_id = %s",
                (created.legacy_id,),
            ).fetchone()
            is None
        )


def test_period_category_order_write_uses_prihlas_price(
    lab_database: LabDatabase,
) -> None:
    """stravnik=B(3), prihlas=A(1) → finanční write používá cenu A (78 ≠ 88)."""

    with lab_database.connect() as connection:
        diner = connection.execute(
            "SELECT btrim(kategorie) FROM public.stravnik WHERE evidcislo=%s",
            (EVIDCISLO,),
        ).fetchone()
        assert diner is not None
        category_b = str(diner[0])
        assert category_b == CATEGORY
        price_a = connection.execute(
            """
            SELECT cena, ok FROM public.getcenamenuden(
              %s, %s, %s, %s, %s, 1
            )
            """,
            (OBED_A, PERIOD_CATEGORY_A, TARGET.year, TARGET.month, TARGET.day),
        ).fetchone()
        price_b = connection.execute(
            """
            SELECT cena, ok FROM public.getcenamenuden(
              %s, %s, %s, %s, %s, 1
            )
            """,
            (OBED_A, category_b, TARGET.year, TARGET.month, TARGET.day),
        ).fetchone()
        assert price_a is not None and price_a[1] is True
        assert price_b is not None and price_b[1] is True
        amount_a = Decimal(str(price_a[0]))
        amount_b = Decimal(str(price_b[0]))
        assert amount_a != amount_b
        connection.execute(
            """
            UPDATE public.prihlas
            SET kategorie = %s
            WHERE stravnik = %s AND rok = %s AND mesic = %s AND typsluzby = %s
            """,
            (PERIOD_CATEGORY_A, EVIDCISLO, TARGET.year, TARGET.month, OBED_A),
        )
        connection.execute(
            sql.SQL(
                """
                UPDATE public.prihlas SET {day} = 'N', cena = 0, pocet = 0
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
        connection.execute(
            """
            UPDATE public.stravnik
            SET preplatekmm = 500, platittm = 0, platitpm = 0,
                platbatm = 0, platbabm = 0
            WHERE evidcislo = %s
            """,
            (EVIDCISLO,),
        )
        before_credit = connection.execute(
            """
            SELECT COALESCE(preplatekmm,0)+COALESCE(platittm,0)+COALESCE(platitpm,0)
                 +COALESCE(platbatm,0)+COALESCE(platbabm,0)
            FROM public.stravnik WHERE evidcislo=%s
            """,
            (EVIDCISLO,),
        ).fetchone()
        assert before_credit is not None
        credit_before = Decimal(str(before_credit[0]))

    result = _order_service(lab_database, frozenset({category_b})).execute(
        OrderCommand(
            action=OrderAction.MENU_ADD,
            evidcislo=EVIDCISLO,
            datum=TARGET,
            typstravy=OBED_A,
            menu=1,
            allowed_categories=frozenset({category_b}),
            actor="JLL-LAB",
            client_version="0.2.1",
        )
    )
    assert result is not None

    with lab_database.connect() as connection:
        after = connection.execute(
            sql.SQL(
                """
                SELECT {day}, cena, pocet, btrim(kategorie)
                FROM public.prihlas
                WHERE stravnik=%s AND rok=%s AND mesic=%s AND typsluzby=%s
                """
            ).format(day=sql.Identifier(f"d{TARGET.day:02d}")),
            (EVIDCISLO, TARGET.year, TARGET.month, OBED_A),
        ).fetchone()
        assert after is not None
        assert str(after[0]) == "1"
        assert Decimal(str(after[1])) == amount_a
        assert Decimal(str(after[1])) != amount_b
        assert str(after[3]) == PERIOD_CATEGORY_A
        diner_after = connection.execute(
            "SELECT btrim(kategorie) FROM public.stravnik WHERE evidcislo=%s",
            (EVIDCISLO,),
        ).fetchone()
        assert diner_after is not None
        assert str(diner_after[0]) == category_b
        credit_after_row = connection.execute(
            """
            SELECT COALESCE(preplatekmm,0)+COALESCE(platittm,0)+COALESCE(platitpm,0)
                 +COALESCE(platbatm,0)+COALESCE(platbabm,0)
            FROM public.stravnik WHERE evidcislo=%s
            """,
            (EVIDCISLO,),
        ).fetchone()
        assert credit_after_row is not None
        credit_after = Decimal(str(credit_after_row[0]))
        # Součet kreditních sloupců se po přihlášce posune o cenu A (± podle znaménka).
        moved = abs(credit_after - credit_before)
        assert moved == amount_a
        assert moved != amount_b
        audit = connection.execute(
            """
            SELECT count(*) FROM public.udalosti
            WHERE stravnik = %s AND datumobj = %s AND typ = 'P'
            """,
            (EVIDCISLO, TARGET),
        ).fetchone()
        assert audit is not None and int(audit[0]) >= 1


def test_serving_record_pickup_real_db_write(lab_database: LabDatabase) -> None:
    if SERVING_WRITE_GATES["record_pickup"].status is not ContractStatus.PROVEN:
        pytest.skip("Serving write gate není PROVEN.")
    (
        prihlaska_id,
        evidcislo,
        typstravy,
        poradiprihl,
        year,
        month,
        day,
        category,
    ) = _prepare_serving_target(lab_database)
    before = _odebral_mark(
        lab_database,
        evidcislo=evidcislo,
        year=year,
        month=month,
        typstravy=typstravy,
        poradiprihl=poradiprihl,
        day=day,
    )
    assert before != "O"
    service = ServingService(
        lab_database.connect,
        lambda: _policy(frozenset({category})),
        _settings(lab_database),
    )
    ok = service.record_pickup(prihlaska_id, evidcislo=evidcislo)
    assert ok is True
    after = _odebral_mark(
        lab_database,
        evidcislo=evidcislo,
        year=year,
        month=month,
        typstravy=typstravy,
        poradiprihl=poradiprihl,
        day=day,
    )
    assert after == "O"


def test_serving_duplicate_pickup_contract(lab_database: LabDatabase) -> None:
    if SERVING_WRITE_GATES["record_pickup"].status is not ContractStatus.PROVEN:
        pytest.skip("Serving write gate není PROVEN.")
    (
        prihlaska_id,
        evidcislo,
        typstravy,
        poradiprihl,
        year,
        month,
        day,
        category,
    ) = _prepare_serving_target(lab_database)
    service = ServingService(
        lab_database.connect,
        lambda: _policy(frozenset({category})),
        _settings(lab_database),
    )
    first = service.record_pickup(prihlaska_id, evidcislo=evidcislo)
    second = service.record_pickup(prihlaska_id, evidcislo=evidcislo)
    assert first is True
    assert second is True
    assert (
        _odebral_mark(
            lab_database,
            evidcislo=evidcislo,
            year=year,
            month=month,
            typstravy=typstravy,
            poradiprihl=poradiprihl,
            day=day,
        )
        == "O"
    )


def test_serving_concurrent_two_stations(lab_database: LabDatabase) -> None:
    if SERVING_WRITE_GATES["record_pickup"].status is not ContractStatus.PROVEN:
        pytest.skip("Serving write gate není PROVEN.")
    (
        prihlaska_id,
        evidcislo,
        typstravy,
        poradiprihl,
        year,
        month,
        day,
        category,
    ) = _prepare_serving_target(lab_database)
    results: list[object] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            svc = ServingService(
                lab_database.connect,
                lambda: _policy(frozenset({category})),
                _settings(lab_database),
            )
            results.append(svc.record_pickup(prihlaska_id, evidcislo=evidcislo))
        except Exception as exc:  # pragma: no cover - characterization
            results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2
    assert results.count(True) == 2
    assert (
        _odebral_mark(
            lab_database,
            evidcislo=evidcislo,
            year=year,
            month=month,
            typstravy=typstravy,
            poradiprihl=poradiprihl,
            day=day,
        )
        == "O"
    )


def test_serving_zapis_odber_rollback(lab_database: LabDatabase) -> None:
    (
        prihlaska_id,
        evidcislo,
        typstravy,
        poradiprihl,
        year,
        month,
        day,
        _category,
    ) = _prepare_serving_target(lab_database)
    before = _odebral_mark(
        lab_database,
        evidcislo=evidcislo,
        year=year,
        month=month,
        typstravy=typstravy,
        poradiprihl=poradiprihl,
        day=day,
    )
    with pytest.raises(RuntimeError, match="forced-rollback"):
        with lab_database.connect(autocommit=False) as connection:
            with connection.transaction():
                ok = ServingRepository(connection).zapis_odber(prihlaska_id)
                assert ok is True
                raise RuntimeError("forced-rollback")
    after = _odebral_mark(
        lab_database,
        evidcislo=evidcislo,
        year=year,
        month=month,
        typstravy=typstravy,
        poradiprihl=poradiprihl,
        day=day,
    )
    assert after == before
