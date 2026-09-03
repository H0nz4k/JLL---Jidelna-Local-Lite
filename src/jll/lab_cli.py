from __future__ import annotations

import argparse
import ipaddress
import re

import psycopg

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DATABASE_PATTERN = re.compile(r"^jll_[A-Za-z0-9_]+$")


def verify_cluster(
    host: str,
    port: int,
    user: str,
    admin_database: str,
    expected_system_identifier: str,
    required_database: str,
) -> None:
    if host.lower().strip("[]") not in LOCAL_HOSTS:
        raise ValueError("LAB guard odmítá non-local host.")
    if not DATABASE_PATTERN.fullmatch(required_database):
        raise ValueError("LAB databáze musí začínat jll_.")
    if not expected_system_identifier.isdigit():
        raise ValueError("Chybí ověřený system_identifier.")
    with psycopg.connect(
        host=host,
        port=port,
        user=user,
        dbname=admin_database,
        connect_timeout=5,
        autocommit=True,
    ) as connection:
        row = connection.execute(
            """
            SELECT host(inet_server_addr()), inet_server_port(),
                   (SELECT system_identifier::text FROM pg_control_system()),
                   EXISTS(SELECT 1 FROM pg_database WHERE datname = %s)
            """,
            (required_database,),
        ).fetchone()
    if (
        row is None
        or not ipaddress.ip_address(row[0]).is_loopback
        or int(row[1]) != port
        or str(row[2]) != expected_system_identifier
        or row[3] is not True
    ):
        raise ValueError("Server-side LAB guard nebo databáze neprošly.")


def main() -> int:
    parser = argparse.ArgumentParser(description="JLL LAB CLI guard")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--user", required=True)
    parser.add_argument("--admin-database", required=True)
    parser.add_argument("--expected-system-identifier", required=True)
    parser.add_argument("--required-database", required=True)
    args = parser.parse_args()
    verify_cluster(
        args.host,
        args.port,
        args.user,
        args.admin_database,
        args.expected_system_identifier,
        args.required_database,
    )
    print(f"LAB guard OK: {args.host}:{args.port}/{args.required_database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
