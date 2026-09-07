"""DB repository pro create/edit strávníka."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from psycopg.rows import dict_row

from .diner_models import PERSONAL_EDIT_FIELDS
from .legacy_pin import legacy_get_pin
from .orders.errors import ErrorCode, OrderBusinessError


class DinerRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def lab_identity(self) -> Mapping[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    host(inet_server_addr()) AS server_address,
                    system_identifier::text AS system_identifier
                FROM pg_control_system()
                """
            )
            row = cursor.fetchone()
        assert row is not None
        return row

    def period_am(self) -> tuple[int, int]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT btrim(parametr) AS parametr,
                       NULLIF(btrim(hodnota), '') AS hodnota
                FROM public.parametry
                WHERE lower(btrim(sekce)) = lower('BACKUP')
                  AND lower(btrim(parametr)) IN (
                    lower('TentoMesic'), lower('TentoRok'),
                    lower('DalsiMesic')
                  )
                """
            )
            values = {
                str(row["parametr"]).casefold(): str(row["hodnota"])
                for row in cursor.fetchall()
                if row["hodnota"] is not None
            }
        try:
            month = int(values["tentomesic"])
            year = int(values["tentorok"])
        except (KeyError, ValueError) as exc:
            raise OrderBusinessError(
                ErrorCode.LAB_GUARD_FAILED,
                "Účetní období (TentoMesic/TentoRok) nelze bezpečně načíst.",
            ) from exc
        return year, month

    def next_period(self, year: int, month: int) -> tuple[int, int]:
        if month == 12:
            return year + 1, 1
        return year, month + 1

    def allocate_evidcislo(self) -> int:
        with self.connection.cursor() as cursor:
            # JLL-only serializace; legacy pridel_cislo_stravnika lock nesdílí.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('jll_create_evidcislo'))")
            cursor.execute("SELECT public.pridel_cislo_stravnika(1)")
            row = cursor.fetchone()
        if row is None or row[0] is None:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Allocator evidcislo nevrátil číslo.",
            )
        return int(row[0])

    def default_payment_method(self, kategorie: str) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NULLIF(btrim(zpusobplatby::text), '')
                FROM public.kategor
                WHERE btrim(oznaceni) = %s
                """,
                (kategorie,),
            )
            row = cursor.fetchone()
        if row and row[0]:
            return str(row[0])[:10]
        return "1"

    def insert_stravnik(
        self,
        *,
        evidcislo: int,
        jmeno: str,
        kategorie: str,
        trida: str,
        zpusobplatby: str,
    ) -> None:
        pin = legacy_get_pin(jmeno, "", evidcislo)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.stravnik (
                    evidcislo, jmeno, kategorie, trida,
                    zpusobplatby, hromadny, deleted, stav,
                    platitpm, preplatekmm, platbabm, uctpreplatek,
                    platbatm, platittm, preplatek_sluzby, pin
                ) VALUES (
                    %s, %s, %s, NULLIF(%s, ''),
                    %s, false, false, 'A',
                    0, 0, 0, 0,
                    0, 0, 0, %s
                )
                """,
                (
                    evidcislo,
                    jmeno,
                    kategorie,
                    trida.strip(),
                    zpusobplatby,
                    pin,
                ),
            )

    def dopln_obvykle_kategor(
        self, year: int, month: int, evidcislo: int, kategorie: str
    ) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT public.doplnobvyklestravnikakategor(%s, %s, %s, %s)
                """,
                (year, month, evidcislo, kategorie),
            )
            row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 999

    def rozpis_vytvoren(self, month: int) -> bool:
        key = f"RozpisVytvoren{int(month):02d}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT NULLIF(btrim(hodnota), '')
                FROM public.parametry
                WHERE lower(btrim(sekce)) = lower('BACKUP')
                  AND lower(btrim(parametr)) = lower(%s)
                """,
                (key,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT NULLIF(btrim(hodnota), '')
                    FROM public.parametry
                    WHERE lower(btrim(parametr)) = lower(%s)
                    """,
                    (key,),
                )
                row = cursor.fetchone()
        return bool(row and str(row[0]).upper().startswith("A"))

    def dopln_rozpis(self, year: int, month: int, evidcislo: int, kategorie: str) -> None:
        if not self.rozpis_vytvoren(month):
            return
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT btrim(typstravy) AS typstravy
                FROM public.stravobv
                WHERE kodstravnika = %s
                """,
                (evidcislo,),
            )
            types = [str(row["typstravy"]) for row in cursor.fetchall()]
            for typ in types:
                cursor.execute(
                    """
                    SELECT 1 FROM public.prihlas
                    WHERE stravnik = %s AND rok = %s AND mesic = %s
                      AND lower(btrim(typsluzby)) = lower(%s)
                    LIMIT 1
                    """,
                    (evidcislo, year, month, typ),
                )
                if cursor.fetchone() is not None:
                    continue
                cursor.execute(
                    """
                    SELECT public.nastavprihlasdleobvykle(
                        %s, %s, %s, %s, false, 1
                    )
                    """,
                    (year, month, evidcislo, typ),
                )

    def insert_audit(
        self,
        *,
        actor: str,
        event: str,
        note: str,
        client_version: str,
        evidcislo: int,
        event_type: str = "S",
    ) -> bool:
        with self.connection.cursor(row_factory=dict_row) as cursor:
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
                    event[:30],
                    event_type[:1],
                    note[:50],
                    client_version[:10],
                    evidcislo,
                    None,
                    None,
                ),
            )
            row = cursor.fetchone()
        return bool(row and row["result"] is True)

    def fetch_for_update(self, evidcislo: int) -> Mapping[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT evidcislo, btrim(jmeno) AS jmeno,
                       btrim(kategorie) AS kategorie,
                       COALESCE(btrim(trida), '') AS trida,
                       stav, COALESCE(deleted, false) AS deleted,
                       updated_dt,
                       ulice, psc, mesto, poznamka, poznamkaam, poznamkabm,
                       email, vzkaz, stredisko, datumnarozeni
                FROM public.stravnik
                WHERE evidcislo = %s
                FOR UPDATE
                """,
                (evidcislo,),
            )
            return cursor.fetchone()

    def update_personal(
        self,
        evidcislo: int,
        fields: Mapping[str, str | date | None],
    ) -> None:
        unknown = set(fields) - PERSONAL_EDIT_FIELDS
        if unknown:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                f"Pole mimo whitelist: {', '.join(sorted(unknown))}",
            )
        if not fields:
            raise OrderBusinessError(
                ErrorCode.POSTCONDITION_FAILED,
                "Žádná pole k úpravě.",
            )
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = %s")
            if key == "jmeno" and isinstance(value, str):
                values.append(value.upper())
            elif key == "trida" and isinstance(value, str):
                values.append(value.upper() if value else None)
            elif isinstance(value, str):
                values.append(value if value.strip() else None)
            else:
                values.append(value)
        values.append(evidcislo)
        sql = (
            f"UPDATE public.stravnik SET {', '.join(assignments)} "
            "WHERE evidcislo = %s"
        )
        with self.connection.cursor() as cursor:
            cursor.execute(sql, values)

    def count_stravobv(self, evidcislo: int) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM public.stravobv WHERE kodstravnika = %s",
                (evidcislo,),
            )
            row = cursor.fetchone()
        return int(row[0]) if row else 0
