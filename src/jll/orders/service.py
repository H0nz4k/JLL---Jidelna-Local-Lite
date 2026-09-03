from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import Connection

from ..lab_guard import assert_lab_identity
from .audit import audit_price, transition_note, validate_audit_command
from .errors import ErrorCode, OrderBusinessError
from .models import (
    Diner,
    FinancialSnapshot,
    MealType,
    OrderAction,
    OrderCommand,
    OrderMetrics,
    OrderPlan,
    OrderResult,
    OrderRow,
    OrderServiceSettings,
    Transition,
    TransitionReason,
)
from .preflight import (
    CENT,
    assert_affordable,
    assert_deadline,
    assert_price_delta,
    calculate_credit,
    calculate_minimum_balance,
    deadline_fields,
    decimal_from_db,
    is_ordered_state,
    monthly_advisory_key,
)
from .repository import OrderRepository

LOGGER = logging.getLogger(__name__)
RETRYABLE_SQLSTATES = {"40P01", "55P03"}

ConnectionFactory = Callable[[], Connection[Any]]
ScopeProvider = Callable[[OrderCommand], Iterable[str]]


class OrderService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        settings: OrderServiceSettings,
        scope_provider: ScopeProvider,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._connection_factory = connection_factory
        self.settings = settings
        self._scope_provider = scope_provider
        self._sleeper = sleeper

    def _authorize_command(self, command: OrderCommand) -> OrderCommand:
        try:
            trusted_scope = frozenset(self._scope_provider(command))
        except Exception as exc:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Autorizační scope nelze bezpečně určit.",
            ) from exc
        if not trusted_scope or command.allowed_categories != trusted_scope:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Požadovaný category scope neodpovídá autorizované session.",
            )
        return replace(command, allowed_categories=trusted_scope)

    def execute(self, command: OrderCommand) -> OrderResult:
        validate_audit_command(command)
        last_retryable: psycopg.Error | None = None
        for attempt in range(1, self.settings.max_retries + 2):
            try:
                authorized_command = self._authorize_command(command)
                result = self._execute_once(authorized_command)
                return replace(
                    result,
                    metrics=replace(result.metrics, attempts=attempt),
                )
            except OrderBusinessError:
                raise
            except psycopg.Error as exc:
                if exc.sqlstate not in RETRYABLE_SQLSTATES:
                    raise
                last_retryable = exc
                if attempt > self.settings.max_retries:
                    break
                self._sleeper(0.05 * (2 ** (attempt - 1)))
        raise OrderBusinessError(
            ErrorCode.CONCURRENT_MODIFICATION,
            "Objednávku nelze bezpečně dokončit kvůli souběžné změně.",
            context={"sqlstate": getattr(last_retryable, "sqlstate", None)},
        ) from last_retryable

    def _execute_once(self, command: OrderCommand) -> OrderResult:
        with self._connection_factory() as connection:
            if not connection.autocommit:
                connection.autocommit = True
            repository = OrderRepository(connection)
            self._assert_lab_guard(repository)

            transaction_started = time.perf_counter()
            advisory_wait_ms = 0.0
            config_wait_ms = 0.0
            with connection.transaction():
                repository.configure_transaction(
                    lock_timeout_ms=self.settings.lock_timeout_ms,
                    statement_timeout_ms=self.settings.statement_timeout_ms,
                    business_timezone=self.settings.business_timezone,
                )

                started = time.perf_counter()
                repository.acquire_month_lock(
                    monthly_advisory_key(command.evidcislo, command.datum)
                )
                advisory_wait_ms = (time.perf_counter() - started) * 1000

                if self.settings.strict_config_lock:
                    started = time.perf_counter()
                    try:
                        repository.lock_configuration()
                    except psycopg.errors.InsufficientPrivilege as exc:
                        raise OrderBusinessError(
                            ErrorCode.LAB_GUARD_FAILED,
                            "DB role nemá oprávnění pro strict config lock.",
                        ) from exc
                    config_wait_ms = (time.perf_counter() - started) * 1000

                diner = repository.lock_diner(command)
                repository.assert_ordering_open()
                target_type = repository.get_meal_type(command.typstravy)
                related, spolecne_codes, vyloucene_codes = self._load_relations(
                    repository, target_type
                )
                types_by_name = {
                    target_type.typstravy: target_type,
                    **{item.typstravy: item for item in related.values()},
                }
                rows = repository.lock_order_rows(command, types_by_name)
                missing = sorted(set(types_by_name) - set(rows))
                if missing:
                    raise OrderBusinessError(
                        ErrorCode.ORDER_ROW_MISSING,
                        "Pro operaci chybí jednoznačný měsíční řádek.",
                        context={"types": missing},
                    )

                self._assert_temporal(repository, command, target_type)
                repository.assert_ordering_open()
                use_pricelist = repository.use_pricelist()
                plan = self._build_plan(
                    repository=repository,
                    command=command,
                    diner=diner,
                    target_type=target_type,
                    related=related,
                    spolecne_codes=spolecne_codes,
                    vyloucene_codes=vyloucene_codes,
                    rows=rows,
                    use_pricelist=use_pricelist,
                )
                assert_affordable(plan)

                affected_types = sorted(types_by_name)
                before = self._financial_snapshot(
                    repository, command, diner, rows, affected_types
                )
                original_rows = dict(rows)

                for transition in plan.transitions:
                    self._apply_transition(
                        repository,
                        command,
                        target_type,
                        diner.kategorie,
                        use_pricelist,
                        transition,
                    )

                after_rows = repository.read_order_rows(command, affected_types)
                after_diner = repository.assert_scope(command)
                after = self._financial_snapshot(
                    repository,
                    command,
                    after_diner,
                    after_rows,
                    affected_types,
                )
                self._assert_final_state(
                    plan,
                    original_rows,
                    after_rows,
                    target_type,
                    related,
                    vyloucene_codes,
                )
                self._assert_financial_postconditions(plan, before, after)

                for transition in plan.transitions:
                    repository.assert_scope(command)
                    if not repository.insert_audit(
                        command,
                        transition,
                        note=transition_note(transition),
                        price=audit_price(transition),
                    ):
                        raise OrderBusinessError(
                            ErrorCode.AUDIT_FAILED,
                            "Databázový audit změnu nepotvrdil.",
                        )

                repository.assert_scope(command)
                self._assert_final_state(
                    plan,
                    original_rows,
                    repository.read_order_rows(command, affected_types),
                    target_type,
                    related,
                    vyloucene_codes,
                )
                committed_at = repository.get_server_now()

            transaction_ms = (time.perf_counter() - transaction_started) * 1000
            LOGGER.info(
                "LAB order committed action=%s evidcislo=%s transitions=%s tx_ms=%.3f",
                command.action.value,
                command.evidcislo,
                len(plan.transitions),
                transaction_ms,
            )
            return OrderResult(
                success=True,
                action=command.action,
                evidcislo=command.evidcislo,
                datum=command.datum,
                committed_transitions=plan.transitions,
                committed_at=committed_at,
                metrics=OrderMetrics(
                    advisory_lock_wait_ms=advisory_wait_ms,
                    config_lock_wait_ms=config_wait_ms,
                    transaction_ms=transaction_ms,
                ),
            )

    def _assert_lab_guard(self, repository: OrderRepository) -> None:
        assert_lab_identity(self.settings, repository.lab_identity())

    @staticmethod
    def _relation_codes(value: str | None) -> set[str]:
        return {character for character in (value or "") if character.strip()}

    def _load_relations(
        self,
        repository: OrderRepository,
        target: MealType,
    ) -> tuple[dict[str, MealType], set[str], set[str]]:
        spolecne = self._relation_codes(target.spolecnes)
        vyloucene = self._relation_codes(target.vyloucenos)
        if spolecne & vyloucene or target.kod in spolecne | vyloucene:
            raise OrderBusinessError(
                ErrorCode.RELATION_CONFIG_INVALID,
                "Vztahy typu stravy jsou konfliktní.",
            )
        related = repository.get_related_types(spolecne | vyloucene)
        return related, spolecne, vyloucene

    def _assert_temporal(
        self,
        repository: OrderRepository,
        command: OrderCommand,
        target_type: MealType,
    ) -> None:
        server_now = repository.get_server_now()
        day_offset, cutoff = deadline_fields(
            command.action,
            prihlasdnu=target_type.prihlasdnu,
            prihlasdo=target_type.prihlasdo,
            menudnu=target_type.menudnu,
            menudo=target_type.menudo,
            odhlasdnu=target_type.odhlasdnu,
            odhlasdo=target_type.odhlasdo,
        )
        next_month = 1 if server_now.month == 12 else server_now.month + 1
        next_year = server_now.year + 1 if server_now.month == 12 else server_now.year
        calendars: dict[tuple[int, int], Mapping[int, bool]] = {}
        for year, month in (
            (server_now.year, server_now.month),
            (next_year, next_month),
        ):
            calendar = repository.get_calendar(target_type.typstravy, year, month)
            if calendar is not None:
                calendars[(year, month)] = calendar
        target_calendar = repository.get_calendar(
            target_type.typstravy,
            command.datum.year,
            command.datum.month,
        )
        assert_deadline(
            server_now=server_now,
            target=command.datum,
            day_offset=day_offset,
            cutoff=cutoff,
            target_is_cooking=bool(
                target_calendar and target_calendar.get(command.datum.day)
            ),
            calendars=calendars,
        )

    def _price(
        self,
        repository: OrderRepository,
        *,
        category: str,
        typstravy: str,
        target: date,
        menu: int,
        use_pricelist: bool,
    ) -> Decimal:
        write_raw, write_ok = repository.write_path_price(
            category, typstravy, target, menu
        )
        if not write_ok:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "DB write-path cenu menu nepotvrdil.",
            )
        write_price = decimal_from_db(
            write_raw,
            field="getcenamenuden.cena",
            null_is_zero=False,
            error_code=ErrorCode.PRICE_INVALID,
        )
        if write_price < 0:
            raise OrderBusinessError(
                ErrorCode.PRICE_INVALID,
                "Cena menu nesmí být záporná.",
            )

        if not use_pricelist:
            rate = repository.active_rate(category, typstravy, target)
            try:
                allowed_menus = int(rate["pocetmenu"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise OrderBusinessError(
                    ErrorCode.PRICE_INVALID,
                    "Počet povolených menu není platný.",
                ) from exc
            if menu > allowed_menus:
                raise OrderBusinessError(
                    ErrorCode.MENU_NOT_AVAILABLE,
                    "Požadované menu není sazbou povoleno.",
                )
            for field in ("dotace", "fksp"):
                if (
                    decimal_from_db(
                        rate[field],
                        field=f"sazby.{field}",
                        null_is_zero=True,
                        error_code=ErrorCode.PRICE_INVALID,
                    )
                    != 0
                ):
                    raise OrderBusinessError(
                        ErrorCode.POSTCONDITION_FAILED,
                        "Nenulová dotace není v LAB pilotu podporována.",
                    )
            rate_price = decimal_from_db(
                repository.rate_price(category, typstravy, target),
                field="dej_sazbu",
                null_is_zero=False,
                error_code=ErrorCode.PRICE_INVALID,
            )
            if rate_price < 0:
                raise OrderBusinessError(
                    ErrorCode.PRICE_INVALID,
                    "Cena menu nesmí být záporná.",
                )
            if abs(rate_price - write_price) >= CENT:
                raise OrderBusinessError(
                    ErrorCode.PRICE_PATH_MISMATCH,
                    "Preflightová a write-path cena se neshodují.",
                )

        repository.assert_zero_subsidy(category, typstravy, target, menu)
        return write_price

    def _build_plan(
        self,
        *,
        repository: OrderRepository,
        command: OrderCommand,
        diner: Diner,
        target_type: MealType,
        related: Mapping[str, MealType],
        spolecne_codes: set[str],
        vyloucene_codes: set[str],
        rows: Mapping[str, OrderRow],
        use_pricelist: bool,
    ) -> OrderPlan:
        target_row = rows[target_type.typstravy]
        target_state = target_row.state
        if not repository.exact_menu_available(
            command.datum, target_type.typstravy, command.menu
        ):
            raise OrderBusinessError(
                ErrorCode.MENU_NOT_AVAILABLE,
                "Požadované konkrétní menu není zveřejněno.",
            )

        specs: list[tuple[MealType, str, str, TransitionReason]] = []
        if command.action is OrderAction.MENU_ADD:
            if target_state not in {"N", "S"}:
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Cílový typ již není ve stavu pro přihlášení.",
                )
        elif command.action is OrderAction.MENU_DELETE:
            if target_state != str(command.menu) or not is_ordered_state(target_state):
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Aktuální objednávka neodpovídá požadované odhlášce.",
                )
        else:
            if not is_ordered_state(target_state) or target_state == str(command.menu):
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Aktuální objednávka není jednoznačně změnitelná.",
                )

        if command.action in {OrderAction.MENU_ADD, OrderAction.MENU_CHANGE}:
            for code in sorted(vyloucene_codes):
                item = related[code]
                state = rows[item.typstravy].state
                if is_ordered_state(state):
                    specs.append(
                        (item, str(state), "N", TransitionReason.VYLOUCENOS)
                    )

        for code in sorted(spolecne_codes):
            item = related[code]
            state = rows[item.typstravy].state
            if command.action is OrderAction.MENU_DELETE:
                if is_ordered_state(state):
                    specs.append(
                        (item, str(state), "N", TransitionReason.SPOLECNES)
                    )
                elif state not in {"N", "S"}:
                    raise OrderBusinessError(
                        ErrorCode.ORDER_STATE_CONFLICT,
                        "Související objednávka má neplatný stav.",
                    )
            else:
                if state in {"N", "S"}:
                    specs.append(
                        (item, str(state), "1", TransitionReason.SPOLECNES)
                    )
                elif is_ordered_state(state) and state != "1":
                    specs.append((item, str(state), "1", TransitionReason.SPOLECNES))
                elif state != "1":
                    raise OrderBusinessError(
                        ErrorCode.ORDER_STATE_CONFLICT,
                        "Související objednávka má neplatný stav.",
                    )

        if command.action is OrderAction.MENU_DELETE:
            target_after = "N"
        else:
            target_after = str(command.menu)
        specs.append(
            (
                target_type,
                str(target_state),
                target_after,
                TransitionReason.PRIMARY,
            )
        )

        transitions: list[Transition] = []
        for meal_type, before_state, after_state, reason in specs:
            row = rows[meal_type.typstravy]
            if is_ordered_state(after_state) and not repository.exact_menu_available(
                command.datum, meal_type.typstravy, int(after_state)
            ):
                raise OrderBusinessError(
                    ErrorCode.MENU_NOT_AVAILABLE,
                    "Související konkrétní menu není zveřejněno.",
                )
            before_price = (
                self._price(
                    repository,
                    category=diner.kategorie,
                    typstravy=meal_type.typstravy,
                    target=command.datum,
                    menu=int(before_state),
                    use_pricelist=use_pricelist,
                )
                if is_ordered_state(before_state)
                else Decimal(0)
            )
            after_price = (
                self._price(
                    repository,
                    category=diner.kategorie,
                    typstravy=meal_type.typstravy,
                    target=command.datum,
                    menu=int(after_state),
                    use_pricelist=use_pricelist,
                )
                if is_ordered_state(after_state)
                else Decimal(0)
            )
            transitions.append(
                Transition(
                    typstravy=meal_type.typstravy,
                    before_state=before_state,
                    after_state=after_state,
                    before_price=before_price,
                    after_price=after_price,
                    reason=reason,
                    poradiprihl=row.poradiprihl,
                )
            )

        current_credit = calculate_credit(diner)
        minimum_balance = calculate_minimum_balance(
            repository.get_category_limit(diner.kategorie)
        )
        return OrderPlan(tuple(transitions), current_credit, minimum_balance)

    def _write_guard(
        self,
        repository: OrderRepository,
        command: OrderCommand,
        target_type: MealType,
        category: str,
        use_pricelist: bool,
        transition: Transition,
        expected_state: str,
        *,
        plus: bool,
    ) -> OrderRow:
        repository.assert_scope(command)
        repository.assert_ordering_open()
        self._assert_temporal(repository, command, target_type)
        rows = repository.read_order_rows(command, [transition.typstravy])
        row = rows.get(transition.typstravy)
        if row is None or row.poradiprihl != transition.poradiprihl:
            raise OrderBusinessError(
                ErrorCode.CONCURRENT_MODIFICATION,
                "Měsíční přihláška se během operace změnila.",
            )
        if row.state != expected_state:
            raise OrderBusinessError(
                ErrorCode.ORDER_STATE_CONFLICT,
                "Objednávka se během operace změnila.",
            )
        menu = int(transition.after_state if plus else transition.before_state)
        if plus and not repository.exact_menu_available(
            command.datum, transition.typstravy, menu
        ):
            raise OrderBusinessError(
                ErrorCode.MENU_NOT_AVAILABLE,
                "Menu již není zveřejněno.",
            )
        expected_price = transition.after_price if plus else transition.before_price
        current_price = self._price(
            repository,
            category=category,
            typstravy=transition.typstravy,
            target=command.datum,
            menu=menu,
            use_pricelist=use_pricelist,
        )
        if abs(current_price - expected_price) >= CENT:
            raise OrderBusinessError(
                ErrorCode.PRICE_PATH_MISMATCH,
                "Cena se během transakce změnila.",
            )
        return row

    def _assert_core_postcondition(
        self,
        repository: OrderRepository,
        command: OrderCommand,
        transition: Transition,
        before: OrderRow,
        *,
        expected_state: str,
        expected_price_delta: Decimal,
        expected_count_delta: int,
    ) -> OrderRow:
        rows = repository.read_order_rows(command, [transition.typstravy])
        row = rows.get(transition.typstravy)
        if (
            row is None
            or row.poradiprihl != transition.poradiprihl
            or row.state != expected_state
        ):
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "DB core nevytvořil očekávaný stav objednávky.",
            )
        assert_price_delta(
            row.cena - before.cena,
            expected_price_delta,
            "Měsíční cena po DB core neodpovídá očekávané změně.",
        )
        if row.pocet - before.pocet != expected_count_delta:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Počet jídel po DB core neodpovídá očekávané změně.",
            )
        repository.assert_scope(command)
        return row

    def _apply_transition(
        self,
        repository: OrderRepository,
        command: OrderCommand,
        target_type: MealType,
        category: str,
        use_pricelist: bool,
        transition: Transition,
    ) -> None:
        current_state = transition.before_state
        if is_ordered_state(current_state):
            before = self._write_guard(
                repository,
                command,
                target_type,
                category,
                use_pricelist,
                transition,
                current_state,
                plus=False,
            )
            core_result = repository.call_minus(command, transition)
            LOGGER.debug("objednavka_minus diagnostic result=%r", core_result)
            self._assert_core_postcondition(
                repository,
                command,
                transition,
                before,
                expected_state="N",
                expected_price_delta=-transition.before_price,
                expected_count_delta=-1,
            )
            current_state = "N"

        if is_ordered_state(transition.after_state):
            before = self._write_guard(
                repository,
                command,
                target_type,
                category,
                use_pricelist,
                transition,
                current_state,
                plus=True,
            )
            core_result = repository.call_plus(command, transition)
            LOGGER.debug("objednavka_plus diagnostic result=%r", core_result)
            self._assert_core_postcondition(
                repository,
                command,
                transition,
                before,
                expected_state=transition.after_state,
                expected_price_delta=transition.after_price,
                expected_count_delta=1,
            )

    @staticmethod
    def _prescribed(diner: Diner) -> Decimal:
        return decimal_from_db(
            diner.platittm,
            field="platittm",
            null_is_zero=True,
            error_code=ErrorCode.POSTCONDITION_FAILED,
        ) + decimal_from_db(
            diner.platitpm,
            field="platitpm",
            null_is_zero=True,
            error_code=ErrorCode.POSTCONDITION_FAILED,
        )

    def _financial_snapshot(
        self,
        repository: OrderRepository,
        command: OrderCommand,
        diner: Diner,
        rows: Mapping[str, OrderRow],
        meal_types: Iterable[str],
    ) -> FinancialSnapshot:
        penden_by_type = repository.penden_aggregate(command, meal_types)
        return FinancialSnapshot(
            order_price=sum((row.cena for row in rows.values()), Decimal(0)),
            order_count=sum(row.pocet for row in rows.values()),
            prescribed=self._prescribed(diner),
            penden_amount=sum(
                (amount for amount, _count in penden_by_type.values()),
                Decimal(0),
            ),
            penden_count=sum(count for _amount, count in penden_by_type.values()),
            penden_by_type=tuple(
                (typstravy, amount, count)
                for typstravy, (amount, count) in sorted(penden_by_type.items())
            ),
        )

    @staticmethod
    def _assert_financial_postconditions(
        plan: OrderPlan,
        before: FinancialSnapshot,
        after: FinancialSnapshot,
    ) -> None:
        expected = plan.planned_financial_delta
        assert_price_delta(
            after.order_price - before.order_price,
            expected,
            "Souhrnná měsíční cena neodpovídá plánu.",
        )
        assert_price_delta(
            after.prescribed - before.prescribed,
            expected,
            "Souhrnný finanční předpis neodpovídá plánu.",
        )
        assert_price_delta(
            after.penden_amount - before.penden_amount,
            -expected,
            "Souhrnný pohyb penden neodpovídá plánu.",
        )
        before_by_type = {
            typstravy: (amount, count)
            for typstravy, amount, count in before.penden_by_type
        }
        after_by_type = {
            typstravy: (amount, count)
            for typstravy, amount, count in after.penden_by_type
        }
        expected_amount_by_type: dict[str, Decimal] = {}
        expected_count_by_type: dict[str, int] = {}
        for transition in plan.transitions:
            expected_amount_by_type[transition.typstravy] = (
                expected_amount_by_type.get(transition.typstravy, Decimal(0))
                - transition.financial_delta
            )
            movement_count = 0
            if (
                is_ordered_state(transition.before_state)
                and abs(transition.before_price) >= CENT
            ):
                movement_count += 1
            if (
                is_ordered_state(transition.after_state)
                and abs(transition.after_price) >= CENT
            ):
                movement_count += 1
            expected_count_by_type[transition.typstravy] = (
                expected_count_by_type.get(transition.typstravy, 0)
                + movement_count
            )
        for typstravy in set(before_by_type) | set(after_by_type) | set(
            expected_amount_by_type
        ):
            before_amount, before_count = before_by_type.get(
                typstravy, (Decimal(0), 0)
            )
            after_amount, after_count = after_by_type.get(
                typstravy, (Decimal(0), 0)
            )
            assert_price_delta(
                after_amount - before_amount,
                expected_amount_by_type.get(typstravy, Decimal(0)),
                "Pohyb penden konkrétního typu neodpovídá plánu.",
            )
            if (
                after_count - before_count
                != expected_count_by_type.get(typstravy, 0)
            ):
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "Počet penden pohybů konkrétního typu neodpovídá plánu.",
                    context={"typstravy": typstravy},
                )
        expected_count = sum(item.count_delta for item in plan.transitions)
        if after.order_count - before.order_count != expected_count:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Souhrnný počet jídel neodpovídá plánu.",
            )

    @staticmethod
    def _assert_final_state(
        plan: OrderPlan,
        original_rows: Mapping[str, OrderRow],
        current_rows: Mapping[str, OrderRow],
        target_type: MealType,
        related: Mapping[str, MealType],
        vyloucene_codes: set[str],
    ) -> None:
        expected = {name: row.state for name, row in original_rows.items()}
        for transition in plan.transitions:
            expected[transition.typstravy] = transition.after_state
        if set(current_rows) != set(original_rows):
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Množina měsíčních přihlášek se neočekávaně změnila.",
            )
        for name, state in expected.items():
            row = current_rows.get(name)
            if row is None or row.state != state:
                raise OrderBusinessError(
                    ErrorCode.POSTCONDITION_FAILED,
                    "Finální stav dotčeného typu neodpovídá plánu.",
                    context={"typstravy": name},
                )

        exclusive_names = {target_type.typstravy}
        exclusive_names.update(
            related[code].typstravy for code in vyloucene_codes
        )
        ordered = [
            name
            for name in exclusive_names
            if is_ordered_state(current_rows[name].state)
        ]
        if len(ordered) > 1:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Po operaci zůstalo více vzájemně vyloučených typů.",
                context={"ordered_types": sorted(ordered)},
            )
