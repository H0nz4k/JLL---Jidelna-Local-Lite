"""Production-aware Flet write gate UI states."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from jll.config import JllConfig
from jll.flet_ui.state import ActionBlockReason, AppState
from jll.policy import Permission
from jll.write_gates import PRODUCTION_DISABLED_MESSAGE


def _prod_config() -> JllConfig:
    return JllConfig(
        site_name="PROD",
        site_id="PROD",
        instance_id="PROD-01",
        allowed_categories=frozenset({"KAT2"}),
        host="db.example.local",
        port=5432,
        database="jidelna",
        user="jll",
        environment="production",
        expected_system_identifier="1000000000000000001",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
    )


def test_production_gui_write_gates_are_write_gate_blocked() -> None:
    state = AppState(config_path=Path("x"), identity_path=Path("y"), config=_prod_config())
    business = MagicMock()
    business.current_policy.return_value.permissions = frozenset(Permission)
    state.business = business
    for getter in (
        state.diner_create_state,
        state.diner_edit_state,
        state.chip_assign_state,
        state.chip_return_state,
        state.chip_block_state,
        state.chip_lost_state,
        state.chip_unblock_state,
        state.payments_post_state,
        state.serving_pickup_state,
    ):
        availability = getter()
        assert availability.allowed is False
        assert availability.reason is ActionBlockReason.WRITE_GATE
        assert availability.message == PRODUCTION_DISABLED_MESSAGE
