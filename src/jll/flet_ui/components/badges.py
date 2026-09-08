"""LAB / status badges."""

from __future__ import annotations

import flet as ft

from .. import theme


def lab_badge() -> ft.Control:
    return ft.Container(
        content=theme.text("LAB", theme.TextRole.META, color="#FFFFFF"),
        bgcolor=theme.COLORS["lab"],
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        border_radius=4,
        tooltip="Lokální testovací databáze – detail v diagnostice",
    )


def soft_badge(text: str, *, color: str | None = None) -> ft.Control:
    return ft.Container(
        content=theme.text(
            text,
            theme.TextRole.META,
            color=theme.COLORS["text_secondary"],
        ),
        bgcolor=color or theme.COLORS["surface_muted"],
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=4,
    )
