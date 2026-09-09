"""Unit: production environment guards and runtime paths."""

from __future__ import annotations

import pytest

from jll.config import LabConfig
from jll.lab_guard import (
    assert_configured_production,
    assert_production_identity,
    assert_runtime_identity,
)
from jll.orders.errors import OrderBusinessError
from jll.runtime_paths import resolve_runtime_paths


def _prod(**kwargs) -> LabConfig:
    values = dict(
        site_name="PROD SITE",
        site_id="PROD",
        instance_id="PROD-ST01",
        allowed_categories=frozenset({"KAT1"}),
        host="db.example.local",
        port=5432,
        database="jidelnasql",
        user="jll",
        environment="production",
        expected_system_identifier="1234567890123456789",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
    )
    values.update(kwargs)
    return LabConfig(**values)


def test_production_config_allows_non_loopback() -> None:
    cfg = _prod()
    assert cfg.environment == "production"
    assert_configured_production(cfg.order_settings)


def test_production_rejects_empty_system_id() -> None:
    with pytest.raises(ValueError):
        _prod(expected_system_identifier="")


def test_production_identity_mismatch_fail_closed() -> None:
    cfg = _prod()
    with pytest.raises(OrderBusinessError):
        assert_production_identity(
            cfg.order_settings,
            {
                "database_name": "jidelnasql",
                "system_identifier": "999",
                "server_address": "10.0.0.5",
            },
        )


def test_runtime_identity_dispatches_production() -> None:
    cfg = _prod()
    assert_runtime_identity(
        cfg.order_settings,
        {
            "database_name": "jidelnasql",
            "system_identifier": "1234567890123456789",
            "server_address": "10.0.0.5",
        },
    )


def test_resolve_runtime_paths_lab_default() -> None:
    paths = resolve_runtime_paths(force_lab=True)
    assert paths.environment_hint == "lab"
    assert paths.config_path.name == "lab.json"
