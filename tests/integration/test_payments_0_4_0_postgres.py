"""0.4.0/0.4.1 payments: history, manual non-cash, Decimal, deposit>0 fail-closed."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jll.chip_command_service import ChipCommandService
from jll.diner_models import ChipCommand, CreateDinerCommand
from jll.diner_service import DinerService
from jll.orders import ErrorCode, OrderBusinessError, OrderServiceSettings
from jll.payment_history_service import PaymentHistoryService
from jll.payment_models import ManualPaymentCommand
from jll.payment_service import PaymentService
from jll.policy import Permission, SessionPolicy
from jll.write_gates import (
    PAYMENT_WRITE_GATES,
    ContractStatus,
    WriteContractNotProven,
)

from conftest import LabDatabase

pytestmark = pytest.mark.integration

CATEGORY = "1JARO"
ACTOR = "LABTEST:VED"
VERSION = "0.4.1"


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


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0.01"),
        Decimal("0.10"),
        Decimal("0.29"),
        Decimal("1234.56"),
        Decimal("999999.99"),
    ],
)
def test_manual_payment_decimal_exactness(
    lab_database: LabDatabase, amount: Decimal
) -> None:
    diners, _, payments, history = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno=f"JLLTEST PAY DEC {amount}",
            kategorie=CATEGORY,
            actor=ACTOR,
            client_version=VERSION,
        )
    )
    try:
        this_m = payments.accounting_periods()[0][1]
        with lab_database.connect() as connection:
            before_tm = Decimal(
                str(
                    connection.execute(
                        "SELECT platbatm FROM public.stravnik WHERE evidcislo=%s",
                        (diner.evidcislo,),
                    ).fetchone()[0]
                    or 0
                )
            )
        result = payments.post_manual(
            ManualPaymentCommand(
                evidcislo=diner.evidcislo,
                amount=amount,
                payment_method_code="4",
                account="STRAV",
                service_type="Oběd-A",
                period_month=this_m,
                note="JLL decimal",
                actor=ACTOR,
                client_version=VERSION,
            )
        )
        assert result.amount == amount
        detail = history.get_detail(result.penden_id)
        assert detail.amount == amount
        with lab_database.connect() as connection:
            row = connection.execute(
                "SELECT castka FROM public.penden WHERE id=%s",
                (result.penden_id,),
            ).fetchone()
            after_tm = Decimal(
                str(
                    connection.execute(
                        "SELECT platbatm FROM public.stravnik WHERE evidcislo=%s",
                        (diner.evidcislo,),
                    ).fetchone()[0]
                    or 0
                )
            )
        assert Decimal(str(row[0])) == amount
        assert after_tm - before_tm == amount
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
        entry = history.list_for_diner(diner.evidcislo, limit=5).items[0]
        assert entry.id == result.penden_id
        assert entry.category_snapshot == CATEGORY
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
        with pytest.raises(WriteContractNotProven):
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
        assert PAYMENT_WRITE_GATES["cash_payment"].status is ContractStatus.BLOCKED
    finally:
        _cleanup(lab_database, diner.evidcislo)


def test_chip_deposit_positive_fail_closed_no_mutation(
    lab_database: LabDatabase,
) -> None:
    assert PAYMENT_WRITE_GATES["chip_deposit"].status is ContractStatus.BLOCKED
    diners, chips, _, _ = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP DEP BLOCK",
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
            chips.assign(
                ChipCommand(
                    chip_code=chip_code,
                    evidcislo=diner.evidcislo,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        assert exc.value.code is ErrorCode.RELATION_CONFIG_INVALID
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
            penden = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            uctenky = connection.execute(
                "SELECT count(*) FROM public.uctenky_kasy WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            owner = connection.execute(
                "SELECT COALESCE(btrim(cip),'') FROM public.stravnik WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
        assert after == before
        assert hist_after == hist_before
        assert int(penden) == 0
        assert int(uctenky) == 0
        assert str(owner) == ""
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_chip_return_positive_fail_closed_no_mutation(
    lab_database: LabDatabase,
) -> None:
    diners, chips, _, _ = _services(lab_database)
    diner = diners.create(
        CreateDinerCommand(
            jmeno="JLLTEST CHIP RET BLOCK",
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
            before = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            penden_before = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
            _set_deposit(connection, "75")
            connection.commit()
        with pytest.raises(OrderBusinessError) as exc:
            chips.return_chip(
                ChipCommand(
                    chip_code=chip_code,
                    evidcislo=diner.evidcislo,
                    actor=ACTOR,
                    client_version=VERSION,
                )
            )
        assert exc.value.code is ErrorCode.RELATION_CONFIG_INVALID
        assert "75" in str(exc.value).replace(",", ".")
        with lab_database.connect() as connection:
            after = connection.execute(
                "SELECT stav, stravnik FROM public.cipy WHERE cislo=%s",
                (chip_code,),
            ).fetchone()
            penden_after = connection.execute(
                "SELECT count(*) FROM public.penden WHERE evidcislo=%s",
                (diner.evidcislo,),
            ).fetchone()[0]
        assert after == before
        assert penden_after == penden_before
    finally:
        with lab_database.connect() as connection:
            _set_deposit(connection, "0")
            connection.commit()
        _cleanup(lab_database, diner.evidcislo, chip_code)


def test_cash_type_and_gates_documented(lab_database: LabDatabase) -> None:
    with lab_database.connect() as connection:
        row = connection.execute(
            "SELECT popis FROM public.typplatb WHERE btrim(typplatby)='1'"
        ).fetchone()
        eet = connection.execute(
            """
            SELECT DISTINCT hodnota FROM public.parametry
            WHERE lower(btrim(parametr))=lower('ModulEET')
            """
        ).fetchall()
    assert row is not None
    assert "Hotov" in str(row[0])
    assert PAYMENT_WRITE_GATES["chip_deposit"].status is ContractStatus.BLOCKED
    assert PAYMENT_WRITE_GATES["chip_deposit_refund"].status is ContractStatus.BLOCKED
    # LAB: ModulEET off (0) — EET není důvod k portu, ale uctenky_kasy stále chybí
    assert {str(r[0]).strip() for r in eet} <= {"0", "1"}
