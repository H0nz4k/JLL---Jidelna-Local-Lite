"""Permission / write-gate presentation helpers."""

from __future__ import annotations

from ...permission_catalog import PERMISSION_CATALOG, permission_title
from ...policy import Permission
from ...write_gates import WriteGate
from ..state import ActionAvailability, ActionBlockReason


def czech_permission_title(permission: Permission) -> str:
    return permission_title(permission)


def catalog_groups() -> dict[str, list[tuple[Permission, str, str]]]:
    groups: dict[str, list[tuple[Permission, str, str]]] = {}
    for item in PERMISSION_CATALOG:
        groups.setdefault(item.group, []).append(
            (item.permission, item.title_cs, item.description_cs)
        )
    return groups


def disabled_hint(state: ActionAvailability) -> str:
    if state.allowed:
        return ""
    return state.message


def gate_badge(gate: WriteGate) -> str | None:
    return gate.badge


__all__ = [
    "ActionAvailability",
    "ActionBlockReason",
    "catalog_groups",
    "czech_permission_title",
    "disabled_hint",
    "gate_badge",
]
