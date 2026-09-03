from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import keyring
from psycopg import Connection
from psycopg_pool import ConnectionPool
from keyring.errors import KeyringError

from .identity import IDENTIFIER_PATTERN
from .lab_guard import assert_configured_lab
from .orders.models import OrderServiceSettings

ConnectionFactory = Callable[[], Connection[Any]]


@dataclass(frozen=True, slots=True)
class LabConfig:
    site_name: str
    site_id: str
    instance_id: str
    allowed_categories: frozenset[str]
    host: str
    port: int
    database: str
    user: str
    environment: str
    expected_system_identifier: str
    business_timezone: str
    strict_config_lock: bool
    search_limit: int = 30
    reader_port: str | None = None
    reader_baud_rate: int = 19_200
    reader_line_end: str = "\r"

    def __post_init__(self) -> None:
        if not self.site_name.strip():
            raise ValueError("site_name nesmí být prázdný.")
        for name in ("site_id", "instance_id"):
            value = getattr(self, name)
            if not IDENTIFIER_PATTERN.fullmatch(value):
                raise ValueError(f"{name} nemá platný formát.")
        categories = frozenset(
            value.strip()
            for value in self.allowed_categories
            if isinstance(value, str) and value.strip()
        )
        if not categories or len(categories) != len(self.allowed_categories):
            raise ValueError("allowed_categories musí obsahovat platný scope.")
        if any(len(value) > 5 for value in categories):
            raise ValueError("Kategorie musí odpovídat varchar(5).")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("port musí být v rozsahu 1..65535.")
        if not self.user.strip():
            raise ValueError("user nesmí být prázdný.")
        if not 1 <= self.search_limit <= 100:
            raise ValueError("search_limit musí být v rozsahu 1..100.")
        if self.reader_port is not None:
            reader_port = self.reader_port.strip()
            if (
                not reader_port
                or len(reader_port) > 64
                or any(not char.isprintable() for char in reader_port)
            ):
                raise ValueError("reader_port nemá platný formát.")
            object.__setattr__(self, "reader_port", reader_port)
        if not 1 <= self.reader_baud_rate <= 4_000_000:
            raise ValueError("reader_baud_rate není platná.")
        if self.reader_line_end not in {"\r", "\n", "\r\n"}:
            raise ValueError("reader_line_end musí být CR, LF nebo CRLF.")
        object.__setattr__(self, "allowed_categories", categories)
        assert_configured_lab(self.order_settings)

    @property
    def order_settings(self) -> OrderServiceSettings:
        return OrderServiceSettings(
            environment=self.environment,
            db_host=self.host,
            db_name=self.database,
            expected_system_identifier=self.expected_system_identifier,
            business_timezone=self.business_timezone,
            strict_config_lock=self.strict_config_lock,
        )

    def connection_factory(self) -> Connection[Any]:
        return psycopg.connect(**self.connection_parameters())

    def connection_parameters(self) -> dict[str, Any]:
        password = os.environ.get("JLL_LAB_DB_PASSWORD")
        if password is None:
            try:
                password = keyring.get_password(
                    "JidelnaLocalLite",
                    f"{self.instance_id}:{self.user}",
                )
            except KeyringError:
                password = None
        parameters: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "connect_timeout": 5,
            "application_name": "jll-lab-gui",
        }
        if password is not None:
            parameters["password"] = password
        return parameters

    def create_pool(self) -> ConnectionPool:
        pool = ConnectionPool(
            kwargs={
                **self.connection_parameters(),
                "autocommit": True,
            },
            min_size=1,
            max_size=5,
            timeout=5,
            open=False,
            name="jll-lab-gui",
        )
        pool.open(wait=True, timeout=5)
        return pool


def load_lab_config(path: str | Path) -> LabConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"LAB config nelze bezpečně načíst: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Kořen LAB configu musí být objekt.")
    required = {
        "site_name",
        "site_id",
        "instance_id",
        "allowed_categories",
        "host",
        "port",
        "database",
        "user",
        "environment",
        "expected_system_identifier",
        "business_timezone",
        "strict_config_lock",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"V LAB configu chybí: {', '.join(missing)}")
    categories = raw["allowed_categories"]
    if not isinstance(categories, list):
        raise ValueError("allowed_categories musí být seznam.")
    if not isinstance(raw["strict_config_lock"], bool):
        raise ValueError("strict_config_lock musí být boolean.")
    return LabConfig(
        site_name=str(raw["site_name"]),
        site_id=str(raw["site_id"]),
        instance_id=str(raw["instance_id"]),
        allowed_categories=frozenset(categories),
        host=str(raw["host"]),
        port=int(raw["port"]),
        database=str(raw["database"]),
        user=str(raw["user"]),
        environment=str(raw["environment"]),
        expected_system_identifier=str(raw["expected_system_identifier"]),
        business_timezone=str(raw["business_timezone"]),
        strict_config_lock=raw["strict_config_lock"],
        search_limit=int(raw.get("search_limit", 30)),
        reader_port=(
            str(raw["reader_port"])
            if raw.get("reader_port") is not None
            else None
        ),
        reader_baud_rate=int(raw.get("reader_baud_rate", 19_200)),
        reader_line_end=str(raw.get("reader_line_end", "\r")),
    )


def save_lab_config(config: LabConfig, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "site_name": config.site_name,
        "site_id": config.site_id,
        "instance_id": config.instance_id,
        "allowed_categories": sorted(config.allowed_categories),
        "host": config.host,
        "port": config.port,
        "database": config.database,
        "user": config.user,
        "environment": config.environment,
        "expected_system_identifier": config.expected_system_identifier,
        "business_timezone": config.business_timezone,
        "strict_config_lock": config.strict_config_lock,
        "search_limit": config.search_limit,
        "reader_port": config.reader_port,
        "reader_baud_rate": config.reader_baud_rate,
        "reader_line_end": config.reader_line_end,
    }
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
