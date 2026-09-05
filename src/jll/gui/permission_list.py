"""Sdílený seznam oprávnění s českými popisky.

Na Qt hranici ukládá jen `permission.value` (str). Při čtení vždy
rekonstruuje `Permission`, protože PySide z UserRole vrací string.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from ..permission_catalog import (
    GROUP_ORDER,
    DEFAULT_OPERATOR_PERMISSIONS,
    permissions_in_group,
)
from ..policy import Permission


def populate_permission_list(
    widget: QListWidget,
    *,
    selected: frozenset[Permission] | None = None,
    include_admin: bool = False,
    defaults: frozenset[Permission] | None = DEFAULT_OPERATOR_PERMISSIONS,
) -> None:
    """Naplní checklist skupinami a českými názvy."""

    widget.clear()
    chosen = selected if selected is not None else (defaults or frozenset())
    for group in GROUP_ORDER:
        items = permissions_in_group(group, include_admin=include_admin)
        if not items:
            continue
        header = QListWidgetItem(group)
        header.setFlags(Qt.ItemIsEnabled)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        widget.addItem(header)
        for meta in items:
            item = QListWidgetItem(f"  {meta.title_cs}")
            item.setToolTip(meta.description_cs)
            item.setData(Qt.UserRole, meta.permission.value)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(
                Qt.Checked if meta.permission in chosen else Qt.Unchecked
            )
            widget.addItem(item)


def selected_permissions_from_list(widget: QListWidget) -> frozenset[Permission]:
    """Vždy vrací `frozenset[Permission]`, nikdy frozenset[str]."""

    result: set[Permission] = set()
    for index in range(widget.count()):
        item = widget.item(index)
        raw = item.data(Qt.UserRole)
        if raw is None or item.checkState() != Qt.Checked:
            continue
        result.add(Permission(str(raw)))
    return frozenset(result)


def set_checked_permissions(
    widget: QListWidget,
    permissions: frozenset[Permission],
) -> None:
    wanted = {item.value for item in permissions}
    for index in range(widget.count()):
        item = widget.item(index)
        raw = item.data(Qt.UserRole)
        if raw is None:
            continue
        item.setCheckState(Qt.Checked if str(raw) in wanted else Qt.Unchecked)


def permission_list_widget(
    parent: QWidget | None = None,
    *,
    include_admin: bool = False,
    defaults: frozenset[Permission] | None = DEFAULT_OPERATOR_PERMISSIONS,
) -> QListWidget:
    widget = QListWidget(parent)
    populate_permission_list(
        widget,
        include_admin=include_admin,
        defaults=defaults,
    )
    return widget
