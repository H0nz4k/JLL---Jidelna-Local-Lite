"""Shared Flet app state (no SQL / business rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..business_session import BusinessSession
from ..config import LabConfig
from ..identity_store import IdentityStore
from ..policy import Permission
from ..read_models import DinerSummary
from ..sup_secret import SupSecretStore
from ..write_gates import CHIP_WRITE_GATES, DINER_WRITE_GATES, WriteGate
from .routes import Route
from .theme import TextScale


class ActionBlockReason(Enum):
    ALLOWED = "allowed"
    NO_PERMISSION = "no_permission"
    WRITE_GATE = "write_gate"
    MISSING_HW = "missing_hw"
    BUSINESS_RULE = "business_rule"


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    allowed: bool
    reason: ActionBlockReason
    message: str


def action_state(
    *,
    has_permission: bool,
    gate: WriteGate | None = None,
    missing_hw: bool = False,
    business_blocked: bool = False,
    business_message: str = "",
) -> ActionAvailability:
    if not has_permission:
        return ActionAvailability(
            False,
            ActionBlockReason.NO_PERMISSION,
            "Nemáte oprávnění k této akci.",
        )
    if missing_hw:
        return ActionAvailability(
            False,
            ActionBlockReason.MISSING_HW,
            "Chybí hardwarová konfigurace nebo zařízení.",
        )
    if gate is not None and not gate.enabled:
        return ActionAvailability(False, ActionBlockReason.WRITE_GATE, gate.tooltip)
    if business_blocked:
        return ActionAvailability(
            False,
            ActionBlockReason.BUSINESS_RULE,
            business_message or "Akci nelze provést.",
        )
    return ActionAvailability(True, ActionBlockReason.ALLOWED, "")


@dataclass
class AppState:
    config_path: Path
    identity_path: Path
    config: LabConfig | None = None
    identity_store: IdentityStore | None = None
    business: BusinessSession | None = None
    pool: Any = None
    read_service: Any = None
    application_service: Any = None
    chip_reader: Any = None
    route: Route = Route.DINERS
    text_scale: TextScale = TextScale.NORMAL
    search_query: str = ""
    diner_results: list[DinerSummary] = field(default_factory=list)
    selected_evidcislo: int | None = None
    selected_day: date | None = None
    status_message: str = ""
    needs_setup: bool = False
    diagnostics: Any = None

    def has_perm(self, permission: Permission) -> bool:
        if self.business is None:
            return False
        return permission in self.business.current_policy().permissions

    def diner_create_state(self) -> ActionAvailability:
        return action_state(
            has_permission=self.has_perm(Permission.DINERS_CREATE),
            gate=DINER_WRITE_GATES["create"],
        )

    def diner_edit_state(self) -> ActionAvailability:
        return action_state(
            has_permission=self.has_perm(Permission.DINERS_EDIT),
            gate=DINER_WRITE_GATES["edit_personal"],
        )

    def chip_assign_state(self) -> ActionAvailability:
        return action_state(
            has_permission=self.has_perm(Permission.CHIPS_ASSIGN),
            gate=CHIP_WRITE_GATES["assign"],
        )


RefreshCallback = Callable[[], None]
