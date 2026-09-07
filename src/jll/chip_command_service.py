"""ChipCommandService – lifecycle writes dle Data.pas NajdiCip / BitBtn13/14."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Mapping

from psycopg.rows import dict_row

from .diner_models import ChipCommand, ChipHistoryEntry
from .lab_guard import assert_lab_identity
from .orders.errors import ErrorCode, OrderBusinessError
from .orders.models import OrderServiceSettings
from .policy import Permission, SessionPolicy
from .read_models import chip_status_label
from .write_gates import CHIP_WRITE_GATES, require_proven

ConnectionFactory = Callable[[], Any]

CHIP_ASSIGNED = "P"
CHIP_FREE = "V"
CHIP_BLOCKED = "B"
CHIP_LOST = "Z"


class ChipCommandService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        policy_provider: Callable[[], SessionPolicy],
        settings: OrderServiceSettings,
    ) -> None:
        self._connection_factory = connection_factory
        self._policy_provider = policy_provider
        self._settings = settings

    def load_history(self, evidcislo: int) -> tuple[ChipHistoryEntry, ...]:
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_VIEW)
        scope = policy.scope()
        with self._connection_factory() as connection:
            if hasattr(connection, "autocommit") and not connection.autocommit:
                connection.autocommit = True
            with connection.cursor(row_factory=dict_row) as cursor:
                self._assert_lab(cursor)
                cursor.execute(
                    """
                    SELECT btrim(s.kategorie) AS kategorie
                    FROM public.stravnik AS s
                    WHERE s.evidcislo = %s
                      AND s.stav = 'A'
                      AND COALESCE(s.deleted, false) = false
                    """,
                    (evidcislo,),
                )
                owner = cursor.fetchone()
                if owner is None or str(owner["kategorie"]) not in scope:
                    raise OrderBusinessError(
                        ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                        "Strávník pro historii čipu není v scope.",
                    )
                cursor.execute(
                    """
                    SELECT btrim(cislo) AS code,
                           NULLIF(btrim(stav), '') AS status_code,
                           stravnik,
                           vydano
                    FROM public.histcipu
                    WHERE stravnik = %s
                    ORDER BY vydano DESC NULLS LAST, id DESC
                    LIMIT 50
                    """,
                    (evidcislo,),
                )
                rows = cursor.fetchall()
        return tuple(
            ChipHistoryEntry(
                code=str(row["code"]),
                status_code=str(row["status_code"]) if row["status_code"] else None,
                status_label=chip_status_label(row["status_code"]),
                owner_evidcislo=int(row["stravnik"]) if row["stravnik"] is not None else None,
                issued_at=row["vydano"],
            )
            for row in rows
        )

    def assign(self, command: ChipCommand) -> None:
        require_proven(CHIP_WRITE_GATES, "assign")
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_ASSIGN)
        self._run_write(command, self._assign_tx)

    def block(self, command: ChipCommand) -> None:
        require_proven(CHIP_WRITE_GATES, "block")
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_BLOCK)
        self._run_write(command, self._block_tx)

    def lost(self, command: ChipCommand) -> None:
        require_proven(CHIP_WRITE_GATES, "lost")
        policy = self._policy_provider()
        policy.require(Permission.CHIPS_LOST)
        self._run_write(command, self._lost_tx)

    def unblock(self, command: ChipCommand) -> None:
        require_proven(CHIP_WRITE_GATES, "unblock")
        policy = self._policy_provider()
        # Unblock je v legacy součást blokace / NajdiCip(B); JLL vyžaduje CHIPS_BLOCK.
        policy.require(Permission.CHIPS_BLOCK)
        self._run_write(command, self._unblock_tx)

    def _run_write(self, command: ChipCommand, handler: Callable) -> None:
        code = self._normalize_chip(command.chip_code)
        if not command.actor or not command.client_version:
            raise OrderBusinessError(
                ErrorCode.AUDIT_FAILED,
                "Chybí auditní actor nebo verze klienta.",
            )
        with self._connection_factory() as connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    self._assert_lab(cursor)
                    owner = self._lock_owner(cursor, command.evidcislo)
                    policy = self._policy_provider()
                    if str(owner["kategorie"]) not in policy.scope():
                        raise OrderBusinessError(
                            ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                            "Strávník je mimo povolený scope.",
                        )
                    handler(cursor, code, command, owner)
                    ok = self._insert_audit(
                        cursor,
                        actor=command.actor,
                        event="Čip",
                        note=f"{code}:{command.evidcislo}"[:50],
                        client_version=command.client_version,
                        evidcislo=command.evidcislo,
                    )
                    if not ok:
                        raise OrderBusinessError(
                            ErrorCode.AUDIT_FAILED,
                            "Chip audit se nepodařilo zapsat.",
                        )

    def _assign_tx(
        self,
        cursor: Any,
        code: str,
        command: ChipCommand,
        owner: Mapping[str, Any],
    ) -> None:
        current_chip = (owner.get("cip") or "").strip()
        if current_chip:
            raise OrderBusinessError(
                ErrorCode.ORDER_STATE_CONFLICT,
                "Strávník už má přidělený čip.",
            )
        cursor.execute(
            """
            SELECT cislo, NULLIF(btrim(stav), '') AS stav, stravnik
            FROM public.cipy
            WHERE cislo = %s
            FOR UPDATE
            """,
            (code,),
        )
        row = cursor.fetchone()
        if row is None:
            self._insert_hist(cursor, code, CHIP_ASSIGNED, command.evidcislo)
            cursor.execute(
                """
                INSERT INTO public.cipy (cislo, stravnik, stav, vydano)
                VALUES (%s, %s, %s, CURRENT_DATE)
                """,
                (code, command.evidcislo, CHIP_ASSIGNED),
            )
        else:
            stav = str(row["stav"] or "")
            if stav == CHIP_ASSIGNED:
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Čip je již přidělen jinému strávníkovi.",
                )
            if stav == CHIP_BLOCKED:
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Čip je blokován.",
                )
            if stav == CHIP_LOST and not command.allow_reassign_lost:
                raise OrderBusinessError(
                    ErrorCode.ORDER_STATE_CONFLICT,
                    "Čip je označen jako ztracený.",
                )
            self._insert_hist(cursor, code, CHIP_ASSIGNED, command.evidcislo)
            cursor.execute(
                """
                UPDATE public.cipy
                SET vydano = CURRENT_DATE,
                    stav = %s,
                    stravnik = %s
                WHERE cislo = %s
                """,
                (CHIP_ASSIGNED, command.evidcislo, code),
            )
        cursor.execute(
            "UPDATE public.stravnik SET cip = %s WHERE evidcislo = %s",
            (code, command.evidcislo),
        )

    def _block_tx(
        self,
        cursor: Any,
        code: str,
        command: ChipCommand,
        owner: Mapping[str, Any],
    ) -> None:
        chip = self._lock_owned_chip(cursor, code, command.evidcislo, owner)
        if str(chip["stav"] or "") != CHIP_ASSIGNED:
            raise OrderBusinessError(
                ErrorCode.ORDER_STATE_CONFLICT,
                "Blokovat lze pouze přidělený čip.",
            )
        self._insert_hist(cursor, code, CHIP_BLOCKED, command.evidcislo)
        cursor.execute(
            "UPDATE public.cipy SET stav = %s WHERE cislo = %s",
            (CHIP_BLOCKED, code),
        )

    def _lost_tx(
        self,
        cursor: Any,
        code: str,
        command: ChipCommand,
        owner: Mapping[str, Any],
    ) -> None:
        self._lock_owned_chip(cursor, code, command.evidcislo, owner)
        cursor.execute(
            "UPDATE public.cipy SET stav = %s WHERE cislo = %s",
            (CHIP_LOST, code),
        )
        self._insert_hist(cursor, code, CHIP_LOST, command.evidcislo)
        cursor.execute(
            "UPDATE public.stravnik SET cip = '' WHERE evidcislo = %s",
            (command.evidcislo,),
        )

    def _unblock_tx(
        self,
        cursor: Any,
        code: str,
        command: ChipCommand,
        owner: Mapping[str, Any],
    ) -> None:
        chip = self._lock_owned_chip(cursor, code, command.evidcislo, owner)
        if str(chip["stav"] or "") != CHIP_BLOCKED:
            raise OrderBusinessError(
                ErrorCode.ORDER_STATE_CONFLICT,
                "Odblokovat lze pouze blokovaný čip.",
            )
        cursor.execute(
            "UPDATE public.cipy SET stav = %s WHERE cislo = %s",
            (CHIP_ASSIGNED, code),
        )
        self._insert_hist(cursor, code, CHIP_ASSIGNED, command.evidcislo)

    def _lock_owner(self, cursor: Any, evidcislo: int) -> Mapping[str, Any]:
        cursor.execute(
            """
            SELECT evidcislo, btrim(kategorie) AS kategorie,
                   NULLIF(btrim(cip), '') AS cip,
                   stav, COALESCE(deleted, false) AS deleted
            FROM public.stravnik
            WHERE evidcislo = %s
            FOR UPDATE
            """,
            (evidcislo,),
        )
        row = cursor.fetchone()
        if row is None or str(row["stav"]) != "A" or bool(row["deleted"]):
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Strávník pro čipovou operaci není dostupný.",
            )
        return row

    def _lock_owned_chip(
        self,
        cursor: Any,
        code: str,
        evidcislo: int,
        owner: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        owner_chip = (owner.get("cip") or "").strip()
        if owner_chip and owner_chip != code:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Čip nepatří vybranému strávníkovi.",
            )
        cursor.execute(
            """
            SELECT cislo, NULLIF(btrim(stav), '') AS stav, stravnik
            FROM public.cipy
            WHERE cislo = %s
            FOR UPDATE
            """,
            (code,),
        )
        row = cursor.fetchone()
        if row is None or int(row["stravnik"] or 0) != evidcislo:
            raise OrderBusinessError(
                ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                "Čip nepatří vybranému strávníkovi.",
            )
        return row

    def _insert_hist(
        self, cursor: Any, code: str, stav: str, evidcislo: int
    ) -> None:
        cursor.execute(
            """
            INSERT INTO public.histcipu (cislo, stravnik, vydano, stav)
            VALUES (%s, %s, CURRENT_DATE, %s)
            """,
            (code, evidcislo, stav),
        )

    def _insert_audit(
        self,
        cursor: Any,
        *,
        actor: str,
        event: str,
        note: str,
        client_version: str,
        evidcislo: int,
    ) -> bool:
        today = date.today().strftime("%d%m%Y")
        cursor.execute(
            """
            SELECT public.insert_udalost(
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) AS result
            """,
            (
                actor[:25],
                event[:30],
                "S",
                note[:50],
                client_version[:10],
                evidcislo,
                today,
                None,
                None,
            ),
        )
        row = cursor.fetchone()
        return bool(row and row["result"] is True)

    def _assert_lab(self, cursor: Any) -> None:
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
        assert_lab_identity(self._settings, identity)

    @staticmethod
    def _normalize_chip(raw: str) -> str:
        code = (raw or "").strip().upper()
        if not code or len(code) > 16:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Číslo čipu není platné.",
            )
        return code.zfill(16) if code.isalnum() and len(code) < 16 else code
