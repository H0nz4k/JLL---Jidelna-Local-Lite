"""Top navigation pills for the application shell."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..routes import NAV_ITEMS, Route

_ICON_BY_NAME: dict[str, str] = {
    "people": ft.Icons.PEOPLE,
    "restaurant": ft.Icons.RESTAURANT,
    "assessment": ft.Icons.ASSESSMENT,
    "settings": ft.Icons.SETTINGS,
}


def navigation_bar(active: Route, on_change) -> ft.Control:
    items: list[ft.Control] = []
    for route, label, icon_name in NAV_ITEMS:
        selected = route == active
        icon = _ICON_BY_NAME.get(icon_name, ft.Icons.CIRCLE)
        items.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            icon,
                            color="#FFFFFF" if selected else theme.COLORS["text_secondary"],
                            size=18,
                        ),
                        ft.Text(
                            label,
                            size=theme.role_size(theme.TextRole.ACTION),
                            color="#FFFFFF" if selected else theme.COLORS["text_primary"],
                            weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_500,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=theme.COLORS["accent"] if selected else theme.COLORS["surface_muted"],
                border=ft.border.all(
                    1,
                    theme.COLORS["accent"]
                    if selected
                    else theme.COLORS.get("block_border", theme.COLORS["border"]),
                ),
                border_radius=22,
                padding=ft.padding.symmetric(horizontal=14, vertical=8),
                ink=True,
                on_click=lambda _e, r=route: on_change(r),
            )
        )
    return ft.Row(
        items,
        spacing=theme.SPACING["md"],
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def navigation_rail(active: Route, on_change) -> ft.Control:
    """Zpětná kompatibilita – stejné položky jako horní lišta."""

    return navigation_bar(active, on_change)
