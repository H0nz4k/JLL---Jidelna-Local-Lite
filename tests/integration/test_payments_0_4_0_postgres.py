"""0.4.0 payments history + manual post + atomic chip deposit."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from jll.chip_command_service import ChipCommandService
from jll.diner_models import ChipCommand, CreateDinerCommand
from jll.diner_service import DinerService
from jll.orders import ErrorCode, OrderBusinessError, OrderServiceSettings
from jll.payment_history_service import PaymentHistoryService
from jll.payment_models import ManualPaymentCommand
from jll.payment_service import PaymentService
from jll.policy import Permission, SessionPolicy
from jll.write_gates import PAYMENT_WRITE_GATES, ContractStatus

from conftest import LabDatabase

pytestmark = pytest.mark.integration

CATEGORY = "1JARO"
ACTOR = "LABTEST:VED"
VERSION = "0.4.0"


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


def _policy(*, extra: frozenset[Permission] | None = None) -> SessionPolicy:
    perms = frozenset(Permission) if extra is None else extra
    return SessionPolicy(
        user_identity="LAB",
        allowed_categories=frozenset({CATEGORY}),
        permissions=perms,
        bypass_order_deadlines=True,
    )


def _services(database: LabDatabase, policy=None):
    pol = policy or (lambda: _policy())
    settings = _settings(database)
    payments = PaymentService(database.connect, pol, settings)
    history = PaymentHistoryService(database.connect, pol, settings)
    chips = ChipCommandService(database.connect, pol, settings, payment_service=payments)
    diners = DinerService(database.connect, pol, settings)
    return diners, chips, payments, history


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
        connection.execute("DELETE FROM public.penden WHERE evidcislo = %s", (evidcislo,))
        connection.execute("DELETE FROM public.prihlas WHERE stravnik = %s", (evidcislo,))
        connection.execute("DELETE FROM public.stravobv WHERE kodstravnika = %s", (evidcislo,))
        connection.execute("DELETE FROM public.stravnik WHERE evidcislo = %s", (evidcislo,))
        connection.commit()


def test_payment_history_requires_view_and_scopes(lab_database: LabDatabase) -> None:
    diners, _, _, history_full = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST PAY HIST",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        limited = PaymentHistoryService(
            lab_database.connect,
            lambda: _policy(extra=frozenset({Permission.DINERS_VIEW})),
            _settings(lab_database),
        )
        with pytest.raises(OrderBusinessError) as exc:
            limited.list_for_diner(diner.evidcislo)
        assert exc.value.code is ErrorCode.OUT_OF_SCOPE_OR_INACTIVE

        page = history_full.list_for_diner(diner.evidcislo, limit=5)
        assert page.evidcislo == diner.evidcislo
        assert page.items == ()
        assert page.has_more is False
    finally:
        _cleanup(lab_database, diner.evidcislo)


def test_manual_payment_bank_single_service(lab_database: LabDatabase) -> None:
    assert PAYMENT_WRITE_GATES["manual_payment"].status is ContractStatus.PROVEN
    diners, _, payments, history = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST PAY MANUAL",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        this_y, this_m = payments.accounting_periods()[0]
        with lab_database.connect() as connection:
            before_tm = connection.execute(
                "SELECT platbatm FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
        result = payments.post_manual(
            ManualPaymentCommand(
                evidcislo=diner.evidcislo,
                amount=Decimal("150.50"),
                payment_method_code="4",
                account="STRAV",
                service_type="Oběd-A",
                period_month=this_m,
                note="JLL test platba",
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        assert result.ledger_type == "P"
        assert result.amount == Decimal("150.50")
        page = history.list_for_diner(diner.evidcislo, limit=5)
        assert len(page.items) == 1
        entry = page.items[0]
        assert entry.id == result.penden_id
        assert entry.amount == Decimal("150.50")
        assert entry.ledger_type == "P"
        assert entry.category_snapshot == CATEGORY
        detail = history.get_detail(result.penden_id)
        assert detail.payment_method_code == "4"
        assert detail.account == "STRAV"
        with lab_database.connect() as connection:
            after_tm = connection.execute(
                "SELECT platbatm FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            audit = connection.execute(
                """
                SELECT count(*) FROM public.udalosti
                WHERE stravnik=%s AND udalost='Platba' AND typ='B'
                """,
                (diner.evidcislo,),
            ).fetchone()[0]
        assert Decimal(str(after_tm)) - Decimal(str(before_tm or 0)) == Decimal("150.50")
        assert int(audit) >= 1
        assert this_y == result.period_year
    finally:
        _cleanup(lab_database, diner.evidcislo)


def test_cash_payment_blocked(lab_database: LabDatabase) -> None:
    diners, _, payments, _ = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST PAY CASH",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        this_m = payments.accounting_periods()[0][1]
        with pytest.raises(Exception):
            payments.post_manual(
                ManualPaymentCommand(
                    evidcislo=diner.evidcislo,
                    amount=Decimal("10"),
                    payment_method_code="1",
                    account="STRAV",
                    service_type="Oběd-A",
                    period_month=this_m,
                    note="cash",
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
    finally:
        _cleanup(lab_database, diner.evidcislo)


def test_atomic_chip_assign_and_return_with_deposit(lab_database: LabDatabase) -> None:
    diners, chips, _, history = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP DEP",
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
        _set_deposit(connection, "100")
        connection.commit()
    try:
        chips.assign(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            chip_row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            penden = connection.execute(
                """
                SELECT castka, typ, mesic, typplatby
                FROM public.penden
                WHERE evidcislo=%s AND typ='C'
                ORDER BY id DESC LIMIT 1
                """,
                (diner.evidcislo,),
            ).fetchone()
        assert str(chip_row[0]) == "P"
        assert int(chip_row[1]) == diner.evidcislo
        assert str(owner) == chip_code
        assert penden is not None
        assert Decimal(str(penden[0])) == Decimal("100")
        assert str(penden[1]) == "C"
        assert int(penden[2]) == 0
        assert str(penden[3]) != "1"

        page = history.list_for_diner(diner.evidcislo)
        assert any(i.ledger_type == "C" and i.amount == Decimal("100") for i in page.items)

        chips.return_chip(
            ChipCommand(
                chip_code=chip_code,
                evidcislo=diner.evidcislo,
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        with lab_database.connect() as connection:
            chip_row = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            refunds = connection.execute(
                """
                SELECT castka FROM public.penden
                WHERE evidcislo=%s AND typ='C' AND castka < 0
                """,
                (diner.evidcislo,),
            ).fetchall()
        assert str(chip_row[0]) == "V"
        assert int(chip_row[1]) == 0
        assert any(Decimal(str(r[0])) == Decimal("-100") for r in refunds)
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_chip_assign_rolls_back_when_finance_fails(lab_database: LabDatabase) -> None:
    diners, chips, payments, _ = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP FINFAIL",
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
        _set_deposit(connection, "100")
        connection.commit()
    try:
        with patch.object(
            payments,
            "post_chip_deposit_on_cursor",
            side_effect=OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED, "injected finance fail"
            ),
        ):
            with pytest.raises(OrderBusinessError, match="injected finance fail"):
                chips.assign(
                    ChipCommand(
                        chip_code=chip_code,
                        evidcislo=diner.evidcislo,
                        actor=ACTOR,
                        client_version=VERSION,
                    )
                )
        with lab_database.connect() as connection:
            after = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            penden = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
        assert after == before
        assert int(penden) == 0
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_chip_assign_rolls_back_finance_when_chip_fails(
    lab_database: LabDatabase,
) -> None:
    diners, chips, _, _ = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP CHIPFAIL",
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
        _set_deposit(connection, "100")
        connection.commit()
    try:
        with patch.object(
            chips,
            "_assign_tx",
            side_effect=OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED, "injected chip fail"
            ),
        ):
            with pytest.raises(OrderBusinessError, match="injected chip fail"):
                chips.assign(
                    ChipCommand(
                        chip_code=chip_code,
                        evidcislo=diner.evidcislo,
                        actor=ACTOR,
                        client_version=VERSION,
                    )
                )
        with lab_database.connect() as connection:
            after = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            penden = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s AND typ='C'",
                (diner.evidcislo,),
            ).fetchone()[0]
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
        assert after == before
        assert int(penden) == 0
        assert str(owner) == ""
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)
