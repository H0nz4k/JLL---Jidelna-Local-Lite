"""ServingService – výdej přes DB funkce; LAB + scope fail-closed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .lab_guard import assert_runtime_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderServiceSettings
from .policy import Permission, SessionPolicy
from .serving_repository import ChipIdentityRow, MealReadyRow, ServingRepository
from .write_gates import SERVING_WRITE_GATES, require_environment_write

ConnectionFactory = Callable[[], Any]


class ServingService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
        settings: OrderServiceSettings,
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider
        self._settings = settings

    def identify_chip(self, chip_uid: str) -> ChipIdentityRow:
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_VIEW)
        scope = policy.scope()
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            repository = ServingRepository(connection)
            assert_runtime_identity(self._settings, repository.lab_identity())
            row = repository.nacti_cip(chip_uid)
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
            assert_runtime_identity(self._settings, repository.lab_identity())
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT kategorie FROM public.stravnik
                    WHERE evidcislo = %s
                      AND stav = 'A'
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

    def meals_ready_manual(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        """Ruční odběr: dnešní přihlášky bez filtru výdejního okna."""

        policy = self._policy_provider()
        policy.require(Permission.PICKUP_STATUS_VIEW)
        scope = policy.scope()
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            repository = ServingRepository(connection)
            assert_runtime_identity(self._settings, repository.lab_identity())
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT kategorie FROM public.stravnik
                    WHERE evidcislo = %s
                      AND stav = 'A'
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
            return repository.stravy_k_manualni_odber(evidcislo)

    def record_pickup(
        self,
        prihlaska_id: int,
        *,
        evidcislo: int | None = None,
    ) -> bool:
        """Zápis výdeje přes public.zapis_odber s LAB/scope gate."""

        require_environment_write(
            SERVING_WRITE_GATES,
            "record_pickup",
            environment=self._settings.environment,
            domain="serving",
        )
        if prihlaska_id <= 0:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Neplatné id přihlášky pro výdej.",
            )
        policy = self._policy_provider()
        policy.require(Permission.ORDERS_CHANGE)
        scope = policy.scope()
        with self._connection_factory() as connection:
            with connection.transaction():
                repository = ServingRepository(connection)
                assert_runtime_identity(self._settings, repository.lab_identity())
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT s.evidcislo, s.kategorie
                        FROM public.prihlas AS p
                        JOIN public.stravnik AS s ON s.evidcislo = p.stravnik
                        WHERE p.id = %s
                          AND s.stav = 'A'
                          AND COALESCE(s.deleted, false) = false
                        """,
                        (prihlaska_id,),
                    )
                    row = cursor.fetchone()
                if row is None:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Přihláška výdeje neexistuje nebo strávník není aktivní.",
                    )
                owner = int(row[0])
                category = str(row[1])
                if category not in scope:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Přihláška výdeje je mimo povolený scope.",
                    )
                if evidcislo is not None and owner != evidcislo:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Přihláška nepatří ověřenému strávníkovi.",
                    )
                return repository.zapis_odber(prihlaska_id)

    def record_serving(
        self,
        prihlaska_id: int,
        *,
        evidcislo: int | None = None,
    ) -> bool:
        return self.record_pickup(prihlaska_id, evidcislo=evidcislo)

    def get_meals_to_serve(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        return self.meals_ready(evidcislo)
