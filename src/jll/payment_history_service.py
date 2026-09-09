"""PaymentHistoryService – read-only historie `public.penden` (P+C)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row

from .lab_guard import assert_runtime_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderServiceSettings
from .payment_models import (
    LEDGER_TYPE_LABELS,
    PAYMENT_HISTORY_TYPES,
    PaymentHistoryPage,
    PaymentLedgerEntry,
)
from .policy import Permission, SessionPolicy

ConnectionFactory = Callable[[], Any]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PaymentHistoryService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
        settings: OrderServiceSettings,
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider
        self._settings = settings

    def list_for_diner(
        self,
        evidcislo: int,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> PaymentHistoryPage:
        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_VIEW)
        page_limit = self._clamp_limit(limit)
        page_offset = max(0, int(offset))
        types = sorted(PAYMENT_HISTORY_TYPES)
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_runtime(cursor)
                self._require_scoped_diner(cursor, evidcislo, policy.scope())
                cursor.execute(
                    """
                    SELECT
                        p.id,
                        p.evidcislo,
                        p.datum AS booked_on,
                        p.cas AS booked_at,
                        p.castka AS amount,
                        NULLIF(btrim(p.typ), '') AS ledger_type,
                        NULLIF(btrim(p.typplatby), '') AS payment_method_code,
                        COALESCE(NULLIF(btrim(t.popis), ''), NULLIF(btrim(p.typplatby), ''), '')
                            AS payment_method_label,
                        COALESCE(NULLIF(btrim(p.ucet), ''), '') AS account,
                        COALESCE(NULLIF(btrim(p.typstravy), ''), '') AS service_type,
                        COALESCE(NULLIF(btrim(p.poznamka), ''), '') AS note,
                        COALESCE(p.mesic, 0) AS period_month,
                        COALESCE(p.rok, 0) AS period_year,
                        COALESCE(NULLIF(btrim(p.kategorie), ''), '') AS category_snapshot,
                        COALESCE(NULLIF(btrim(p.trida), ''), '') AS class_snapshot
                    FROM public.penden AS p
                    LEFT JOIN public.typplatb AS t
                      ON btrim(t.typplatby) = btrim(p.typplatby)
                    WHERE p.evidcislo = %s
                      AND NULLIF(btrim(p.typ), '') = ANY(%s)
                    ORDER BY p.datum DESC, p.cas DESC NULLS LAST, p.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (evidcislo, types, page_limit + 1, page_offset),
                )
                rows = cursor.fetchall()
        has_more = len(rows) > page_limit
        items = tuple(self._to_entry(row) for row in rows[:page_limit])
        return PaymentHistoryPage(
            evidcislo=evidcislo,
            items=items,
            limit=page_limit,
            offset=page_offset,
            has_more=has_more,
        )

    def get_detail(self, penden_id: int) -> PaymentLedgerEntry:
        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_VIEW)
        types = sorted(PAYMENT_HISTORY_TYPES)
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_runtime(cursor)
                cursor.execute(
                    """
                    SELECT
                        p.id,
                        p.evidcislo,
                        p.datum AS booked_on,
                        p.cas AS booked_at,
                        p.castka AS amount,
                        NULLIF(btrim(p.typ), '') AS ledger_type,
                        NULLIF(btrim(p.typplatby), '') AS payment_method_code,
                        COALESCE(NULLIF(btrim(t.popis), ''), NULLIF(btrim(p.typplatby), ''), '')
                            AS payment_method_label,
                        COALESCE(NULLIF(btrim(p.ucet), ''), '') AS account,
                        COALESCE(NULLIF(btrim(p.typstravy), ''), '') AS service_type,
                        COALESCE(NULLIF(btrim(p.poznamka), ''), '') AS note,
                        COALESCE(p.mesic, 0) AS period_month,
                        COALESCE(p.rok, 0) AS period_year,
                        COALESCE(NULLIF(btrim(p.kategorie), ''), '') AS category_snapshot,
                        COALESCE(NULLIF(btrim(p.trida), ''), '') AS class_snapshot
                    FROM public.penden AS p
                    LEFT JOIN public.typplatb AS t
                      ON btrim(t.typplatby) = btrim(p.typplatby)
                    WHERE p.id = %s
                      AND NULLIF(btrim(p.typ), '') = ANY(%s)
                    """,
                    (penden_id, types),
                )
                row = cursor.fetchone()
                if row is None:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Záznam platby nebyl nalezen.",
                    )
                self._require_scoped_diner(
                    cursor, int(row["evidcislo"]), policy.scope()
                )
        return self._to_entry(row)

    @staticmethod
    def _to_entry(row: dict[str, Any]) -> PaymentLedgerEntry:
        ledger = str(row["ledger_type"] or "")
        return PaymentLedgerEntry(
            id=int(row["id"]),
            evidcislo=int(row["evidcislo"]),
            booked_on=row["booked_on"],
            booked_at=row["booked_at"],
            amount=Decimal(str(row["amount"] or 0)),
            ledger_type=ledger,
            ledger_type_label=LEDGER_TYPE_LABELS.get(ledger, ledger or "—"),
            payment_method_code=str(row["payment_method_code"] or ""),
            payment_method_label=str(row["payment_method_label"] or ""),
            account=str(row["account"] or ""),
            service_type=str(row["service_type"] or ""),
            note=str(row["note"] or ""),
            period_month=int(row["period_month"] or 0),
            period_year=int(row["period_year"] or 0),
            category_snapshot=str(row["category_snapshot"] or ""),
            class_snapshot=str(row["class_snapshot"] or ""),
        )

    def _require_scoped_diner(
        self, cursor: Any, evidcislo: int, scope: frozenset[str]
    ) -> None:
        cursor.execute(
            """
            SELECT btrim(kategorie) AS kategorie
            FROM public.stravnik
            WHERE evidcislo = %s
              AND stav = 'A'
              AND COALESCE(deleted, false) = false
            """,
            (evidcislo,),
        )
        owner = cursor.fetchone()
        if owner is None or str(owner["kategorie"]) not in scope:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník pro historii plateb není v scope.",
            )

    def _assert_runtime(self, cursor: Any) -> None:
        cursor.execute(
            """
            SELECT
                current_database() AS database_name,
                host(inet_server_addr()) AS server_address,
                system_identifier::text AS system_identifier
            FROM pg_control_system()
            """
        )
        identity = cursor.fetchone()
        assert identity is not None
        assert_runtime_identity(self._settings, identity)

    @staticmethod
    def _clamp_limit(limit: int) -> int:
        value = int(limit)
        if value < 1:
            return DEFAULT_PAGE_SIZE
        return min(value, MAX_PAGE_SIZE)
