from __future__ import annotations

import threading
import time
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Callable

import psycopg
import pytest
from psycopg import sql

from jll.orders import (
    ErrorCode,
    OrderAction,
    OrderBusinessError,
    OrderCommand,
    OrderService,
    OrderServiceSettings,
)
from jll.orders.preflight import monthly_advisory_key
from jll.orders.repository import OrderRepository

from conftest import LabDatabase

TARGET = date(2026, 9, 10)
TARGET_2 = date(2026, 9, 11)
EVIDCISLO = 29
CATEGORY = "3"
OBED_A = "Oběd-A"
OBED_B = "Oběd-B"
OBED_C = "Oběd-C"
OBED_D = "Oběd-D"
MIXED_WRITER_BLOCKER = (
    "Potvrzený produkční blocker: legacy core writer po čekání používá "
    "zastaralý měsíční stav a nesdílí JLL advisory/revalidation protokol."
)


def order(
    typstravy: str = OBED_A,
    *,
    action: OrderAction = OrderAction.MENU_ADD,
    menu: int = 1,
    target: date = TARGET,
    category: str = CATEGORY,
    evidcislo: int = EVIDCISLO,
) -> OrderCommand:
    return OrderCommand(
        action=action,
        evidcislo=evidcislo,
        datum=target,
        typstravy=typstravy,
        menu=menu,
        allowed_categories=frozenset({category}),
        actor="JLL-LAB",
        client_version="0.1.0",
    )


def service(
    database: LabDatabase,
    *,
    strict_config_lock: bool = True,
    lock_timeout_ms: int = 2_000,
    max_retries: int = 0,
) -> OrderService:
    return OrderService(
        lambda: database.connect(autocommit=True),
        OrderServiceSettings(
            environment="lab",
            db_host=database.host,
            db_name=database.name,
            expected_system_identifier=database.system_identifier,
            business_timezone="Europe/Prague",
            strict_config_lock=strict_config_lock,
            lock_timeout_ms=lock_timeout_ms,
            statement_timeout_ms=15_000,
            max_retries=max_retries,
        ),
        scope_provider=lambda _command: frozenset({CATEGORY}),
    )


def day_column(target: date) -> sql.Identifier:
    return sql.Identifier(f"d{target.day:02d}")


def state(database: LabDatabase, typstravy: str, target: date = TARGET) -> str:
    with database.connect() as connection:
        row = connection.execute(
            sql.SQL(
                """
                SELECT {day}
                FROM public.prihlas
                WHERE stravnik = %s
                  AND typsluzby = %s
                  AND rok = %s
                  AND mesic = %s
                  AND poradiprihl = 1
                """
            ).format(day=day_column(target)),
            (EVIDCISLO, typstravy, target.year, target.month),
        ).fetchone()
    assert row is not None
    return str(row[0])


def set_state(
    database: LabDatabase,
    value: str,
    *,
    typstravy: str = OBED_A,
    target: date = TARGET,
) -> None:
    with database.connect() as connection:
        connection.execute(
            sql.SQL(
                """
                UPDATE public.prihlas
                SET {day} = %s
                WHERE stravnik = %s
                  AND typsluzby = %s
                  AND rok = %s
                  AND mesic = %s
                  AND poradiprihl = 1
                """
            ).format(day=day_column(target)),
            (value, EVIDCISLO, typstravy, target.year, target.month),
        )


def setup_order(
    database: LabDatabase,
    *,
    typstravy: str = OBED_A,
    menu: int = 1,
    target: date = TARGET,
) -> None:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT public.objednavka_plus(%s, %s, %s, %s, %s, %s)
            """,
            (
                target.year,
                target.month,
                target.day,
                str(menu),
                EVIDCISLO,
                typstravy,
            ),
        ).fetchone()
        assert row is not None
    assert state(database, typstravy, target) == str(menu)


def set_credit(database: LabDatabase, amount: Decimal) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE public.stravnik
            SET preplatekmm = %s,
                platittm = 0,
                platitpm = 0,
                platbatm = 0,
                platbabm = 0
            WHERE evidcislo = %s
            """,
            (amount, EVIDCISLO),
        )


