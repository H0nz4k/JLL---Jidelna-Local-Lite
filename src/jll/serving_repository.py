"""Tenká DB vrstva pro výdejní API JídelnaSQL (nacti_cip / stravy / odber).

Write (`zapis_odber`) zůstává za explicitním voláním služby; žádný Python
fallback. Scope kategorií musí ověřit volající service před write.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .orders.repository import DAY_COLUMNS

LOGGER = logging.getLogger(__name__)

# Legacy `nacti_cip` očekává krátký token; delší pseudo-UID může spadnout
# na substring chybu uvnitř PL/pgSQL (doloženo na LAB).
_CHIP_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


@dataclass(frozen=True, slots=True)
class ChipIdentityRow:
    evidcislo: int
    name: str
    credit_today: Decimal
    chip_state: str
    category: str
    meal_norm: str


@dataclass(frozen=True, slots=True)
class MealReadyRow:
    raw: Mapping[str, Any]


class ServingRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def lab_identity(self) -> Mapping[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    host(inet_server_addr()) AS server_address,
                    inet_server_port() AS server_port,
                    (SELECT system_identifier::text FROM pg_control_system())
                        AS system_identifier,
                    version() AS server_version
                """
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Databázovou identitu nelze ověřit.")
        return row

    def nacti_cip(self, chip_uid: str) -> ChipIdentityRow | None:
        token = chip_uid.strip()
        if not token:
            raise ValueError("chip_uid nesmí být prázdný.")
        if not _CHIP_TOKEN_RE.fullmatch(token):
            LOGGER.info("nacti_cip odmítl neplatný tvar čipu len=%s", len(token))
            return None
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM public.nacti_cip(%s)",
                    (token,),
                )
                row = cursor.fetchone()
        except psycopg.Error as exc:
            LOGGER.warning(
                "nacti_cip selhalo sqlstate=%s",
                getattr(exc, "sqlstate", None),
            )
            return None
        if row is None or row.get("pevidcislo") is None:
            return None
        return ChipIdentityRow(
            evidcislo=int(row["pevidcislo"]),
            name=str(row["pjmeno"] or ""),
            credit_today=Decimal(str(row["kredit_dnes"] or 0)),
            chip_state=str(row["stav_cipu"] or ""),
            category=str(row["kategorie_stravnika"] or ""),
            meal_norm=str(row["norma_stravy"] or ""),
        )

    def stravy_k_vydeji(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        if evidcislo <= 0:
            raise ValueError("evidcislo musí být kladné.")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM public.stravy_k_vydeji(%s)",
                (evidcislo,),
            )
            rows = cursor.fetchall()
        return tuple(MealReadyRow(raw=dict(row)) for row in rows)

    def stravy_k_manualni_odber(self, evidcislo: int) -> tuple[MealReadyRow, ...]:
        """Dnešní přihlášky k ručnímu odběru bez filtru výdejního okna.

        Čipový výdej dál používá ``stravy_k_vydeji`` (včetně ``vydejod``/``vydejdo``).
        Ruční odběr z karty strávníka záměrně neomezuje čas ani výdejní ``relace``.
        """

        if evidcislo <= 0:
            raise ValueError("evidcislo musí být kladné.")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT CURRENT_DATE AS today")
            today = cursor.fetchone()
            if today is None or today.get("today") is None:
                raise RuntimeError("CURRENT_DATE nelze načíst.")
            day_date = today["today"]
        day_num = int(day_date.day)
        day_col = sql.Identifier(DAY_COLUMNS[day_num - 1])
        query = sql.SQL(
            """
            SELECT
                btrim(p.typsluzby)::character varying AS typ_stravy,
                p.{day}::character varying AS menu,
                CASE
                    WHEN COALESCE(substr(o.odebral, %(day_num)s, 1), '') = '' THEN 'X'
                    WHEN substr(o.odebral, %(day_num)s, 1) = '.' THEN 'X'
                    ELSE substr(o.odebral, %(day_num)s, 1)
                END::character varying AS odebrano,
                (
                    COALESCE(substr(o.odebral, %(day_num)s, 1), '') = ''
                    OR substr(o.odebral, %(day_num)s, 1) <> 'O'
                ) AS vydat,
                NULL::integer AS vydejni_misto,
                p.id AS id_prihlasky
            FROM public.prihlas AS p
            LEFT JOIN public.odebral AS o
              ON o.stravnik = p.stravnik
             AND o.rok = p.rok
             AND o.mesic = p.mesic
             AND lower(btrim(o.typstravy)) = lower(btrim(p.typsluzby))
             AND o.poradiprihl = p.poradiprihl
            WHERE p.rok = %(year)s
              AND p.mesic = %(month)s
              AND p.stravnik = %(evidcislo)s
              AND p.{day} ~ '^[1-9]$'
            ORDER BY btrim(p.typsluzby), p.{day}, p.id
            """
        ).format(day=day_col)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                query,
                {
                    "day_num": day_num,
                    "year": int(day_date.year),
                    "month": int(day_date.month),
                    "evidcislo": evidcislo,
                },
            )
            rows = cursor.fetchall()
        return tuple(MealReadyRow(raw=dict(row)) for row in rows)

    def zapis_odber(self, prihlaska_id: int) -> bool:
        if prihlaska_id <= 0:
            raise ValueError("id_prihlasky musí být kladné.")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.zapis_odber(%s)",
                (prihlaska_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return False
        return bool(row[0])
