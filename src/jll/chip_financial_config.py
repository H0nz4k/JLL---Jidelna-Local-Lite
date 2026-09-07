"""Finanční konfigurace čipu z public.parametry (ne INI)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg.rows import dict_row

from .orders.errors import ErrorCode, OrderBusinessError

CHIP_DEPOSIT_SECTION = "BACKUP"
CHIP_DEPOSIT_PARAM = "CenaZaPrvniCip"
CHIP_NEXT_DEPOSIT_PARAM = "CenaZaDalsiCip"

_CONFIG_FAIL_MESSAGE = (
    "Nelze bezpečně určit zálohu za čip z nastavení jídelny.\n"
    "Operace nebyla provedena."
)


@dataclass(frozen=True, slots=True)
class ChipFinancialConfig:
    """Autoritativní záloha za první čip z LAB `public.parametry`."""

    first_chip_deposit: Decimal
    next_chip_deposit: Decimal | None = None

    @property
    def requires_payment(self) -> bool:
        return self.first_chip_deposit > 0

    def assign_blocked_message(self) -> str:
        amount = f"{self.first_chip_deposit:.2f}".replace(".", ",")
        return (
            f"Tato jídelna účtuje zálohu za čip {amount} Kč.\n"
            "Finanční zaúčtování zatím není v této verzi podporováno.\n"
            "Čip nebyl přidělen."
        )

    def return_blocked_message(self) -> str:
        amount = f"{self.first_chip_deposit:.2f}".replace(".", ",")
        return (
            f"Tato jídelna vrací zálohu za čip {amount} Kč.\n"
            "Finanční vratka zatím není v této verzi podporována.\n"
            "Čip nebyl vrácen."
        )


def _parse_money(raw: str | None) -> Decimal:
    if raw is None:
        raise OrderBusinessError(ErrorCode.RELATION_CONFIG_INVALID, _CONFIG_FAIL_MESSAGE)
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    if not text:
        raise OrderBusinessError(ErrorCode.RELATION_CONFIG_INVALID, _CONFIG_FAIL_MESSAGE)
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise OrderBusinessError(
            ErrorCode.RELATION_CONFIG_INVALID,
            _CONFIG_FAIL_MESSAGE,
        ) from exc
    if value.is_nan() or value.is_infinite() or value < 0:
        raise OrderBusinessError(ErrorCode.RELATION_CONFIG_INVALID, _CONFIG_FAIL_MESSAGE)
    # peníze max 2 desetinná místa (fail-closed při delší přesnosti)
    if value.as_tuple().exponent < -2:
        raise OrderBusinessError(ErrorCode.RELATION_CONFIG_INVALID, _CONFIG_FAIL_MESSAGE)
    return value


def load_chip_financial_config(connection: Any) -> ChipFinancialConfig:
    """Načte CenaZaPrvniCip ze sekce BACKUP; fail-closed při konfliktu."""

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT btrim(sekce) AS sekce,
                   btrim(parametr) AS parametr,
                   NULLIF(btrim(hodnota), '') AS hodnota
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower(%s)
              AND lower(btrim(parametr)) = lower(%s)
            """,
            (CHIP_DEPOSIT_SECTION, CHIP_DEPOSIT_PARAM),
        )
        rows = cursor.fetchall()
        if not rows:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                _CONFIG_FAIL_MESSAGE,
            )
        values = {row["hodnota"] for row in rows}
        if len(values) != 1:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                _CONFIG_FAIL_MESSAGE,
            )
        first = _parse_money(next(iter(values)))

        cursor.execute(
            """
            SELECT NULLIF(btrim(hodnota), '') AS hodnota
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower(%s)
              AND lower(btrim(parametr)) = lower(%s)
            """,
            (CHIP_DEPOSIT_SECTION, CHIP_NEXT_DEPOSIT_PARAM),
        )
        next_rows = cursor.fetchall()
        next_deposit: Decimal | None = None
        if next_rows:
            next_values = {row["hodnota"] for row in next_rows}
            if len(next_values) == 1:
                try:
                    next_deposit = _parse_money(next(iter(next_values)))
                except OrderBusinessError:
                    next_deposit = None

    return ChipFinancialConfig(
        first_chip_deposit=first,
        next_chip_deposit=next_deposit,
    )


def require_zero_chip_deposit(
    connection: Any,
    *,
    operation: str,
) -> ChipFinancialConfig:
    """Fail-closed před chip write, pokud záloha vyžaduje PaymentService."""

    config = load_chip_financial_config(connection)
    if config.requires_payment:
        message = (
            config.assign_blocked_message()
            if operation == "assign"
            else config.return_blocked_message()
        )
        raise OrderBusinessError(ErrorCode.RELATION_CONFIG_INVALID, message)
    return config