def financial_state(database: LabDatabase) -> tuple[Decimal, Decimal, int]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT
                COALESCE(platittm, 0) + COALESCE(platitpm, 0),
                (
                    SELECT COALESCE(SUM(castka), 0)
                    FROM public.penden
                    WHERE evidcislo = s.evidcislo
                      AND rok = %s
                      AND mesic = %s
                      AND typ = 'R'
                ),
                (
                    SELECT COUNT(*)
                    FROM public.udalosti
                    WHERE stravnik = s.evidcislo
                      AND datumobj = %s
                      AND udalost = 'Přihláška'
                      AND typ = 'P'
                )
            FROM public.stravnik AS s
            WHERE evidcislo = %s
            """,
            (TARGET.year, TARGET.month, TARGET, EVIDCISLO),
        ).fetchone()
    assert row is not None
    return Decimal(row[0]), Decimal(row[1]), int(row[2])


def setup_menu_two(database: LabDatabase, price: Decimal) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE public.parametry
            SET hodnota = '1'
            WHERE sekce = 'BACKUP' AND parametr = 'PouzivatCenik'
            """
        )
        connection.execute(
            """
            UPDATE public.sazby
            SET pocetmenu = 2
            WHERE kategorie = %s
              AND typstravy = %s
              AND platnostod <= %s
              AND platnostdo >= %s
            """,
            (CATEGORY, OBED_A, TARGET, TARGET),
        )
        connection.execute(
            """
            INSERT INTO public.cenik (
                rok, mesic, den, datum, kod_stravy, menu, slozka,
                id_receptury, povinna, kategorie, limit_, sazba, dotace,
                mzdovr, ostatr, fksp, sazbadph, user1, user2, user3,
                user4, user5, updated_dt
            )
            SELECT
                rok, mesic, den, datum, kod_stravy, 2, slozka,
                id_receptury, povinna, kategorie, limit_, %s, dotace,
                mzdovr, ostatr, fksp, sazbadph, user1, user2, user3,
                user4, user5, clock_timestamp()
            FROM public.cenik
            WHERE rok = %s
              AND mesic = %s
              AND den = %s
              AND kategorie = %s
              AND kod_stravy = (
                  SELECT kod FROM public.typstrav WHERE typstravy = %s
              )
              AND menu = 1
            ON CONFLICT DO NOTHING
            """,
            (
                price,
                TARGET.year,
                TARGET.month,
                TARGET.day,
                CATEGORY,
                OBED_A,
            ),
        )
        connection.execute(
            """
            INSERT INTO public.jidelnicek (
                datum, jazyk, typstravy, idmenustravy, idreceptury,
                idjidelnicku, nazev, maxpocetporci, prihlaseno, poznamka,
                cislojidelnicku, zverejneny, updated_dt
            )
            SELECT
                j.datum, j.jazyk, j.typstravy, 44, j.idreceptury,
                j.idjidelnicku, 'LAB Menu 2', j.maxpocetporci,
                j.prihlaseno, j.poznamka, j.cislojidelnicku, true,
                clock_timestamp()
            FROM public.jidelnicek AS j
            JOIN public.menustravy AS m ON m.id = j.idmenustravy
            JOIN public.typstrj AS t ON t.id = m.idtypstrj
            WHERE j.datum = %s
              AND j.typstravy = %s
              AND j.jazyk = 'česky'
              AND j.cislojidelnicku = 1
              AND t.oznaceni = '1'
            ORDER BY m.caststravy, m.id
            LIMIT 1
            ON CONFLICT DO NOTHING
            """,
            (TARGET, OBED_A),
        )


def duplicate_prihlas(database: LabDatabase) -> None:
    with database.connect() as connection:
        columns = [
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'prihlas'
                ORDER BY ordinal_position
                """
            ).fetchall()
        ]
        expressions = []
        for column in columns:
            if column == "poradiprihl":
                expressions.append(sql.Literal(2))
            elif column == "id":
                expressions.append(
                    sql.SQL("(SELECT max(id) + 1 FROM public.prihlas)")
                )
            else:
                expressions.append(sql.Identifier(column))
        query = sql.SQL(
            """
            INSERT INTO public.prihlas ({columns})
            SELECT {expressions}
            FROM public.prihlas
            WHERE stravnik = %s
              AND typsluzby = %s
              AND rok = %s
              AND mesic = %s
              AND poradiprihl = 1
            """
        ).format(
            columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
            expressions=sql.SQL(", ").join(expressions),
        )
        connection.execute(
            query,
            (EVIDCISLO, OBED_A, TARGET.year, TARGET.month),
        )


def assert_error(code: ErrorCode, callable_: Any) -> OrderBusinessError:
    with pytest.raises(OrderBusinessError) as caught:
        callable_()
    assert caught.value.code is code
    return caught.value


def order_row_snapshot(
    database: LabDatabase,
    typstravy: str = OBED_A,
) -> tuple[str, str, Decimal, int, Decimal, Decimal, int]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT
                p.d10,
                p.d11,
                p.cena,
                p.pocet,
                COALESCE(s.platittm, 0) + COALESCE(s.platitpm, 0),
                (
                    SELECT COALESCE(SUM(x.castka), 0)
                    FROM public.penden AS x
                    WHERE x.evidcislo = s.evidcislo
                      AND x.rok = 2026
                      AND x.mesic = 9
                      AND x.typ = 'R'
                      AND x.typstravy = p.typsluzby
                ),
                (
                    SELECT COUNT(*)
                    FROM public.penden AS x
                    WHERE x.evidcislo = s.evidcislo
                      AND x.rok = 2026
                      AND x.mesic = 9
                      AND x.typ = 'R'
                      AND x.typstravy = p.typsluzby
                )
            FROM public.prihlas AS p
            JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
            WHERE p.stravnik = %s
              AND p.typsluzby = %s
              AND p.rok = 2026
              AND p.mesic = 9
              AND p.poradiprihl = 1
            """,
            (EVIDCISLO, typstravy),
        ).fetchone()
    assert row is not None
    return (
        str(row[0]),
        str(row[1]),
        Decimal(row[2]),
        int(row[3]),
        Decimal(row[4]),
        Decimal(row[5]),
        int(row[6]),
    )


