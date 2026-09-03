from __future__ import annotations

import ipaddress
import os
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from psycopg import sql


@dataclass(frozen=True)
class LabDatabase:
    host: str
    port: int
    user: str
    name: str
    system_identifier: str

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} "
            f"user={self.user} dbname={self.name}"
        )

    def connect(self, *, autocommit: bool = True) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn, autocommit=autocommit)


def _admin_settings() -> tuple[str, int, str, str] | None:
    dsn = os.environ.get("JLL_LAB_ADMIN_DSN")
    if not dsn:
        return None
    values = psycopg.conninfo.conninfo_to_dict(dsn)
    host = values.get("host", "")
    port = int(values.get("port", 5432))
    user = values.get("user", "")
    database = values.get("dbname", "postgres")
    return host, port, user, database


@pytest.fixture()
def lab_database() -> LabDatabase:
    settings = _admin_settings()
    if settings is None:
        pytest.skip("JLL_LAB_ADMIN_DSN není nastaven.")
    host, port, user, admin_database = settings
    template = os.environ.get("JLL_LAB_TEMPLATE", "jll_demo_lab")
    expected_system_identifier = os.environ.get("JLL_LAB_SYSTEM_IDENTIFIER", "")
    if host.lower().strip("[]") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Integration fixture odmítla non-local PostgreSQL host.")
    if not template.startswith("jll_"):
        pytest.fail("LAB template databáze musí začínat jll_.")
    if not expected_system_identifier.isdigit():
        pytest.fail("JLL_LAB_SYSTEM_IDENTIFIER není bezpečně nastaven.")

    name = f"jll_test_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    admin_dsn = (
        f"host={host} port={port} user={user} dbname={admin_database}"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        identity = connection.execute(
            """
            SELECT
                current_database(),
                host(inet_server_addr()),
                inet_server_port(),
                (SELECT system_identifier::text FROM pg_control_system())
            """
        ).fetchone()
        assert identity is not None
        assert ipaddress.ip_address(identity[1]).is_loopback
        assert identity[3] == expected_system_identifier
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name),
                sql.Identifier(template),
            )
        )

    database = LabDatabase(host, port, user, name, expected_system_identifier)
    try:
        yield database
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
            )
