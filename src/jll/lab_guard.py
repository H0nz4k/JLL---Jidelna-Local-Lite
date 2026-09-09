from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any, Protocol

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LabTargetSettings(Protocol):
    environment: str
    db_host: str
    db_name: str
    expected_system_identifier: str


def assert_configured_lab(settings: LabTargetSettings) -> None:
    from .orders.errors import ErrorCode, OrderBusinessError

    host = settings.db_host.strip().lower().strip("[]")
    database = settings.db_name.strip()
    if (
        settings.environment.strip().lower() != "lab"
        or host not in LOCAL_HOSTS
        or not database.startswith("jll_")
    ):
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Aplikace je povolena pouze pro lokální LAB databázi.",
        )


def assert_configured_production(settings: LabTargetSettings) -> None:
    """Production guard — bez loopback/`jll_` požadavků; System ID zůstává."""

    from .orders.errors import ErrorCode, OrderBusinessError

    if settings.environment.strip().lower() != "production":
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Konfigurace není označená jako production.",
        )
    if not settings.db_host.strip():
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Production vyžaduje neprázdný db host.",
        )
    if not settings.db_name.strip():
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Production vyžaduje neprázdný název databáze.",
        )
    ident = settings.expected_system_identifier.strip()
    if not ident or not ident.isdigit():
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Production vyžaduje číselný expected_system_identifier.",
        )


def assert_configured_environment(settings: LabTargetSettings) -> None:
    env = settings.environment.strip().lower()
    if env == "lab":
        assert_configured_lab(settings)
        return
    if env == "production":
        assert_configured_production(settings)
        return
    from .orders.errors import ErrorCode, OrderBusinessError

    raise OrderBusinessError(
        ErrorCode.LAB_GUARD_FAILED,
        "Nepodporovaný environment (povolené: lab, production).",
    )


def assert_lab_identity(
    settings: LabTargetSettings,
    identity: Mapping[str, Any],
) -> None:
    from .orders.errors import ErrorCode, OrderBusinessError

    assert_configured_lab(settings)
    actual_name = str(identity.get("database_name") or "")
    address_text = str(identity.get("server_address") or "")
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError as exc:
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Serverová adresa LAB databáze není ověřitelná.",
        ) from exc
    if (
        not address.is_loopback
        or not actual_name.startswith("jll_")
        or actual_name != settings.db_name.strip()
        or str(identity.get("system_identifier") or "")
        != settings.expected_system_identifier
    ):
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Připojená databáze nesplňuje lokální LAB guard.",
        )


def assert_production_identity(
    settings: LabTargetSettings,
    identity: Mapping[str, Any],
) -> None:
    from .orders.errors import ErrorCode, OrderBusinessError

    assert_configured_production(settings)
    actual_name = str(identity.get("database_name") or "")
    if actual_name != settings.db_name.strip():
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "Připojená databáze neodpovídá production konfiguraci.",
        )
    if (
        str(identity.get("system_identifier") or "")
        != settings.expected_system_identifier
    ):
        raise OrderBusinessError(
            ErrorCode.LAB_GUARD_FAILED,
            "System Identifier neodpovídá production pinu.",
        )


def assert_runtime_identity(
    settings: LabTargetSettings,
    identity: Mapping[str, Any],
) -> None:
    env = settings.environment.strip().lower()
    if env == "production":
        assert_production_identity(settings, identity)
        return
    assert_lab_identity(settings, identity)
