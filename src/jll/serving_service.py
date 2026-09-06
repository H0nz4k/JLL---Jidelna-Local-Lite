"""ServingService – výdej přes DB funkce; scope fail-closed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .orders.errors import ErrorCode, OrderBusinessError
from .policy import Permission, SessionPolicy
from .serving_repository import ChipIdentityRow, MealReadyRow, ServingRepository

ConnectionFactory = Callable[[], Any]


class ServingService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider

    def identify_chip(self, chip_uid: str) -> ChipIdentityRow:
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_VIEW)
        scope = policy.scope()
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            row = ServingRepository(connection).nacti_cip(chip_uid)
        if row is None:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Čip nebyl nalezen nebo není aktivní.",
            )
        if row.category not in scope:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Čip patří strávníkovi mimo povolený category scope.",
            )
        return row

    def meals_ready(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        policy = self._policy_provider()
        policy.require(Permission.PICKUP_STATUS_VIEW)
        scope = policy.scope()
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            repository = ServingRepository(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT kategorie FROM public.stravnik
                    WHERE evidcislo = %s
                      AND COALESCE(deleted, false) = false
                    """,
                    (evidcislo,),
                )
                row = cursor.fetchone()
            if row is None or str(row[0]) not in scope:
                raise OrderBusinessError(
                    ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                    "Strávník pro výdej není v povoleném scope.",
                )
            return repository.stravy_k_vydeji(evidcislo)

    def record_pickup(self, prihlaska_id: int) -> bool:
        """Zápis výdeje přes public.zapis_odber."""

        policy = self._policy_provider()
        policy.require(Permission.ORDERS_CHANGE)
        scope = policy.scope()
        with self._connection_factory() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT s.kategorie
                        FROM public.prihlas AS p
                        JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
                        WHERE p.id = %s
                        """,
                        (prihlaska_id,),
                    )
                    row = cursor.fetchone()
                if row is None or str(row[0]) not in scope:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Přihláška výdeje je mimo povolený scope.",
                    )
                return ServingRepository(connection).zapis_odber(prihlaska_id)

    def record_serving(self, prihlaska_id: int) -> bool:
        return self.record_pickup(prihlaska_id)

    def get_meals_to_serve(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        return self.meals_ready(evidcislo)
