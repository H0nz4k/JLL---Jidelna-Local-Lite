"""Reusable empty / muted states."""

from __future__ import annotations

import flet as ft

from .. import theme


def empty_state(title: str, body: str) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    title,
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                    color=theme.COLORS["text_primary"],
                ),
                ft.Text(
                    body,
                    size=theme.role_size(theme.TextRole.BODY),
                    color=theme.COLORS["text_secondary"],
                ),
            ],
            spacing=theme.SPACING["sm"],
            tight=True,
        ),
        padding=theme.SPACING["lg"],
    )
