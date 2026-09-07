"""Integrační testy diner create/edit + chip lifecycle 0.3.0."""

from __future__ import annotations

import threading
from datetime import datetime

import pytest

from jll.chip_command_service import ChipCommandService
from jll.diner_models import (
    ChipCommand,
    CreateDinerCommand,
    EditDinerPersonalCommand,
)
from jll.diner_service import DinerService
from jll.orders import ErrorCode, OrderBusinessError, OrderServiceSettings
from jll.policy import Permission, SessionPolicy
from jll.write_gates import (
    CHIP_WRITE_GATES,
    DINER_WRITE_GATES,
    ContractStatus,
)

from conftest import LabDatabase

pytestmark = pytest.mark.integration

CATEGORY = "1JARO"
ACTOR = "LABTEST:VED"
VERSION = "0.3.1"


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


def _policy(categories: frozenset[str] | None = None) -> SessionPolicy:
    return SessionPolicy(
        user_identity="LAB",
        allowed_categories=categories or frozenset({CATEGORY}),
        permissions=frozenset(Permission),
        bypass_order_deadlines=True,
    )


def _diner_service(database: LabDatabase, categories: frozenset[str] | None = None) -> DinerService:
    return DinerService(
        database.connect,
        lambda: _policy(categories),
        _settings(database),
    )


def _chip_service(database: LabDatabase, categories: frozenset[str] | None = None) -> ChipCommandService:
    return ChipCommandService(
        database.connect,
        lambda: _policy(categories),
        _settings(database),
    )


def _cleanup_diner(database: LabDatabase, evidcislo: int) -> None:
    with database.connect() as connection:
        connection.execute("DELETE FROM public.udalosti WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.histcipu WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.prihlas WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.stravobv WHERE kodstravnika = %s", (evidcislo,))
        connection.execute("DELETE FROM public.odebral WHERE stravnik = %s", (evidcislo,))
        connection.execute(
            "UPDATE public.cipy SET stav='V', stravnik=0 WHERE stravnik = %s",
            (evidcislo,),
        )
        connection.execute("DELETE FROM public.stravnik WHERE evidcislo = %s", (evidcislo,))
        connection.commit()


