"""PaymentService – `public.zapisplatbu` (žádný přímý INSERT do penden)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row

from .lab_guard import assert_runtime_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderServiceSettings
from .payment_models import (
    AccountOption,
    ManualPaymentCommand,
    PaymentMethodOption,
    PaymentPostResult,
)
from .policy import Permission, SessionPolicy
from .write_gates import PAYMENT_WRITE_GATES, require_environment_write

ConnectionFactory = Callable[[], Any]

CASH_PAYMENT_METHOD = "1"
DEFAULT_ACCOUNT = "STRAV"
CHIP_NOTE_DEPOSIT_PARAM = "TextZalohazaCip"
CHIP_NOTE_REFUND_PARAM = "TextVracenozaCip"
DEFAULT_CHIP_DEPOSIT_NOTE = "Záloha na čip"
DEFAULT_CHIP_REFUND_NOTE = "Vrácení zálohy za čip"


class PaymentService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
        settings: OrderServiceSettings,
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider
        self._settings = settings

    def accounting_periods(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """((this_year, this_month), (next_year, next_month))."""

        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_POST)
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_runtime(cursor)
                period = self._load_period(cursor)
        return (
            (period["this_year"], period["this_month"]),
            (period["next_year"], period["next_month"]),
        )

    def list_payment_methods(self, *, include_cash: bool = False) -> tuple[PaymentMethodOption, ...]:
        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_POST)
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_runtime(cursor)
                cursor.execute(
                    """
                    SELECT btrim(typplatby) AS code,
                           COALESCE(NULLIF(btrim(popis), ''), btrim(typplatby)) AS label
                    FROM public.typplatb
                    ORDER BY typplatby
                    """
                )
                rows = cursor.fetchall()
        items = []
        for row in rows:
            code = str(row["code"] or "")
            if not code:
                continue
            if not include_cash and code == CASH_PAYMENT_METHOD:
                continue
            items.append(PaymentMethodOption(code=code, label=str(row["label"])))
        return tuple(items)

    def list_accounts(self) -> tuple[AccountOption, ...]:
        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_POST)
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_runtime(cursor)
                cursor.execute(
                    """
                    SELECT btrim(ucet) AS code,
                           COALESCE(NULLIF(btrim(popis), ''), btrim(ucet)) AS label
                    FROM public.typuct
                    ORDER BY ucet
                    """
                )
                rows = cursor.fetchall()
        return tuple(
            AccountOption(code=str(row["code"]), label=str(row["label"]))
            for row in rows
            if row["code"]
        )

    def post_manual(self, command: ManualPaymentCommand) -> PaymentPostResult:
        require_environment_write(
            PAYMENT_WRITE_GATES,
            "manual_payment",
            environment=self._settings.environment,
            domain="payment",
        )
        policy = self._policy_provider()
        policy.require(Permission.PAYMENTS_POST)
        amount = self._positive_money(command.amount)
        method = (command.payment_method_code or "").strip()
        if not method or method == CASH_PAYMENT_METHOD:
            require_environment_write(
            PAYMENT_WRITE_GATES,
            "cash_payment",
            environment=self._settings.environment,
            domain="payment",
        )
        account = (command.account or "").strip() or DEFAULT_ACCOUNT
        service = (command.service_type or "").strip()
        if not service:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Vyberte typ služby k zaúčtování.",
            )
        note = (command.note or "").strip()
        if not command.actor or not command.client_version:
            raise OrderBusinessError(
                ErrorCode.AUDIT_FAILED,
                "Chybí auditní actor nebo verze klienta.",
            )

        with self._connection_factory() as connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    self._assert_runtime(cursor)
                    diner = self._lock_diner(cursor, command.evidcislo, policy.scope())
                    period = self._load_period(cursor)
                    if int(command.period_month) not in {
                        period["this_month"],
                        period["next_month"],
                    }:
                        raise OrderBusinessError(
                            ErrorCode.RELATION_CONFIG_INVALID,
                            "Špatný účtovaný měsíc.",
                        )
                    year = (
                        period["this_year"]
                        if int(command.period_month) == period["this_month"]
                        else period["next_year"]
                    )
                    service_kind = self._assert_service_type(cursor, service)
                    self._assert_account(cursor, account)
                    self._assert_payment_method(cursor, method)
                    before_id = self._max_penden_id(cursor, command.evidcislo)
                    before_finance = self._finance_snapshot(cursor, command.evidcislo)
                    ok = self._call_zapisplatbu(
                        cursor,
                        diner=diner,
                        amount=amount,
                        note=note or "Platba",
                        period_month=int(command.period_month),
                        period_year=year,
                        ledger_type="P",
                        payment_method=method,
                        account=account,
                        service_type=service,
                        day=0,
                    )
                    if not ok:
                        raise OrderBusinessError(
                            ErrorCode.POSTCONDITION_FAILED,
                            "zapisplatbu nevrátila úspěch.",
                        )
                    entry = self._require_new_penden(
                        cursor,
                        evidcislo=command.evidcislo,
                        before_id=before_id,
                        expected_type="P",
                        expected_amount=amount,
                    )
                    after_finance = self._finance_snapshot(cursor, command.evidcislo)
                    self._assert_manual_finance_delta(
                        before_finance,
                        after_finance,
                        amount=amount,
                        period_month=int(command.period_month),
                        this_month=period["this_month"],
                        service_kind=service_kind,
                    )
                    audit_ok = self._insert_payment_audit(
                        cursor,
                        actor=command.actor,
                        note=(note or "Platba")[:50],
                        client_version=command.client_version,
                        evidcislo=command.evidcislo,
                        amount=amount,
                        finance_state=after_finance,
                        period_month=int(command.period_month),
                        this_month=period["this_month"],
                    )
                    if not audit_ok:
                        raise OrderBusinessError(
                            ErrorCode.AUDIT_FAILED,
                            "Audit platby se nepodařilo zapsat.",
                        )
                    return PaymentPostResult(
                        penden_id=int(entry["id"]),
                        amount=amount,
                        ledger_type="P",
                        period_month=int(command.period_month),
                        period_year=year,
                    )

    def post_chip_deposit_on_cursor(
        self,
        cursor: Any,
        *,
        diner: Mapping[str, Any],
        amount: Decimal,
        actor: str,
        client_version: str,
        payment_method: str | None = None,
        account: str = DEFAULT_ACCOUNT,
    ) -> PaymentPostResult:
        """Záloha za čip uvnitř existující transakce (typ C, mesic=0)."""

        require_environment_write(
            PAYMENT_WRITE_GATES,
            "chip_deposit",
            environment=self._settings.environment,
            domain="payment",
        )
        money = self._positive_money(amount)
        method = self._resolve_chip_payment_method(cursor, payment_method)
        note = self._param_text(
            cursor, CHIP_NOTE_DEPOSIT_PARAM, DEFAULT_CHIP_DEPOSIT_NOTE
        )
        period = self._load_period(cursor)
        service = self._default_service_type(cursor)
        before_id = self._max_penden_id(cursor, int(diner["evidcislo"]))
        ok = self._call_zapisplatbu(
            cursor,
            diner=diner,
            amount=money,
            note=note,
            period_month=0,
            period_year=period["this_year"],
            ledger_type="C",
            payment_method=method,
            account=account or DEFAULT_ACCOUNT,
            service_type=service,
            day=0,
        )
        if not ok:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Finanční záloha za čip selhala.",
            )
        entry = self._require_new_penden(
            cursor,
            evidcislo=int(diner["evidcislo"]),
            before_id=before_id,
            expected_type="C",
            expected_amount=money,
        )
        # Legacy GenerujUdalost_Penden jen pro typ P; čip audit řeší ChipCommandService.
        return PaymentPostResult(
            penden_id=int(entry["id"]),
            amount=money,
            ledger_type="C",
            period_month=0,
            period_year=period["this_year"],
        )

    def post_chip_deposit_refund_on_cursor(
        self,
        cursor: Any,
        *,
        diner: Mapping[str, Any],
        amount: Decimal,
        actor: str,
        client_version: str,
        payment_method: str | None = None,
        account: str = DEFAULT_ACCOUNT,
    ) -> PaymentPostResult:
        """Vratka zálohy za čip uvnitř existující transakce (typ C, záporná částka)."""

        require_environment_write(
            PAYMENT_WRITE_GATES,
            "chip_deposit_refund",
            environment=self._settings.environment,
            domain="payment",
        )
        money = self._positive_money(amount)
        method = self._resolve_chip_payment_method(cursor, payment_method)
        note = self._param_text(
            cursor, CHIP_NOTE_REFUND_PARAM, DEFAULT_CHIP_REFUND_NOTE
        )
        period = self._load_period(cursor)
        service = self._default_service_type(cursor)
        before_id = self._max_penden_id(cursor, int(diner["evidcislo"]))
        ok = self._call_zapisplatbu(
            cursor,
            diner=diner,
            amount=-money,
            note=note,
            period_month=0,
            period_year=period["this_year"],
            ledger_type="C",
            payment_method=method,
            account=account or DEFAULT_ACCOUNT,
            service_type=service,
            day=0,
        )
        if not ok:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Finanční vratka za čip selhala.",
            )
        entry = self._require_new_penden(
            cursor,
            evidcislo=int(diner["evidcislo"]),
            before_id=before_id,
            expected_type="C",
            expected_amount=-money,
        )
        return PaymentPostResult(
            penden_id=int(entry["id"]),
            amount=-money,
            ledger_type="C",
            period_month=0,
            period_year=period["this_year"],
        )

    def _call_zapisplatbu(
        self,
        cursor: Any,
        *,
        diner: Mapping[str, Any],
        amount: Decimal,
        note: str,
        period_month: int,
        period_year: int,
        ledger_type: str,
        payment_method: str,
        account: str,
        service_type: str,
        day: int,
    ) -> bool:
        cursor.execute(
            """
            SELECT public.zapisplatbu(
                to_char(CURRENT_DATE, 'DDMMYYYY'),
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) AS result
            """,
            (
                str(diner["jmeno"])[:30],
                str(diner["kategorie"])[:10],
                str(diner.get("trida") or "")[:4],
                amount,
                note[:80],
                int(period_month),
                int(period_year),
                int(diner["evidcislo"]),
                ledger_type,
                payment_method,
                account[:20],
                service_type,
                int(day),
            ),
        )
        row = cursor.fetchone()
        return bool(row and row["result"] is True)

    def _lock_diner(
        self, cursor: Any, evidcislo: int, scope: frozenset[str]
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            SELECT evidcislo,
                   btrim(jmeno) AS jmeno,
                   btrim(kategorie) AS kategorie,
                   COALESCE(btrim(trida), '') AS trida,
                   COALESCE(NULLIF(btrim(cip), ''), '') AS cip,
                   platbatm, platbabm
            FROM public.stravnik
            WHERE evidcislo = %s
              AND stav = 'A'
              AND COALESCE(deleted, false) = false
            FOR UPDATE
            """,
            (evidcislo,),
        )
        row = cursor.fetchone()
        if row is None or str(row["kategorie"]) not in scope:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník není dostupný pro zaúčtování.",
            )
        return row

    def _load_period(self, cursor: Any) -> dict[str, int]:
        cursor.execute(
            """
            SELECT btrim(parametr) AS parametr,
                   NULLIF(btrim(hodnota), '') AS hodnota
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower('BACKUP')
              AND lower(btrim(parametr)) IN (
                lower('TentoMesic'), lower('TentoRok')
              )
            """
        )
        values = {
            str(row["parametr"]).casefold(): str(row["hodnota"])
            for row in cursor.fetchall()
            if row["hodnota"] is not None
        }
        try:
            this_month = int(values["tentomesic"])
            this_year = int(values["tentorok"])
        except (KeyError, ValueError) as exc:
            raise OrderBusinessError(
                ErrorCode.LAB_GUARD_FAILED,
                "Účetní období (TentoMesic/TentoRok) nelze bezpečně načíst.",
            ) from exc
        # Budoucí období = TentoMesic+1 (Ini.pas: budoucirok:=Tentorok / přetečení roku).
        # Parametr DalsiMesic v LAB nemusí odpovídat aritmetickému +1 — neautoritativní.
        if this_month == 12:
            next_month, next_year = 1, this_year + 1
        else:
            next_month, next_year = this_month + 1, this_year
        return {
            "this_month": this_month,
            "this_year": this_year,
            "next_month": next_month,
            "next_year": next_year,
        }

    def _default_service_type(self, cursor: Any) -> str:
        cursor.execute(
            """
            SELECT typstravy FROM public.typstrav
            WHERE typstravy = %s
            LIMIT 1
            """,
            ("Oběd",),
        )
        row = cursor.fetchone()
        if row and row["typstravy"]:
            return str(row["typstravy"])
        cursor.execute(
            """
            SELECT typstravy FROM public.typstrav
            WHERE lower(btrim(typsluzby)) = lower('strava')
            ORDER BY typstravy
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None or not row["typstravy"]:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Nelze určit výchozí typ stravy pro platbu.",
            )
        return str(row["typstravy"])

    def _resolve_chip_payment_method(
        self, cursor: Any, explicit: str | None
    ) -> str:
        if explicit:
            code = explicit.strip()
            if code == CASH_PAYMENT_METHOD:
                require_environment_write(
            PAYMENT_WRITE_GATES,
            "cash_payment",
            environment=self._settings.environment,
            domain="payment",
        )
            self._assert_payment_method(cursor, code)
            return code
        cursor.execute(
            """
            SELECT NULLIF(btrim(hodnota), '') AS hodnota
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower('BACKUP')
              AND lower(btrim(parametr)) = lower('ImplicitTypPlatby')
            """
        )
        rows = cursor.fetchall()
        values = {row["hodnota"] for row in rows if row["hodnota"]}
        if len(values) == 1:
            code = str(next(iter(values))).strip()
            if code and code != CASH_PAYMENT_METHOD:
                self._assert_payment_method(cursor, code)
                return code
        # Hotovost + uctenky_kasy/EET je BLOCKED; JLL volí nehotovostní cestu.
        fallback = "4"
        self._assert_payment_method(cursor, fallback)
        return fallback

    def _param_text(self, cursor: Any, parametr: str, default: str) -> str:
        cursor.execute(
            """
            SELECT NULLIF(btrim(hodnota), '') AS hodnota
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower('BACKUP')
              AND lower(btrim(parametr)) = lower(%s)
            """,
            (parametr,),
        )
        rows = cursor.fetchall()
        values = {row["hodnota"] for row in rows if row["hodnota"]}
        if len(values) == 1:
            return str(next(iter(values)))[:80]
        return default

    def _assert_service_type(self, cursor: Any, service: str) -> str:
        cursor.execute(
            """
            SELECT lower(btrim(typsluzby)) AS kind
            FROM public.typstrav
            WHERE typstravy = %s
            LIMIT 1
            """,
            (service,),
        )
        row = cursor.fetchone()
        if row is None:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Neplatný typ služby.",
            )
        return str(row["kind"] or "")

    def _assert_account(self, cursor: Any, account: str) -> None:
        cursor.execute(
            "SELECT 1 FROM public.typuct WHERE btrim(ucet) = %s LIMIT 1",
            (account,),
        )
        if cursor.fetchone() is None:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Neplatný účet.",
            )

    def _assert_payment_method(self, cursor: Any, method: str) -> None:
        cursor.execute(
            "SELECT 1 FROM public.typplatb WHERE btrim(typplatby) = %s LIMIT 1",
            (method,),
        )
        if cursor.fetchone() is None:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Neplatný způsob platby.",
            )

    def _max_penden_id(self, cursor: Any, evidcislo: int) -> int:
        cursor.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM public.penden WHERE evidcislo = %s",
            (evidcislo,),
        )
        row = cursor.fetchone()
        return int(row["max_id"] if row else 0)

    def _require_new_penden(
        self,
        cursor: Any,
        *,
        evidcislo: int,
        before_id: int,
        expected_type: str,
        expected_amount: Decimal,
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            SELECT id, castka, typ, mesic, rok, typplatby, ucet, typstravy, poznamka
            FROM public.penden
            WHERE evidcislo = %s AND id > %s
            ORDER BY id DESC
            LIMIT 5
            """,
            (evidcislo, before_id),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Neočekávaný počet nových řádků penden.",
            )
        row = rows[0]
        if str(row["typ"]).strip() != expected_type:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Typ řádku penden neodpovídá operaci.",
            )
        actual = Decimal(str(row["castka"]))
        if actual != expected_amount:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Částka v penden neodpovídá očekávání.",
            )
        return row

    def _finance_snapshot(self, cursor: Any, evidcislo: int) -> dict[str, Decimal]:
        cursor.execute(
            """
            SELECT platbatm, platbabm
            FROM public.stravnik
            WHERE evidcislo = %s
            """,
            (evidcislo,),
        )
        row = cursor.fetchone()
        assert row is not None
        return {
            "platbatm": Decimal(str(row["platbatm"] or 0)),
            "platbabm": Decimal(str(row["platbabm"] or 0)),
        }

    def _assert_manual_finance_delta(
        self,
        before: Mapping[str, Decimal],
        after: Mapping[str, Decimal],
        *,
        amount: Decimal,
        period_month: int,
        this_month: int,
        service_kind: str,
    ) -> None:
        # zapisplatbu: update platbatm/platbabm jen když typsluzby in (strava, …)
        # a pmesic<>0. Encoding „stravovací služba“ v LAB může mít diakritiku.
        affects = service_kind.startswith("strava")
        expected = amount if affects else Decimal(0)
        delta_tm = after["platbatm"] - before["platbatm"]
        delta_bm = after["platbabm"] - before["platbabm"]
        if period_month == this_month:
            if delta_bm != 0 or delta_tm != expected:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "Neočekávaná změna platbatm/platbabm.",
                )
        else:
            if delta_tm != 0 or delta_bm != expected:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "Neočekávaná změna platbatm/platbabm.",
                )

    def _insert_payment_audit(
        self,
        cursor: Any,
        *,
        actor: str,
        note: str,
        client_version: str,
        evidcislo: int,
        amount: Decimal,
        finance_state: Mapping[str, Decimal],
        period_month: int,
        this_month: int,
    ) -> bool:
        state = (
            finance_state["platbatm"]
            if period_month == this_month
            else finance_state["platbabm"]
        )
        cursor.execute(
            """
            SELECT public.insert_udalost(
                %s, %s, %s, %s, %s, %s,
                to_char(CURRENT_DATE, 'DDMMYYYY'),
                %s, %s
            ) AS result
            """,
            (
                actor[:25],
                "Platba",
                "B",
                note[:50],
                client_version[:10],
                evidcislo,
                int(amount),
                f"Stav:{state}"[:30],
            ),
        )
        row = cursor.fetchone()
        return bool(row and row["result"] is True)

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
    def _positive_money(value: Decimal) -> Decimal:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        if amount <= 0 or amount.as_tuple().exponent < -2:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Částka musí být kladná (max. 2 desetinná místa).",
            )
        return amount
