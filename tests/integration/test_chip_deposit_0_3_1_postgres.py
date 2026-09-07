"""0.3.1 chip deposit safety + audit server time + return deposit=0."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jll.chip_command_service import ChipCommandService
from jll.chip_financial_config import load_chip_financial_config
from jll.diner_models import ChipCommand, CreateDinerCommand
from jll.diner_service import DinerService
from jll.orders import ErrorCode, OrderBusinessError, OrderServiceSettings
from jll.policy import Permission, SessionPolicy
from jll.write_gates import CHIP_WRITE_GATES, ContractStatus

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


def _policy() -> SessionPolicy:
    return SessionPolicy(
        user_identity="LAB",
        allowed_categories=frozenset({CATEGORY}),
        permissions=frozenset(Permission),
        bypass_order_deadlines=True,
    )


def _diner(database: LabDatabase) -> DinerService:
    return DinerService(database.connect, _policy, _settings(database))


def _chip(database: LabDatabase) -> ChipCommandService:
    return ChipCommandService(database.connect, _policy, _settings(database))


def _cleanup(database: LabDatabase, evidcislo: int, chip_code: str | None = None) -> None:
    with database.connect() as connection:
        if chip_code:
            connection.execute(
                "UPDATE public.cipy SET stav='V', stravnik=0 WHERE cislo = %s",
                (chip_code,),
            )
            connection.execute("DELETE FROM public.histcipu WHERE cislo = %s", (chip_code,))
        connection.execute("DELETE FROM public.udalosti WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.histcipu WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.prihlas WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.stravobv WHERE kodstravnika = %s", (evidcislo,))
        connection.execute("DELETE FROM public.stravnik WHERE evidcislo = %s", (evidcislo,))
        connection.commit()


def _set_deposit(connection, value: str) -> None:
    connection.execute(
        """
        UPDATE public.parametry
        SET hodnota = %s
        WHERE lower(btrim(sekce)) = lower('BACKUP')
          AND lower(btrim(parametr)) = lower('CenaZaPrvniCip')
        """,
        (value,),
    )


def test_lab_deposit_is_zero_by_default(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        cfg = load_chip_financial_config(connection)
    assert cfg.first_chip_deposit == Decimal("0")
    assert not cfg.requires_payment


def test_assign_pass_when_deposit_zero(lab_database: LabDatabase) -> None:
    assert CHIP_WRITE_GATES["assign"].status is ContractStatus.PROVEN
    diner = _diner(lab_database).create(
        CreateDinerCommand(
            jmeno="JLLTEST DEP0 ASSIGN",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    with lab_database.connect() as connection:
        chip_code = connection.execute(
            "SELECT cislo FROM public.cipy WHERE stav='V' ORDER BY cislo LIMIT 1"
        ).fetchone()[0]
        _set_deposit(connection, "0")
        connection.commit()
    try:
        _chip(lab_database).assign(
            ChipCommand(
                chip_code=str(chip_code),
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            assert str(row[0]) == "P"
            assert int(row[1]) == diner.evidcislo
    finally:
        _cleanup(lab_database, diner.evidcislo, str(chip_code))
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()


def test_assign_blocked_before_write_when_deposit_positive(
    lab_database: LabDatabase,
) -> None:
    diner = _diner(lab_database).create(
        CreateDinerCommand(
            jmeno="JLLTEST DEP+ ASSIGN",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    with lab_database.connect() as connection:
        chip_code = str(
            connection.execute(
                "SELECT cislo FROM public.cipy WHERE stav='V' ORDER BY cislo LIMIT 1"
            ).fetchone()[0]
        )
        before = connection.execute(
            "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
            (chip_code,),
        ).fetchone()
        hist_before = connection.execute(
            "SELECT count(*) FROM public.histcipu WHERE cislo=%s",
            (chip_code,),
        ).fetchone()[0]
        _set_deposit(connection, "100")
        connection.commit()
    try:
        with pytest.raises(OrderBusinessError) as exc:
            _chip(lab_database).assign(
                ChipCommand(
                    chip_code=chip_code,
                    evidcislo=diner.evidcislo,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        assert exc.value.code is ErrorCode.RELATION_CONFIG_INVALID
        assert "100,00" in str(exc.value) or "100.00" in str(exc.value)
        assert "Hotovostní" in str(exc.value)
        with lab_database.connect() as connection:
            after = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            hist_after = connection.execute(
                "SELECT count(*) FROM public.histcipu WHERE cislo=%s",
                (chip_code,),
            ).fetchone()[0]
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            penden = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s AND typ='C'",
                (diner.evidcislo,),
            ).fetchone()[0]
        assert after == before
        assert hist_after == hist_before
        assert str(owner) == ""
        assert int(penden) == 0
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_deposit_missing_invalid_negative_fail_closed(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        if hasattr(connection, "autocommit"):
            connection.autocommit = False
        connection.execute(
            """
            DELETE FROM public.parametry
            WHERE lower(btrim(sekce))=lower('BACKUP')
              AND lower(btrim(parametr))=lower('CenaZaPrvniCip')
            """
        )
        try:
            with pytest.raises(OrderBusinessError) as exc:
                load_chip_financial_config(connection)
            assert "Nelze bezpečně určit zálohu" in str(exc.value)
        finally:
            connection.rollback()

    for bad in ("xyz", "-5", "1.234"):
        with lab_database.connect() as connection:
            if hasattr(connection, "autocommit"):
                connection.autocommit = False
            _set_deposit(connection, bad)
            try:
                with pytest.raises(OrderBusinessError):
                    load_chip_financial_config(connection)
            finally:
                connection.rollback()


def test_return_zero_deposit_happy_path(lab_database: LabDatabase) -> None:
    assert CHIP_WRITE_GATES["return"].status is ContractStatus.PROVEN
    diner = _diner(lab_database).create(
        CreateDinerCommand(
            jmeno="JLLTEST RET0",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    with lab_database.connect() as connection:
        chip_code = str(
            connection.execute(
                "SELECT cislo FROM public.cipy WHERE stav='V' ORDER BY cislo LIMIT 1"
            ).fetchone()[0]
        )
        _set_deposit(connection, "0")
        connection.commit()
    chip = _chip(lab_database)
    try:
        chip.assign(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        chip.return_chip(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            hist = connection.execute(
                "SELECT count(*) FROM public.histcipu WHERE cislo=%s AND stav='V'",
                (chip_code,),
            ).fetchone()[0]
        assert str(row[0]) == "V"
        assert int(row[1]) == 0
        assert str(owner) == ""
        assert int(hist) >= 1
    finally:
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_return_positive_deposit_blocked_without_mutation(
    lab_database: LabDatabase,
) -> None:
    diner = _diner(lab_database).create(
        CreateDinerCommand(
            jmeno="JLLTEST RET+",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    with lab_database.connect() as connection:
        chip_code = str(
            connection.execute(
                "SELECT cislo FROM public.cipy WHERE stav='V' ORDER BY cislo LIMIT 1"
            ).fetchone()[0]
        )
        _set_deposit(connection, "0")
        connection.commit()
    chip = _chip(lab_database)
    try:
        chip.assign(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            before = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            _set_deposit(connection, "75")
            connection.commit()
        with pytest.raises(OrderBusinessError) as exc:
            chip.return_chip(
                ChipCommand(
                    chip_code=chip_code,
                    evidcislo=diner.evidcislo,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        assert "75,00" in str(exc.value) or "75.00" in str(exc.value)
        assert "Hotovostní" in str(exc.value) or "hotovost" in str(exc.value).casefold()
        with lab_database.connect() as connection:
            after = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
        assert after == before
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_audit_uses_database_current_date(lab_database: LabDatabase) -> None:
    diner = _diner(lab_database).create(
        CreateDinerCommand(
            jmeno="JLLTEST AUDITDATE",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        with lab_database.connect() as connection:
            server_date = connection.execute("SELECT CURRENT_DATE").fetchone()[0]
            row = connection.execute(
                """
                SELECT datum FROM public.udalosti
                WHERE stravnik = %s AND udalost = 'Nový strávník'
                ORDER BY cas DESC NULLS LAST
                LIMIT 1
                """,
                (diner.evidcislo,),
            ).fetchone()
        assert row is not None
        assert row[0] == server_date
    finally:
        _cleanup(lab_database, diner.evidcislo)
