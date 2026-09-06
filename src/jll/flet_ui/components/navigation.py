"""Left navigation."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..routes import NAV_ITEMS, Route


def navigation_rail(active: Route, on_change) -> ft.Control:
    destinations = []
    selected = 0
    for index, (route, label, icon) in enumerate(NAV_ITEMS):
        destinations.append(
            ft.NavigationRailDestination(
                icon=icon,
                selected_icon=icon,
                label=label,
            )
        )
        if route == active:
            selected = index

    def _changed(e: ft.ControlEvent) -> None:
        route = NAV_ITEMS[int(e.control.selected_index)][0]
        on_change(route)

    return ft.NavigationRail(
        selected_index=selected,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=theme.NAV_WIDTH,
        min_extended_width=theme.NAV_WIDTH,
        extended=True,
        destinations=destinations,
        on_change=_changed,
        bgcolor=theme.COLORS["nav"],
        indicator_color=theme.COLORS["accent"],
        unselected_label_text_style=ft.TextStyle(
            size=theme.role_size(theme.TextRole.ACTION),
            color=theme.COLORS["nav_text"],
        ),
        selected_label_text_style=ft.TextStyle(
            size=theme.role_size(theme.TextRole.ACTION),
            color="#FFFFFF",
            weight=ft.FontWeight.W_700,
        ),
    )
