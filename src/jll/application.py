from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderAction, OrderCommand, OrderResult
from .orders.service import OrderService
from .identity import ActorContext
from .policy import Permission, SessionPolicy
from .read_models import DinerDay, MealDay
from .read_service import OrderReadService

LOGGER = logging.getLogger(__name__)

ERROR_TEXTS: dict[ErrorCode, str] = {
    ErrorCode.ORDERING_CLOSED: "Objednávání je nyní uzavřeno.",
    ErrorCode.OUT_OF_SCOPE_OR_INACTIVE: (
        "Strávník není v této provozovně dostupný."
    ),
    ErrorCode.HOUSEHOLD_ACCOUNT_UNSUPPORTED: (
        "Tento typ účtu zatím nelze v JLL objednávat."
    ),
    ErrorCode.DEADLINE_EXPIRED: "Termín pro tuto změnu již uplynul.",
    ErrorCode.NON_COOKING_DAY: "Vybraný den není varný den.",
    ErrorCode.MENU_NOT_AVAILABLE: "Vybrané menu již není dostupné.",
    ErrorCode.PRICE_INVALID: "Cenu menu nelze bezpečně ověřit.",
    ErrorCode.PRICE_PATH_MISMATCH: "Databáze vrátila rozpornou cenu menu.",
    ErrorCode.CREDIT_DATA_INVALID: "Kredit nelze bezpečně určit.",
    ErrorCode.INSUFFICIENT_CREDIT: "Pro tuto objednávku není dostatečný kredit.",
    ErrorCode.AMBIGUOUS_ORDER_ROW: "Objednávková data nejsou jednoznačná.",
    ErrorCode.ORDER_ROW_MISSING: "Pro tento den chybí objednávková data.",
    ErrorCode.ORDER_STATE_CONFLICT: (
        "Objednávka se mezitím změnila. Zobrazení bylo obnoveno."
    ),
    ErrorCode.RELATION_CONFIG_INVALID: (
        "Nastavení souvisejících typů stravy není platné."
    ),
    ErrorCode.POSTCONDITION_FAILED: (
        "Databáze nepotvrdila bezpečný výsledek operace."
    ),
    ErrorCode.AUDIT_FAILED: "Operaci se nepodařilo bezpečně zaznamenat.",
    ErrorCode.CONCURRENT_MODIFICATION: (
        "Objednávku právě mění někdo jiný. Zkuste to znovu."
    ),
    ErrorCode.LAB_GUARD_FAILED: (
        "LAB databázi nelze bezpečně ověřit. Zápisy jsou blokovány."
    ),
}


@dataclass(frozen=True, slots=True)
class SafeError:
    user_message: str
    code: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class MutationOutcome:
    result: OrderResult | None
    refreshed: DinerDay | None
    error: SafeError | None
    refresh_error: SafeError | None
    action: OrderAction | None
    duration_ms: float

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.error is None


def present_error(error: BaseException) -> SafeError:
    correlation_id = uuid.uuid4().hex[:12]
    if isinstance(error, OrderBusinessError):
        return SafeError(
            ERROR_TEXTS.get(error.code, "Operaci nelze bezpečně dokončit."),
            error.code.value,
            correlation_id,
        )
    LOGGER.exception("Unhandled LAB request error correlation_id=%s", correlation_id)
    return SafeError(
        "Požadavek se nepodařilo dokončit. Zkuste to znovu.",
        "UNEXPECTED_ERROR",
        correlation_id,
    )


def determine_action(meal: MealDay, menu: int) -> OrderAction:
    if not any(item.menu == menu for item in meal.options):
        raise OrderBusinessError(
            ErrorCode.MENU_NOT_AVAILABLE,
            "Vybrané menu není v aktuálním jídelníčku.",
        )
    if meal.ordered_menu is None:
        if meal.current_state not in {"N", "S"}:
            raise OrderBusinessError(
                ErrorCode.ORDER_ROW_MISSING
                if meal.current_state is None
                else ErrorCode.ORDER_STATE_CONFLICT,
                "Objednávkový stav nelze bezpečně změnit.",
            )
        action = OrderAction.MENU_ADD
    elif meal.ordered_menu == menu:
        action = OrderAction.MENU_DELETE
    else:
        action = OrderAction.MENU_CHANGE
    availability = next(
        (item for item in meal.availability if item.action is action),
        None,
    )
    if availability is None or not availability.allowed:
        raise OrderBusinessError(
            availability.error_code
            if availability and availability.error_code
            else ErrorCode.DEADLINE_EXPIRED,
            "Operace není podle termínu dostupná.",
        )
    return action


class OrderApplicationService:
    def __init__(
        self,
        order_service: OrderService,
        read_service: OrderReadService,
        policy: SessionPolicy | Callable[[], SessionPolicy],
        actor_provider: Callable[[], ActorContext],
    ) -> None:
        self.order_service = order_service
        self.read_service = read_service
        self._policy_provider = (
            policy if callable(policy) else lambda: policy
        )
        self._actor_provider = actor_provider

    @property
    def policy(self) -> SessionPolicy:
        return self._policy_provider()

    def execute_selection(
        self,
        evidcislo: int,
        target: date,
        meal_type: str,
        menu: int,
    ) -> MutationOutcome:
        started = time.perf_counter()
        result: OrderResult | None = None
        primary_error: SafeError | None = None
        action: OrderAction | None = None
        try:
            policy = self.policy
            policy.require(Permission.ORDERS_CHANGE)
            actor = self._actor_provider()
            current = self.read_service.load_diner_day(evidcislo, target)
            meal = next(
                (item for item in current.meals if item.meal_type == meal_type),
                None,
            )
            if meal is None:
                raise OrderBusinessError(
                    ErrorCode.MENU_NOT_AVAILABLE,
                    "Typ stravy již není dostupný.",
                )
            action = determine_action(meal, menu)
            command = OrderCommand(
                action=action,
                evidcislo=evidcislo,
                datum=target,
                typstravy=meal_type,
                menu=menu,
                allowed_categories=policy.scope(),
                actor=actor.audit_actor,
                client_version=actor.client_version,
            )
            result = self.order_service.execute(command)
        except Exception as exc:
            primary_error = present_error(exc)

        refreshed: DinerDay | None = None
        refresh_error: SafeError | None = None
        try:
            refreshed = self.read_service.load_diner_day(evidcislo, target)
        except Exception as exc:
            refresh_error = present_error(exc)

        duration_ms = (time.perf_counter() - started) * 1000
        LOGGER.info(
            "LAB action=%s evidcislo=%s result=%s error_code=%s duration_ms=%.1f",
            action.value if action else "undetermined",
            evidcislo,
            "success" if result else "failure",
            primary_error.code if primary_error else "",
            duration_ms,
        )
        return MutationOutcome(
            result,
            refreshed,
            primary_error,
            refresh_error,
            action,
            duration_ms,
        )
