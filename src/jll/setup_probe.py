"""Read-only probe pro Setup Wizard: provozovna, stanice, kategorie.

Nezapisuje do databáze. Create stanice zde není — kontrakt není doložen.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

import psycopg

from .identity import IDENTIFIER_PATTERN

_SITE_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class StationOption:
    """Jedna platná stanice z `public.stanice`.

    Business identifikátor pro JLL je `nazev` (legacy `STANICE:`), nikoli PK.
    """

    station_id: int
    name: str

    @property
    def usable_as_instance_id(self) -> bool:
        return bool(IDENTIFIER_PATTERN.fullmatch(self.name))


@dataclass(frozen=True, slots=True)
class CategoryOption:
    """Kategorie strávníků: zkratka + volitelný název z `public.kategor`."""

    code: str
    name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.code} — {self.name}" if self.name else self.code


@dataclass(frozen=True, slots=True)
class DatabaseProbe:
    system_identifier: str
    categories: tuple[str, ...]
    subject_name: str | None
    stations: tuple[StationOption, ...]
    subject_missing: bool = False
    category_options: tuple[CategoryOption, ...] = ()


def derive_site_id(site_name: str) -> str:
    """Interní site_id z názvu provozovny; hospodářka jej nezadává."""

    cleaned = _SITE_ID_SAFE.sub("", site_name.upper().replace(" ", "-"))
    cleaned = cleaned.strip("-_")
    if not cleaned:
        return "LAB"
    return cleaned[:20]


def list_category_options(connection: psycopg.Connection) -> tuple[CategoryOption, ...]:
    """Katalog kategorií z `public.kategor` (označení + název)."""

    rows = connection.execute(
        """
        SELECT btrim(k.oznaceni) AS code,
               NULLIF(btrim(k.nazev), '') AS name
        FROM public.kategor AS k
        WHERE NULLIF(btrim(k.oznaceni), '') IS NOT NULL
        ORDER BY lower(btrim(k.oznaceni))
        """
    ).fetchall()
    return tuple(
        CategoryOption(
            code=str(row[0]).strip(),
            name=str(row[1]).strip() if row[1] else None,
        )
        for row in rows
        if row[0] and str(row[0]).strip()
    )


def probe_lab_database(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> DatabaseProbe:
    """Ověří lokální LAB DB a načte NameSubject, stanice a kategorie."""

    normalized_host = host.lower().strip("[]")
    if normalized_host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LAB setup povoluje pouze loopback host.")
    if not database.startswith("jll_"):
        raise ValueError("LAB databáze musí začínat jll_.")
    return _probe_database(
        host=normalized_host,
        port=port,
        database=database,
        user=user,
        password=password,
        require_loopback=True,
    )


def probe_production_database(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> DatabaseProbe:
    """Read-only production probe — hostname/IP, bez jll_ prefixu."""

    normalized_host = host.strip()
    if not normalized_host:
        raise ValueError("Host nesmí být prázdný.")
    db = database.strip()
    if not db:
        raise ValueError("Název databáze nesmí být prázdný.")
    return _probe_database(
        host=normalized_host,
        port=port,
        database=db,
        user=user,
        password=password,
        require_loopback=False,
    )


def _probe_database(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    require_loopback: bool,
) -> DatabaseProbe:
    parameters: dict[str, object] = {
        "host": host,
        "port": port,
        "dbname": database,
        "user": user,
        "connect_timeout": 5,
        "autocommit": True,
    }
    if password:
        parameters["password"] = password
    with psycopg.connect(**parameters) as connection:
        identity = connection.execute(
            """
            SELECT current_database(), host(inet_server_addr()),
                   (SELECT system_identifier::text FROM pg_control_system())
            """
        ).fetchone()
        if identity is None:
            raise ValueError("Identitu databáze nelze načíst.")
        if identity[0] != database:
            raise ValueError("Připojená databáze neodpovídá požadavku.")
        if require_loopback:
            try:
                if not ipaddress.ip_address(str(identity[1])).is_loopback:
                    raise ValueError("Připojená databáze není lokální LAB.")
            except ValueError as exc:
                if "Připojená databáze" in str(exc):
                    raise
                raise ValueError("Serverovou adresu nelze ověřit jako loopback.") from exc

        subject_row = connection.execute(
            """
            SELECT NULLIF(btrim(hodnota), '') AS subject_name
            FROM public.parametry
            WHERE lower(btrim(sekce)) = lower('BACKUP')
              AND lower(btrim(parametr)) = lower('NameSubject')
            LIMIT 1
            """
        ).fetchone()
        subject_name = (
            str(subject_row[0]).strip()
            if subject_row is not None and subject_row[0]
            else None
        )

        station_rows = connection.execute(
            """
            SELECT id, btrim(nazev) AS nazev
            FROM public.stanice
            WHERE COALESCE(platna, true) = true
              AND NULLIF(btrim(nazev), '') IS NOT NULL
            ORDER BY lower(btrim(nazev)), id
            """
        ).fetchall()
        stations = tuple(
            StationOption(int(row[0]), str(row[1]).strip().upper())
            for row in station_rows
            if str(row[1]).strip()
        )

        category_options = list_category_options(connection)
    categories = tuple(item.code for item in category_options)
    if not categories:
        raise ValueError("Databáze neobsahuje volitelné kategorie.")
    return DatabaseProbe(
        system_identifier=str(identity[2]),
        categories=categories,
        subject_name=subject_name,
        stations=stations,
        subject_missing=subject_name is None,
        category_options=category_options,
    )
