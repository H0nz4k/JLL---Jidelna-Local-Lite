"""DinerService – create + personal edit; LAB + scope fail-closed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from psycopg.errors import UniqueViolation

from .diner_models import (
    FORBIDDEN_PERSONAL_EDIT_FIELDS,
    PERSONAL_EDIT_FIELDS,
    CreateDinerCommand,
    DinerWriteResult,
    EditDinerPersonalCommand,
)
from .diner_repository import DinerRepository
from .lab_guard import assert_lab_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderServiceSettings
from .policy import Permission, SessionPolicy
from .write_gates import DINER_WRITE_GATES, require_environment_write

ConnectionFactory = Callable[[], Any]
_CREATE_ALLOCATOR_RETRIES = 5


class DinerService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
        settings: OrderServiceSettings,
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider
        self._settings = settings

    def create(self, command: CreateDinerCommand) -> DinerWriteResult:
        require_environment_write(
            DINER_WRITE_GATES,
            "create",
            environment=self._settings.environment,
            domain="diner",
        )
        policy = self._policy_provider()
        policy.require(Permission.DINERS_CREATE)
        jmeno = " ".join((command.jmeno or "").split()).upper()
        kategorie = (command.kategorie or "").strip().upper()
        trida = (command.trida or "").strip().upper()
        if not jmeno or len(jmeno) > 30:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Jméno strávníka není platné.",
            )
        if not kategorie or kategorie not in policy.scope():
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Kategorie strávníka není v povoleném scope.",
            )
        if not command.actor or not command.client_version:
            raise OrderBusinessError(
                ErrorCode.AUDIT_FAILED,
                "Chybí auditní actor nebo verze klienta.",
            )

        last_error: BaseException | None = None
        for _attempt in range(_CREATE_ALLOCATOR_RETRIES):
            try:
                return self._create_once(command, jmeno, kategorie, trida)
            except UniqueViolation as exc:
                # pridel_cislo_stravnika nemá vnitřní lock; JLL-only retry.
                last_error = exc
                continue
        raise OrderBusinessError(
            ErrorCode.CONCURRENT_MODIFICATION,
            "Allocator evidcislo kolidoval; zkuste znovu.",
        ) from last_error

    def _create_once(
        self,
        command: CreateDinerCommand,
        jmeno: str,
        kategorie: str,
        trida: str,
    ) -> DinerWriteResult:
        with self._connection_factory() as connection:
            with connection.transaction():
                repo = DinerRepository(connection)
                assert_lab_identity(self._settings, repo.lab_identity())
                evidcislo = repo.allocate_evidcislo()
                payment = repo.default_payment_method(kategorie)
                repo.insert_stravnik(
                    evidcislo=evidcislo,
                    jmeno=jmeno,
                    kategorie=kategorie,
                    trida=trida,
                    zpusobplatby=payment,
                )
                year, month = repo.period_am()
                next_year, next_month = repo.next_period(year, month)
                for y, m in ((year, month), (next_year, next_month)):
                    code = repo.dopln_obvykle_kategor(y, m, evidcislo, kategorie)
                    if code == 999:
                        raise OrderBusinessError(
                            ErrorCode.POSTCONDITION_FAILED,
                            "Doplnění obvyklých služeb selhalo.",
                        )
                    if code > 0:
                        raise OrderBusinessError(
                            ErrorCode.ORDER_STATE_CONFLICT,
                            "Existují placené přihlášky bránící create.",
                        )
                    repo.dopln_rozpis(y, m, evidcislo, kategorie)
                if not repo.insert_audit(
                    actor=command.actor,
                    event="Nový strávník",
                    note=f"{evidcislo}:{kategorie}"[:50],
                    client_version=command.client_version,
                    evidcislo=evidcislo,
                ):
                    raise OrderBusinessError(
                        ErrorCode.AUDIT_FAILED,
                        "Create audit se nepodařilo zapsat.",
                    )
                return DinerWriteResult(evidcislo, jmeno, kategorie)

    def edit_personal(self, command: EditDinerPersonalCommand) -> DinerWriteResult:
        require_environment_write(
            DINER_WRITE_GATES,
            "edit_personal",
            environment=self._settings.environment,
            domain="diner",
        )
        policy = self._policy_provider()
        policy.require(Permission.DINERS_EDIT)
        if not command.actor or not command.client_version:
            raise OrderBusinessError(
                ErrorCode.AUDIT_FAILED,
                "Chybí auditní actor nebo verze klienta.",
            )
        forbidden = set(command.fields) & FORBIDDEN_PERSONAL_EDIT_FIELDS
        if forbidden:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                f"Zakázaná pole v personal edit: {', '.join(sorted(forbidden))}",
            )
        unknown = set(command.fields) - PERSONAL_EDIT_FIELDS
        if unknown:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                f"Pole mimo whitelist: {', '.join(sorted(unknown))}",
            )
        if "kategorie" in command.fields:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Kategorie nepatří do personal edit.",
            )

        cleaned: dict[str, Any] = {}
        for key, value in command.fields.items():
            if key == "jmeno":
                text = " ".join(str(value or "").split()).upper()
                if not text or len(text) > 30:
                    raise OrderBusinessError(
                        ErrorCode.POSTCONDITION_FAILED,
                        "Jméno strávníka není platné.",
                    )
                cleaned[key] = text
            elif key == "datumnarozeni":
                cleaned[key] = value
            else:
                cleaned[key] = (
                    str(value).strip() if value is not None else None
                )

        with self._connection_factory() as connection:
            with connection.transaction():
                repo = DinerRepository(connection)
                assert_lab_identity(self._settings, repo.lab_identity())
                row = repo.fetch_for_update(command.evidcislo)
                if row is None:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Strávník neexistuje.",
                    )
                if str(row["stav"]) != "A" or bool(row["deleted"]):
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Strávník není aktivní.",
                    )
                category = str(row["kategorie"])
                if category not in policy.scope():
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Strávník je mimo povolený scope.",
                    )
                current_dt = row["updated_dt"]
                if command.expected_updated_dt is not None:
                    if current_dt is None or current_dt != command.expected_updated_dt:
                        raise OrderBusinessError(
                            ErrorCode.CONCURRENT_MODIFICATION,
                            "Strávník byl mezitím změněn jiným uživatelem.",
                        )
                before_name = str(row["jmeno"])
                repo.update_personal(command.evidcislo, cleaned)
                note = ",".join(sorted(cleaned))[:50]
                if not repo.insert_audit(
                    actor=command.actor,
                    event="Úprava strávníka",
                    note=note or before_name[:50],
                    client_version=command.client_version,
                    evidcislo=command.evidcislo,
                ):
                    raise OrderBusinessError(
                        ErrorCode.AUDIT_FAILED,
                        "Edit audit se nepodařilo zapsat.",
                    )
                return DinerWriteResult(
                    command.evidcislo,
                    str(cleaned.get("jmeno", before_name)),
                    category,
                )