def menu_price(
    database: LabDatabase,
    typstravy: str,
    target: date,
    menu: int = 1,
) -> Decimal:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT cena, ok
            FROM public.getcenamenuden(%s, %s, %s, %s, %s, %s)
            """,
            (
                typstravy,
                CATEGORY,
                target.year,
                target.month,
                target.day,
                menu,
            ),
        ).fetchone()
    assert row is not None and row[1] is True
    return Decimal(str(row[0]))


def run_mixed_writer_interleaving(
    database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
    jll_command: OrderCommand,
    legacy_write: Callable[[psycopg.Connection[Any]], Any],
) -> tuple[object, object]:
    rows_locked = threading.Event()
    release_jll = threading.Event()
    legacy_started = threading.Event()
    pause_guard = threading.Lock()
    paused = False
    original = OrderRepository.lock_order_rows

    def paused_order_lock(
        repository: OrderRepository,
        command: OrderCommand,
        meal_types: Any,
    ) -> Any:
        nonlocal paused
        result = original(repository, command, meal_types)
        with pause_guard:
            should_pause = not paused
            paused = True
        if should_pause:
            pid_row = repository.connection.execute(
                "SELECT pg_backend_pid()"
            ).fetchone()
            assert pid_row is not None
            jll_pid.append(int(pid_row[0]))
            rows_locked.set()
            assert release_jll.wait(timeout=15)
        return result

    monkeypatch.setattr(OrderRepository, "lock_order_rows", paused_order_lock)
    jll_result: list[object] = []
    legacy_result: list[object] = []
    jll_pid: list[int] = []
    legacy_pid: list[int] = []

    def execute_jll() -> None:
        try:
            jll_result.append(
                service(database, lock_timeout_ms=10_000).execute(jll_command)
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            jll_result.append(exc)

    def execute_legacy() -> None:
        try:
            with database.connect(autocommit=False) as connection:
                pid_row = connection.execute(
                    "SELECT pg_backend_pid()"
                ).fetchone()
                assert pid_row is not None
                legacy_pid.append(int(pid_row[0]))
                legacy_started.set()
                legacy_result.append(legacy_write(connection))
                connection.commit()
        except Exception as exc:  # pragma: no cover - diagnostic capture
            legacy_result.append(exc)

    jll_thread = threading.Thread(target=execute_jll)
    jll_thread.start()
    assert rows_locked.wait(timeout=15)

    legacy_thread = threading.Thread(target=execute_legacy)
    legacy_thread.start()
    assert legacy_started.wait(timeout=10)

    deadline = time.monotonic() + 10
    observed_lock_wait = False
    try:
        while time.monotonic() < deadline:
            with database.connect() as observer:
                wait_row = observer.execute(
                    """
                    SELECT
                        wait_event_type,
                        %s = ANY(pg_blocking_pids(pid)) AS blocked_by_jll,
                        NOT EXISTS (
                            SELECT 1
                            FROM pg_locks
                            WHERE pid = %s
                              AND locktype = 'advisory'
                              AND granted
                        ) AS has_no_advisory_lock
                    FROM pg_stat_activity
                    WHERE pid = %s
                    """,
                    (jll_pid[0], legacy_pid[0], legacy_pid[0]),
                ).fetchone()
            if wait_row and wait_row == ("Lock", True, True):
                observed_lock_wait = True
                break
            time.sleep(0.02)
        assert observed_lock_wait, (
            "Legacy writer nebyl prokazatelně blokován row lockem."
        )
    finally:
        release_jll.set()

    jll_thread.join(timeout=30)
    legacy_thread.join(timeout=30)
    assert not jll_thread.is_alive()
    assert not legacy_thread.is_alive()
    assert len(jll_result) == 1
    assert len(legacy_result) == 1
    return jll_result[0], legacy_result[0]


@pytest.mark.integration
@pytest.mark.parametrize("initial", ["N", "S"])
def test_add_n_or_s_to_menu(
    lab_database: LabDatabase,
    initial: str,
) -> None:
    set_state(lab_database, initial)
    before = financial_state(lab_database)

    result = service(lab_database).execute(order())

    assert state(lab_database, OBED_A) == "1"
    after = financial_state(lab_database)
    assert after[0] - before[0] == Decimal("88")
    assert after[1] - before[1] == Decimal("-88")
    assert after[2] - before[2] == 1
    assert result.success is True
    assert result.committed_transitions[0].before_state == initial
    assert result.metrics.config_lock_wait_ms >= 0
    assert str(result.committed_at.tzinfo) == "Europe/Prague"


@pytest.mark.integration
def test_business_timezone_overrides_different_connection_timezone(
    lab_database: LabDatabase,
) -> None:
    observed_initial_timezone: list[str] = []

    def utc_connection() -> psycopg.Connection[Any]:
        connection = lab_database.connect(autocommit=True)
        connection.execute("SET TimeZone = 'UTC'")
        row = connection.execute("SHOW TimeZone").fetchone()
        assert row is not None
        observed_initial_timezone.append(str(row[0]))
        return connection

    result = OrderService(
        utc_connection,
        OrderServiceSettings(
            environment="lab",
            db_host=lab_database.host,
            db_name=lab_database.name,
            expected_system_identifier=lab_database.system_identifier,
            business_timezone="Europe/Prague",
            strict_config_lock=True,
            lock_timeout_ms=2_000,
            statement_timeout_ms=15_000,
            max_retries=0,
        ),
        scope_provider=lambda _command: frozenset({CATEGORY}),
    ).execute(order())

    assert observed_initial_timezone == ["UTC"]
    assert str(result.committed_at.tzinfo) == "Europe/Prague"


@pytest.mark.integration
def test_delete_menu_to_n_and_credit_does_not_block(
    lab_database: LabDatabase,
) -> None:
    setup_order(lab_database)
    set_credit(lab_database, Decimal("-9999"))

    service(lab_database).execute(
        order(action=OrderAction.MENU_DELETE)
    )

    assert state(lab_database, OBED_A) == "N"


@pytest.mark.integration
def test_delete_noop_rolls_back_without_audit(lab_database: LabDatabase) -> None:
    set_state(lab_database, "N")
    before = financial_state(lab_database)

    assert_error(
        ErrorCode.ORDER_STATE_CONFLICT,
        lambda: service(lab_database).execute(
            order(action=OrderAction.MENU_DELETE)
        ),
    )

    assert financial_state(lab_database) == before


@pytest.mark.integration
def test_more_expensive_change_passes_with_credit(lab_database: LabDatabase) -> None:
    setup_menu_two(lab_database, Decimal("98"))
    setup_order(lab_database)
    set_credit(lab_database, Decimal("1000"))

    before = financial_state(lab_database)
    service(lab_database).execute(
        order(action=OrderAction.MENU_CHANGE, menu=2)
    )

    assert state(lab_database, OBED_A) == "2"
    assert financial_state(lab_database)[2] - before[2] == 1


@pytest.mark.integration
def test_more_expensive_change_fails_credit_and_keeps_old_menu(
    lab_database: LabDatabase,
) -> None:
    setup_menu_two(lab_database, Decimal("98"))
    setup_order(lab_database)
    set_credit(lab_database, Decimal("-195"))
    before = financial_state(lab_database)

    assert_error(
        ErrorCode.INSUFFICIENT_CREDIT,
        lambda: service(lab_database).execute(
            order(action=OrderAction.MENU_CHANGE, menu=2)
        ),
    )

    assert state(lab_database, OBED_A) == "1"
    assert financial_state(lab_database) == before


@pytest.mark.integration
def test_cheaper_change_is_allowed(lab_database: LabDatabase) -> None:
    setup_menu_two(lab_database, Decimal("78"))
    setup_order(lab_database)
    set_credit(lab_database, Decimal("-999"))

    service(lab_database).execute(
        order(action=OrderAction.MENU_CHANGE, menu=2)
    )

    assert state(lab_database, OBED_A) == "2"


@pytest.mark.integration
@pytest.mark.parametrize("target_type", [OBED_B, OBED_C, OBED_D])
def test_exclusive_variant_change_removes_a_and_adds_target(
    lab_database: LabDatabase,
    target_type: str,
) -> None:
    setup_order(lab_database, typstravy=OBED_A)
    before = financial_state(lab_database)

    service(lab_database).execute(order(target_type))

    assert state(lab_database, OBED_A) == "N"
    assert state(lab_database, target_type) == "1"
    other_states = [
        state(lab_database, name) for name in (OBED_A, OBED_B, OBED_C, OBED_D)
    ]
    assert sum(value.isdigit() for value in other_states) == 1
    assert financial_state(lab_database)[2] - before[2] == 2


@pytest.mark.integration
def test_multiple_poradiprihl_is_rejected(lab_database: LabDatabase) -> None:
    duplicate_prihlas(lab_database)

    assert_error(
        ErrorCode.AMBIGUOUS_ORDER_ROW,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
@pytest.mark.parametrize("remove_stravobv", [False, True])
def test_missing_prihlas_row_is_fail_closed(
    lab_database: LabDatabase,
    remove_stravobv: bool,
) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            """
            DELETE FROM public.prihlas
            WHERE stravnik = %s
              AND typsluzby = %s
              AND rok = %s
              AND mesic = %s
            """,
            (EVIDCISLO, OBED_A, TARGET.year, TARGET.month),
        )
        if remove_stravobv:
            connection.execute(
                """
                DELETE FROM public.stravobv
                WHERE kodstravnika = %s AND typstravy = %s
                """,
                (EVIDCISLO, OBED_A),
            )

    assert_error(
        ErrorCode.ORDER_ROW_MISSING,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
def test_core_return_one_without_change_is_detected(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(OrderRepository, "call_plus", lambda *_args: 1)

    assert_error(
        ErrorCode.POSTCONDITION_FAILED,
        lambda: service(lab_database).execute(order()),
    )

    assert state(lab_database, OBED_A) == "S"


@pytest.mark.integration
def test_minus_then_plus_failure_rolls_back_real_minus(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_menu_two(lab_database, Decimal("98"))
    setup_order(lab_database)
    before = financial_state(lab_database)
    monkeypatch.setattr(OrderRepository, "call_plus", lambda *_args: 1)

    assert_error(
        ErrorCode.POSTCONDITION_FAILED,
        lambda: service(lab_database).execute(
            order(action=OrderAction.MENU_CHANGE, menu=2)
        ),
    )

    assert state(lab_database, OBED_A) == "1"
    assert financial_state(lab_database) == before


@pytest.mark.integration
@pytest.mark.parametrize("failure_mode", ["false", "exception"])
def test_audit_failure_rolls_back_business_and_finance(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    setup_order(lab_database, typstravy=OBED_A)
    before = financial_state(lab_database)
    original = OrderRepository.insert_audit
    calls = 0

    def fail_second_audit(
        repository: OrderRepository,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(repository, *args, **kwargs)
        if failure_mode == "false":
            return False
        raise psycopg.errors.RaiseException("synthetic second audit failure")

    monkeypatch.setattr(OrderRepository, "insert_audit", fail_second_audit)

    if failure_mode == "false":
        assert_error(
            ErrorCode.AUDIT_FAILED,
            lambda: service(lab_database).execute(order(OBED_B)),
        )
    else:
        with pytest.raises(psycopg.errors.RaiseException):
            service(lab_database).execute(order(OBED_B))

    assert calls == 2
    assert state(lab_database, OBED_A) == "1"
    assert state(lab_database, OBED_B) == "S"
    assert financial_state(lab_database) == before


@pytest.mark.integration
def test_price_null_is_rejected(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            """
            UPDATE public.cenik AS c
            SET sazba = NULL
            FROM public.typstrav AS t
            WHERE t.kod = c.kod_stravy
              AND t.typstravy = %s
              AND c.kategorie = %s
              AND c.rok = %s
              AND c.mesic = %s
              AND c.den = %s
              AND c.menu = 1
            """,
            (OBED_A, CATEGORY, TARGET.year, TARGET.month, TARGET.day),
        )

    assert_error(
        ErrorCode.PRICE_INVALID,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
def test_price_path_mismatch_is_rejected(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            """
            UPDATE public.sazby
            SET sazba = sazba + 1
            WHERE kategorie = %s
              AND typstravy = %s
              AND platnostod <= %s
              AND platnostdo >= %s
            """,
            (CATEGORY, OBED_A, TARGET, TARGET),
        )

    assert_error(
        ErrorCode.PRICE_PATH_MISMATCH,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["missing", "null", "invalid"])
def test_invalid_use_pricelist_parameter_is_fail_closed(
    lab_database: LabDatabase,
    mode: str,
) -> None:
    with lab_database.connect() as connection:
        if mode == "missing":
            connection.execute(
                """
                DELETE FROM public.parametry
                WHERE sekce = 'BACKUP' AND parametr = 'PouzivatCenik'
                """
            )
        else:
            connection.execute(
                """
                UPDATE public.parametry
                SET hodnota = %s
                WHERE sekce = 'BACKUP' AND parametr = 'PouzivatCenik'
                """,
                (None if mode == "null" else "unexpected",),
            )

    assert_error(
        ErrorCode.PRICE_INVALID,
        lambda: service(lab_database).execute(order()),
    )
    assert state(lab_database, OBED_A) == "S"


@pytest.mark.integration
@pytest.mark.parametrize("column", ["cena", "pocet"])
def test_null_monthly_order_finance_is_fail_closed(
    lab_database: LabDatabase,
    column: str,
) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            sql.SQL(
                """
                UPDATE public.prihlas
                SET {} = NULL
                WHERE stravnik = %s
                  AND typsluzby = %s
                  AND rok = %s
                  AND mesic = %s
                  AND poradiprihl = 1
                """
            ).format(sql.Identifier(column)),
            (EVIDCISLO, OBED_A, TARGET.year, TARGET.month),
        )

    assert_error(
        ErrorCode.POSTCONDITION_FAILED,
        lambda: service(lab_database).execute(order()),
    )
    assert state(lab_database, OBED_A) == "S"


@pytest.mark.integration
def test_invalid_credit_is_rejected(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            "UPDATE public.stravnik SET preplatekmm = 'NaN'::numeric "
            "WHERE evidcislo = %s",
            (EVIDCISLO,),
        )

    assert_error(
        ErrorCode.CREDIT_DATA_INVALID,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
def test_unpublished_or_different_menu_is_rejected(
    lab_database: LabDatabase,
) -> None:
    setup_menu_two(lab_database, Decimal("98"))
    with lab_database.connect() as connection:
        connection.execute(
            """
            UPDATE public.jidelnicek
            SET zverejneny = false
            WHERE datum = %s AND typstravy = %s
            """,
            (TARGET, OBED_A),
        )
        connection.execute(
            """
            UPDATE public.jidelnicek AS j
            SET zverejneny = true
            FROM public.menustravy AS m, public.typstrj AS t
            WHERE m.id = j.idmenustravy
              AND t.id = m.idtypstrj
              AND j.datum = %s
              AND j.typstravy = %s
              AND t.oznaceni = '2'
            """,
            (TARGET, OBED_A),
        )

    assert_error(
        ErrorCode.MENU_NOT_AVAILABLE,
        lambda: service(lab_database).execute(order(menu=1)),
    )


@pytest.mark.integration
def test_nonzero_subsidy_pilot_guard(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        connection.execute(
            """
            UPDATE public.cenik AS c
            SET dotace = 1
            FROM public.typstrav AS t
            WHERE t.kod = c.kod_stravy
              AND t.typstravy = %s
              AND c.kategorie = %s
              AND c.rok = %s
              AND c.mesic = %s
              AND c.den = %s
              AND c.menu = 1
            """,
            (OBED_A, CATEGORY, TARGET.year, TARGET.month, TARGET.day),
        )

    assert_error(
        ErrorCode.POSTCONDITION_FAILED,
        lambda: service(lab_database).execute(order()),
    )


@pytest.mark.integration
def test_month_lock_serializes_two_different_days(
    lab_database: LabDatabase,
) -> None:
    commands = [order(target=TARGET), order(target=TARGET_2)]
    results: list[object] = []

    def execute(item: OrderCommand) -> None:
        try:
            results.append(service(lab_database, lock_timeout_ms=5_000).execute(item))
        except Exception as exc:  # pragma: no cover - diagnostic capture
            results.append(exc)

    threads = [threading.Thread(target=execute, args=(item,)) for item in commands]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert not any(isinstance(item, Exception) for item in results)
    assert state(lab_database, OBED_A, TARGET) == "1"
    assert state(lab_database, OBED_A, TARGET_2) == "1"


@pytest.mark.integration
def test_same_day_concurrency_has_one_success_and_one_safe_rejection(
    lab_database: LabDatabase,
) -> None:
    results: list[object] = []

    def execute() -> None:
        try:
            results.append(service(lab_database, lock_timeout_ms=5_000).execute(order()))
        except Exception as exc:  # pragma: no cover - diagnostic capture
            results.append(exc)

    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(not isinstance(item, Exception) for item in results) == 1
    errors = [item for item in results if isinstance(item, OrderBusinessError)]
    assert len(errors) == 1
    assert errors[0].code is ErrorCode.ORDER_STATE_CONFLICT
    assert state(lab_database, OBED_A) == "1"


@pytest.mark.integration
def test_concurrent_a_to_b_and_a_to_c_keep_exclusion_invariant(
    lab_database: LabDatabase,
) -> None:
    setup_order(lab_database, typstravy=OBED_A)
    results: list[object] = []

    def execute(target_type: str) -> None:
        try:
            results.append(
                service(lab_database, lock_timeout_ms=5_000).execute(
                    order(target_type)
                )
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            results.append(exc)

    threads = [
        threading.Thread(target=execute, args=(OBED_B,)),
        threading.Thread(target=execute, args=(OBED_C,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    assert not any(
        isinstance(item, Exception)
        and not isinstance(item, OrderBusinessError)
        for item in results
    )
    states = [state(lab_database, item) for item in (OBED_A, OBED_B, OBED_C, OBED_D)]
    assert sum(value.isdigit() for value in states) == 1


@pytest.mark.integration
def test_category_changed_while_waiting_is_revalidated(
    lab_database: LabDatabase,
) -> None:
    blocker = lab_database.connect(autocommit=False)
    blocker.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (monthly_advisory_key(EVIDCISLO, TARGET),),
    )
    result: list[object] = []

    def execute() -> None:
        try:
            result.append(
                service(lab_database, lock_timeout_ms=5_000).execute(order())
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            result.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    time.sleep(0.2)
    blocker.execute(
        "UPDATE public.stravnik SET kategorie = '2' WHERE evidcislo = %s",
        (EVIDCISLO,),
    )
    blocker.commit()
    blocker.close()
    thread.join(timeout=20)

    assert len(result) == 1
    assert isinstance(result[0], OrderBusinessError)
    assert result[0].code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE
    assert state(lab_database, OBED_A) == "S"


@pytest.mark.integration
def test_advisory_lock_timeout_is_fail_closed(lab_database: LabDatabase) -> None:
    blocker = lab_database.connect(autocommit=False)
    blocker.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (monthly_advisory_key(EVIDCISLO, TARGET),),
    )
    try:
        assert_error(
            ErrorCode.CONCURRENT_MODIFICATION,
            lambda: service(
                lab_database,
                lock_timeout_ms=150,
                max_retries=0,
            ).execute(order()),
        )
    finally:
        blocker.rollback()
        blocker.close()


@pytest.mark.integration
def test_real_postgres_deadlock_retries_in_new_transaction(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)
    original = OrderRepository.lock_diner
    first_attempt: set[int] = set()
    attempt_guard = threading.Lock()
    test_keys = {EVIDCISLO: 9_100_001, 35: 9_100_002}

    def deadlocking_lock(
        repository: OrderRepository,
        command: OrderCommand,
    ) -> Any:
        with attempt_guard:
            inject = command.evidcislo not in first_attempt
            first_attempt.add(command.evidcislo)
        if inject:
            own_key = test_keys[command.evidcislo]
            other_key = next(
                value for key, value in test_keys.items() if key != command.evidcislo
            )
            repository.connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (own_key,),
            )
            barrier.wait(timeout=10)
            repository.connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (other_key,),
            )
        return original(repository, command)

    monkeypatch.setattr(OrderRepository, "lock_diner", deadlocking_lock)
    results: list[object] = []

    def execute(command: OrderCommand) -> None:
        try:
            results.append(
                service(
                    lab_database,
                    lock_timeout_ms=5_000,
                    max_retries=1,
                ).execute(command)
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            results.append(exc)

    threads = [
        threading.Thread(target=execute, args=(order(evidcislo=EVIDCISLO),)),
        threading.Thread(target=execute, args=(order(evidcislo=35),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert not any(isinstance(item, Exception) for item in results)
    assert sorted(item.metrics.attempts for item in results) == [1, 2]


@pytest.mark.integration
def test_config_share_lock_blocks_admin_dml(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked = threading.Event()
    release = threading.Event()
    original = OrderRepository.lock_configuration

    def paused_lock(repository: OrderRepository) -> None:
        original(repository)
        locked.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr(OrderRepository, "lock_configuration", paused_lock)
    result: list[object] = []

    def execute() -> None:
        try:
            result.append(service(lab_database, lock_timeout_ms=5_000).execute(order()))
        except Exception as exc:  # pragma: no cover - diagnostic capture
            result.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    assert locked.wait(timeout=10)
    with lab_database.connect(autocommit=False) as admin:
        admin.execute("SET LOCAL lock_timeout = '150ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            admin.execute(
                "UPDATE public.signaly SET hodnota = hodnota "
                "WHERE nazev = 'UZAVERKA'"
            )
        admin.rollback()
    release.set()
    thread.join(timeout=20)

    assert len(result) == 1
    assert not isinstance(result[0], Exception)
    assert result[0].metrics.config_lock_wait_ms >= 150


@pytest.mark.integration
def test_strict_config_lock_without_permission_is_fail_closed(
    lab_database: LabDatabase,
) -> None:
    role = f"jll_limited_{uuid.uuid4().hex[:10]}"
    with lab_database.connect() as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role))
        )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(lab_database.name),
                sql.Identifier(role),
            )
        )
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(role)
            )
        )
        admin.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(role)
            )
        )
        admin.execute(
            sql.SQL("REVOKE ALL ON public.cenik FROM {}").format(
                sql.Identifier(role)
            )
        )

    limited = LabDatabase(
        lab_database.host,
        lab_database.port,
        role,
        lab_database.name,
        lab_database.system_identifier,
    )
    try:
        assert_error(
            ErrorCode.LAB_GUARD_FAILED,
            lambda: service(limited).execute(order()),
        )
    finally:
        with lab_database.connect() as admin:
            admin.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role))
            )
            admin.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
            )


@pytest.mark.integration
@pytest.mark.xfail(strict=True, reason=MIXED_WRITER_BLOCKER)
def test_mixed_writer_same_day_preserves_single_financial_transition(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = order_row_snapshot(lab_database)
    price = menu_price(lab_database, OBED_A, TARGET)

    def legacy_plus(connection: psycopg.Connection[Any]) -> Any:
        return connection.execute(
            "SELECT public.objednavka_plus(%s, %s, %s, %s, %s, %s)",
            (2026, 9, 10, "1", EVIDCISLO, OBED_A),
        ).fetchone()

    jll_result, legacy_result = run_mixed_writer_interleaving(
        lab_database,
        monkeypatch,
        order(),
        legacy_plus,
    )

    assert not isinstance(jll_result, Exception)
    assert not isinstance(legacy_result, Exception)
    after = order_row_snapshot(lab_database)
    assert after[0] == "1", after
    assert after[2] - before[2] == price, after
    assert after[3] - before[3] == 1, after
    assert after[4] - before[4] == price, after
    assert after[5] - before[5] == -price, after
    assert after[6] - before[6] == 1, after


@pytest.mark.integration
@pytest.mark.xfail(strict=True, reason=MIXED_WRITER_BLOCKER)
def test_mixed_writer_different_day_preserves_both_month_updates(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = order_row_snapshot(lab_database)
    first_price = menu_price(lab_database, OBED_A, TARGET)
    second_price = menu_price(lab_database, OBED_A, TARGET_2)
    total_price = first_price + second_price

    def legacy_plus(connection: psycopg.Connection[Any]) -> Any:
        return connection.execute(
            "SELECT public.objednavka_plus(%s, %s, %s, %s, %s, %s)",
            (2026, 9, 11, "1", EVIDCISLO, OBED_A),
        ).fetchone()

    jll_result, legacy_result = run_mixed_writer_interleaving(
        lab_database,
        monkeypatch,
        order(),
        legacy_plus,
    )

    assert not isinstance(jll_result, Exception)
    assert not isinstance(legacy_result, Exception)
    after = order_row_snapshot(lab_database)
    assert after[0:2] == ("1", "1"), after
    assert after[2] - before[2] == total_price, after
    assert after[3] - before[3] == 2, after
    assert after[4] - before[4] == total_price, after
    assert after[5] - before[5] == -total_price, after
    assert after[6] - before[6] == 2, after


@pytest.mark.integration
@pytest.mark.xfail(strict=True, reason=MIXED_WRITER_BLOCKER)
def test_mixed_writer_variant_change_keeps_only_one_exclusive_type(
    lab_database: LabDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_order(lab_database, typstravy=OBED_A)

    def legacy_a_to_c(connection: psycopg.Connection[Any]) -> Any:
        visible_states = {
            typstravy: current
            for typstravy, current in connection.execute(
                """
                SELECT typsluzby, d10
                FROM public.prihlas
                WHERE stravnik = %s
                  AND rok = 2026
                  AND mesic = 9
                  AND typsluzby = ANY(%s::varchar[])
                ORDER BY typsluzby
                """,
                (EVIDCISLO, [OBED_A, OBED_B, OBED_D]),
            ).fetchall()
        }
        removed = []
        for typstravy, current in visible_states.items():
            if str(current).isdigit():
                removed.append(
                    connection.execute(
                        "SELECT public.objednavka_minus(%s, %s, %s, %s, %s, %s)",
                        (2026, 9, 10, str(current), EVIDCISLO, typstravy),
                    ).fetchone()
                )
        added = connection.execute(
            "SELECT public.objednavka_plus(%s, %s, %s, %s, %s, %s)",
            (2026, 9, 10, "1", EVIDCISLO, OBED_C),
        ).fetchone()
        return removed, added

    jll_result, legacy_result = run_mixed_writer_interleaving(
        lab_database,
        monkeypatch,
        order(OBED_B),
        legacy_a_to_c,
    )

    assert not isinstance(jll_result, Exception)
    assert not isinstance(legacy_result, Exception)
    states = [
        state(lab_database, typstravy)
        for typstravy in (OBED_A, OBED_B, OBED_C, OBED_D)
    ]
    assert sum(value.isdigit() for value in states) == 1, states
