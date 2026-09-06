"""Legacy public.uzivatel repository (read + characterized insert)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from psycopg.rows import dict_row

LOGGER = logging.getLogger(__name__)
USER_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


@dataclass(frozen=True, slots=True)
class LegacyUserRow:
    code: str
    display_name: str
    is_admin: bool
    typ: str | None
    disabled: bool
    prava: str
    prava1: str
    has_password: bool
    #: Legacy integer id (`public.uzivatel.id`); None pokud řádek nemá id.
    legacy_id: int | None = None


class LegacyUserRepository:
    """Forenzně: PK(uzivatel); heslo='' = smazané heslo (uzivatelform.pas).

    Alokace `id`: Delphi UI volá `test_new_user_id` (max(id)+1). Sequence
    `new_user_id()` / `uzivatel_id_seq` může být pozadu za MAX(id) — proto JLL
    používá stejný max+1 kontrakt jako legacy formulář.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def list_users(self, *, include_disabled: bool = True) -> tuple[LegacyUserRow, ...]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT uzivatel, COALESCE(jmeno, '') AS jmeno,
                       COALESCE(is_admin, false) AS is_admin,
                       typ, COALESCE(disabled, false) AS disabled,
                       COALESCE(prava, '') AS prava,
                       COALESCE(prava1, '') AS prava1,
                       COALESCE(heslo, '') AS heslo,
                       id
                FROM public.uzivatel
                ORDER BY uzivatel
                """
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            disabled = bool(row["disabled"])
            if disabled and not include_disabled:
                continue
            heslo = str(row["heslo"] or "")
            raw_id = row["id"]
            result.append(
                LegacyUserRow(
                    code=str(row["uzivatel"]).strip(),
                    display_name=str(row["jmeno"] or "").strip() or str(row["uzivatel"]),
                    is_admin=bool(row["is_admin"]),
                    typ=str(row["typ"]).strip() if row["typ"] else None,
                    disabled=disabled,
                    prava=str(row["prava"] or ""),
                    prava1=str(row["prava1"] or ""),
                    has_password=bool(heslo),
                    legacy_id=int(raw_id) if raw_id is not None else None,
                )
            )
        return tuple(result)

    def get_user(self, code: str) -> LegacyUserRow | None:
        code = code.strip()
        for user in self.list_users(include_disabled=True):
            if user.code.casefold() == code.casefold():
                return user
        return None

    def allocate_legacy_id(self) -> int:
        """Unikátní `uzivatel.id` dle legacy `test_new_user_id`."""

        with self.connection.cursor() as cursor:
            cursor.execute("SELECT public.test_new_user_id(0)")
            row = cursor.fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("Nelze alokovat legacy uzivatel.id.")
        value = int(row[0])
        if value <= 0:
            raise RuntimeError("Alokované legacy uzivatel.id je neplatné.")
        return value

    def create_user_from_template(
        self,
        *,
        code: str,
        display_name: str,
        template: LegacyUserRow,
    ) -> LegacyUserRow:
        """Insert dle uzivatelform BitBtn9 + dědění prava/prava1/typ/role z VED.

        heslo='' = bez hesla (BitBtn2 clear). Nikdy nekopíruje template.heslo,
        is_admin ani SUP secret. Role z `public.user_role` se klonují podle
        `template.legacy_id`, pokud je dostupný.
        """

        code = code.strip().upper()
        display_name = display_name.strip()
        if not USER_CODE_RE.fullmatch(code):
            raise ValueError("Kód uživatele nemá platný formát.")
        if not display_name or len(display_name) > 80:
            raise ValueError("Jméno uživatele nemá platný formát.")
        if template.is_admin:
            raise ValueError("Šablona pro běžného uživatele nesmí být admin.")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT 1 FROM public.uzivatel WHERE btrim(uzivatel)=%s",
                (code,),
            )
            if cursor.fetchone() is not None:
                raise ValueError(f"Uživatel {code} už existuje.")
            legacy_id = self.allocate_legacy_id()
            cursor.execute(
                """
                INSERT INTO public.uzivatel (
                  uzivatel, jmeno, heslo, prava, prava1, is_admin, typ, disabled, id
                ) VALUES (
                  %s, %s, '', %s, %s, false, %s, false, %s
                )
                RETURNING uzivatel, COALESCE(jmeno,'') AS jmeno,
                          COALESCE(is_admin,false) AS is_admin, typ,
                          COALESCE(disabled,false) AS disabled,
                          COALESCE(prava,'') AS prava,
                          COALESCE(prava1,'') AS prava1,
                          COALESCE(heslo,'') AS heslo,
                          id
                """,
                (
                    code,
                    display_name,
                    template.prava,
                    template.prava1,
                    template.typ,
                    legacy_id,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            if template.legacy_id is not None:
                cursor.execute(
                    """
                    INSERT INTO public.user_role (user_id, role_id)
                    SELECT %s, role_id
                    FROM public.user_role
                    WHERE user_id = %s
                    ON CONFLICT DO NOTHING
                    """,
                    (legacy_id, template.legacy_id),
                )
        LOGGER.info(
            "legacy user created code=%s id=%s template=%s",
            code,
            legacy_id,
            template.code,
        )
        return LegacyUserRow(
            code=str(row["uzivatel"]).strip(),
            display_name=str(row["jmeno"] or "").strip() or code,
            is_admin=bool(row["is_admin"]),
            typ=str(row["typ"]).strip() if row["typ"] else None,
            disabled=bool(row["disabled"]),
            prava=str(row["prava"] or ""),
            prava1=str(row["prava1"] or ""),
            has_password=bool(row["heslo"]),
            legacy_id=int(row["id"]) if row["id"] is not None else legacy_id,
        )


def copy_ved_access_fields(ved: LegacyUserRow) -> tuple[str, str, str | None]:
    return ved.prava, ved.prava1, ved.typ