def test_diner_create_real_db(lab_database: LabDatabase) -> None:
    assert DINER_WRITE_GATES["create"].status is ContractStatus.PROVEN
    service = _diner_service(lab_database)
    result = service.create(
        CreateDinerCommand(
            jmeno="JLLTEST CREATE NOVÁK",
            kategorie=CATEGORY,
            trida="9.A",
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        assert result.evidcislo > 0
        with lab_database.connect() as connection:
            row = connection.execute(
                """
                SELECT jmeno, kategorie, trida, stav, hromadny,
                       preplatekmm, zpusobplatby, pin
                FROM public.stravnik WHERE evidcislo = %s
                """,
                (result.evidcislo,),
            ).fetchone()
            assert row is not None
            assert str(row[0]).startswith("JLLTEST CREATE")
            assert str(row[1]) == CATEGORY
            assert str(row[2]) == "9.A"
            assert str(row[3]) == "A"
            assert row[4] is False
            assert float(row[5] or 0) == 0.0
            assert row[6]
            assert row[7]
            year, month = connection.execute(
                """
                SELECT
                  (SELECT hodnota::int FROM public.parametry
                   WHERE lower(btrim(sekce))=lower('BACKUP')
                     AND lower(btrim(parametr))=lower('TentoRok')),
                  (SELECT hodnota::int FROM public.parametry
                   WHERE lower(btrim(sekce))=lower('BACKUP')
                     AND lower(btrim(parametr))=lower('TentoMesic'))
                """
            ).fetchone()
            expected_types = {
                str(r[0])
                for r in connection.execute(
                    """
                    SELECT DISTINCT btrim(sa.typstravy)
                    FROM public.sazby AS sa
                    WHERE btrim(sa.kategorie) = %s
                      AND sa.platnostod <= make_date(%s, %s, 1)
                      AND sa.platnostdo >= make_date(%s, %s, 1) + 27
                    """,
                    (CATEGORY, year, month, year, month),
                ).fetchall()
            }
            actual_types = {
                str(r[0])
                for r in connection.execute(
                    """
                    SELECT btrim(typstravy) FROM public.stravobv
                    WHERE kodstravnika = %s
                    """,
                    (result.evidcislo,),
                ).fetchall()
            }
            assert actual_types == expected_types
            rozpis = connection.execute(
                """
                SELECT NULLIF(btrim(hodnota), '')
                FROM public.parametry
                WHERE lower(btrim(sekce)) = lower('BACKUP')
                  AND lower(btrim(parametr)) = lower(%s)
                """,
                (f"RozpisVytvoren{int(month):02d}",),
            ).fetchone()
            if rozpis and str(rozpis[0]).upper().startswith("A") and expected_types:
                prihlas = connection.execute(
                    """
                    SELECT count(*) FROM public.prihlas
                    WHERE stravnik = %s AND rok = %s AND mesic = %s
                    """,
                    (result.evidcislo, year, month),
                ).fetchone()
                assert int(prihlas[0]) >= 1
            audit = connection.execute(
                """
                SELECT count(*) FROM public.udalosti
                WHERE stravnik = %s AND udalost = 'Nový strávník'
                """,
                (result.evidcislo,),
            ).fetchone()
            assert int(audit[0]) >= 1
    finally:
        _cleanup_diner(lab_database, result.evidcislo)


def test_diner_create_out_of_scope_blocked(lab_database: LabDatabase) -> None:
    service = _diner_service(lab_database, frozenset({CATEGORY}))
    with pytest.raises(OrderBusinessError) as exc:
        service.create(
            CreateDinerCommand(
                jmeno="JLLTEST SCOPE",
                kategorie="NOPE",
                actor=ACTOR,
                client_version=VERSION,
            )
        )
    assert exc.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE


def test_diner_create_permission_denied(lab_database: LabDatabase) -> None:
    policy = SessionPolicy(
        user_identity="LAB",
        allowed_categories=frozenset({CATEGORY}),
        permissions=frozenset({Permission.DINERS_VIEW}),
        bypass_order_deadlines=True,
    )
    service = DinerService(
        lab_database.connect,
        lambda: policy,
        _settings(lab_database),
    )
    with pytest.raises(Exception):
        service.create(
            CreateDinerCommand(
                jmeno="JLLTEST PERM",
                kategorie=CATEGORY,
                actor=ACTOR,
                client_version=VERSION,
            )
        )


def test_diner_create_lab_guard(lab_database: LabDatabase) -> None:
    bad = OrderServiceSettings(
        environment="lab",
        db_host=lab_database.host,
        db_name=lab_database.name,
        expected_system_identifier="999999999999",
        business_timezone="Europe/Prague",
        lock_timeout_ms=2_000,
        statement_timeout_ms=15_000,
        max_retries=0,
    )
    service = DinerService(lab_database.connect, _policy, bad)
    with pytest.raises(OrderBusinessError) as exc:
        service.create(
            CreateDinerCommand(
                jmeno="JLLTEST GUARD",
                kategorie=CATEGORY,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
    assert exc.value.code is ErrorCode.LAB_GUARD_FAILED


def test_diner_create_concurrency(lab_database: LabDatabase) -> None:
    results: list[int] = []
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            service = _diner_service(lab_database)
            result = service.create(
                CreateDinerCommand(
                    jmeno=f"JLLTEST CONC {idx}",
                    kategorie=CATEGORY,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
            results.append(result.evidcislo)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    for evid in results:
        _cleanup_diner(lab_database, evid)
    assert not errors, errors
    assert len(results) == 2
    assert len(set(results)) == 2


def test_diner_create_rollback_after_inserts(lab_database: LabDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """Po skutečných insertech selže audit → transakce vrátí vše."""

    from jll import diner_repository

    original = diner_repository.DinerRepository.insert_audit

    def _fail_audit(self, *args, **kwargs):  # noqa: ANN001
        assert self.count_stravobv  # repo je živé
        # ověř, že strávník už v transakci existuje
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.stravnik WHERE jmeno LIKE 'JLLTEST REALROLL%'")
            assert int(cursor.fetchone()[0]) >= 1
        return False

    monkeypatch.setattr(diner_repository.DinerRepository, "insert_audit", _fail_audit)
    service = _diner_service(lab_database)
    with lab_database.connect() as connection:
        before_s = connection.execute(
            "SELECT count(*) FROM public.stravnik WHERE jmeno LIKE 'JLLTEST REALROLL%'"
        ).fetchone()[0]
        before_u = connection.execute(
            "SELECT count(*) FROM public.udalosti WHERE udalost = 'Nový strávník'"
        ).fetchone()[0]
    with pytest.raises(OrderBusinessError) as exc:
        service.create(
            CreateDinerCommand(
                jmeno="JLLTEST REALROLL",
                kategorie=CATEGORY,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
    assert exc.value.code is ErrorCode.AUDIT_FAILED
    with lab_database.connect() as connection:
        after_s = connection.execute(
            "SELECT count(*) FROM public.stravnik WHERE jmeno LIKE 'JLLTEST REALROLL%'"
        ).fetchone()[0]
        after_obv = connection.execute(
            """
            SELECT count(*) FROM public.stravobv o
            JOIN public.stravnik s ON s.evidcislo = o.kodstravnika
            WHERE s.jmeno LIKE 'JLLTEST REALROLL%'
            """
        ).fetchone()[0]
        after_p = connection.execute(
            """
            SELECT count(*) FROM public.prihlas p
            JOIN public.stravnik s ON s.evidcislo = p.stravnik
            WHERE s.jmeno LIKE 'JLLTEST REALROLL%'
            """
        ).fetchone()[0]
        after_u = connection.execute(
            "SELECT count(*) FROM public.udalosti WHERE udalost = 'Nový strávník'"
        ).fetchone()[0]
    assert after_s == before_s
    assert after_obv == 0
    assert after_p == 0
    assert after_u == before_u
    monkeypatch.setattr(diner_repository.DinerRepository, "insert_audit", original)


def test_diner_create_rollback_on_audit_fail(lab_database: LabDatabase) -> None:
    """Simulace: po insertu vynutíme audit fail přes prázdného actora."""

    service = _diner_service(lab_database)
    with lab_database.connect() as connection:
        before = connection.execute(
            "SELECT count(*) FROM public.stravnik WHERE jmeno LIKE 'JLLTEST ROLL%'"
        ).fetchone()[0]
    with pytest.raises(OrderBusinessError) as exc:
        service.create(
            CreateDinerCommand(
                jmeno="JLLTEST ROLLBACK",
                kategorie=CATEGORY,
                actor="",
                client_version=VERSION,
            )
        )
    assert exc.value.code is ErrorCode.AUDIT_FAILED
    with lab_database.connect() as connection:
        after = connection.execute(
            "SELECT count(*) FROM public.stravnik WHERE jmeno LIKE 'JLLTEST ROLL%'"
        ).fetchone()[0]
    assert after == before


def test_diner_edit_personal_and_stale(lab_database: LabDatabase) -> None:
    assert DINER_WRITE_GATES["edit_personal"].status is ContractStatus.PROVEN
    service = _diner_service(lab_database)
    created = service.create(
        CreateDinerCommand(
            jmeno="JLLTEST EDIT BASE",
            kategorie=CATEGORY,
            trida="1.A",
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        with lab_database.connect() as connection:
            updated = connection.execute(
                "SELECT updated_dt FROM public.stravnik WHERE evidcislo = %s",
                (created.evidcislo,),
            ).fetchone()[0]
        service.edit_personal(
            EditDinerPersonalCommand(
                evidcislo=created.evidcislo,
                expected_updated_dt=updated,
                fields={"jmeno": "JLLTEST EDIT DONE", "trida": "2.B"},
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT jmeno, trida, updated_dt FROM public.stravnik WHERE evidcislo = %s",
                (created.evidcislo,),
            ).fetchone()
            assert str(row[0]) == "JLLTEST EDIT DONE"
            assert str(row[1]) == "2.B"
            new_dt = row[2]
        with pytest.raises(OrderBusinessError) as exc:
            service.edit_personal(
                EditDinerPersonalCommand(
                    evidcislo=created.evidcislo,
                    expected_updated_dt=updated,
                    fields={"jmeno": "JLLTEST STALE"},
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        assert exc.value.code is ErrorCode.CONCURRENT_MODIFICATION
        with pytest.raises(OrderBusinessError):
            service.edit_personal(
                EditDinerPersonalCommand(
                    evidcislo=created.evidcislo,
                    expected_updated_dt=new_dt,
                    fields={"kategorie": "X"},
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        with pytest.raises(OrderBusinessError):
            service.edit_personal(
                EditDinerPersonalCommand(
                    evidcislo=created.evidcislo,
                    expected_updated_dt=new_dt,
                    fields={"preplatekmm": "1"},
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
    finally:
        _cleanup_diner(lab_database, created.evidcislo)


def test_chip_assign_block_unblock_lost(lab_database: LabDatabase) -> None:
    assert CHIP_WRITE_GATES["assign"].status is ContractStatus.PROVEN
    diner_svc = _diner_service(lab_database)
    chip_svc = _chip_service(lab_database)
    created = diner_svc.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP OWN",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    with lab_database.connect() as connection:
        free = connection.execute(
            "SELECT cislo FROM public.cipy WHERE stav = 'V' ORDER BY cislo LIMIT 1"
        ).fetchone()
        assert free is not None
        chip_code = str(free[0])
    try:
        chip_svc.assign(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=created.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo = %s",
                (chip_code,),
            ).fetchone()
            assert str(row[0]) == "P"
            assert int(row[1]) == created.evidcislo
            owner = connection.execute(
                "SELECT cip FROM public.stravnik WHERE evidcislo = %s",
                (created.evidcislo,),
            ).fetchone()
            assert str(owner[0]) == chip_code
            hist = connection.execute(
                "SELECT count(*) FROM public.histcipu WHERE cislo = %s AND stav = 'P'",
                (chip_code,),
            ).fetchone()
            assert int(hist[0]) >= 1

        with pytest.raises(OrderBusinessError):
            chip_svc.assign(
                ChipCommand(
                    chip_code=chip_code,
                    evidcislo=created.evidcislo,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )

        chip_svc.block(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=created.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        chip_svc.unblock(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=created.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        chip_svc.lost(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=created.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo = %s",
                (chip_code,),
            ).fetchone()
            assert str(row[0]) == "Z"
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo = %s",
                (created.evidcislo,),
            ).fetchone()
            assert str(owner[0]) == ""
    finally:
        with lab_database.connect() as connection:
            connection.execute(
                "UPDATE public.cipy SET stav='V', stravnik=0 WHERE cislo = %s",
                (chip_code,),
            )
            connection.execute("DELETE FROM public.histcipu WHERE cislo = %s", (chip_code,))
            connection.commit()
        _cleanup_diner(lab_database, created.evidcislo)


def test_chip_detail_history_permission(lab_database: LabDatabase) -> None:
    chip_svc = _chip_service(lab_database)
    # evid 29 je v LAB se známým čipem; scope testu je 1JARO — najdi in-scope diner
    with lab_database.connect() as connection:
        row = connection.execute(
            """
            SELECT evidcislo FROM public.stravnik
            WHERE kategorie = %s AND stav = 'A'
              AND COALESCE(deleted,false)=false
            ORDER BY evidcislo LIMIT 1
            """,
            (CATEGORY,),
        ).fetchone()
        assert row is not None
        evid = int(row[0])
    history = chip_svc.load_history(evid)
    assert isinstance(history, tuple)

    denied = SessionPolicy(
        user_identity="LAB",
        allowed_categories=frozenset({CATEGORY}),
        permissions=frozenset({Permission.DINERS_VIEW}),
        bypass_order_deadlines=True,
    )
    blocked = ChipCommandService(
        lab_database.connect,
        lambda: denied,
        _settings(lab_database),
    )
    with pytest.raises(Exception):
        blocked.load_history(evid)
