"""Reusable empty / muted states."""

from __future__ import annotations

import flet as ft

from .. import theme


def empty_state(title: str, body: str) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            [
                theme.text(
                    title,
                    theme.TextRole.PRIMARY,
                    color=theme.COLORS["text_primary"],
                ),
                theme.text(
                    body,
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                ),
            ],
            spacing=theme.SPACING["sm"],
            tight=True,
        ),
        padding=theme.SPACING["lg"],
    )
