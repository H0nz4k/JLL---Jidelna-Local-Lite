"""Common dialogs."""

from __future__ import annotations

import flet as ft

from .. import theme


def message_dialog(
    page: ft.Page,
    *,
    title: str,
    body: str,
    primary: str = "Zavřít",
) -> None:
    dialog = ft.AlertDialog(
        modal=True,
        title=theme.text(title, theme.TextRole.PRIMARY),
        content=theme.text(
            body,
            theme.TextRole.BODY,
            color=theme.COLORS["text_primary"],
        ),
        actions=[
            ft.TextButton(
                primary,
                style=theme.button_style(),
                on_click=lambda _e: _close(page, dialog),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def confirm_dialog(
    page: ft.Page,
    *,
    title: str,
    body: str,
    on_confirm,
    confirm_label: str = "Potvrdit",
) -> None:
    dialog = ft.AlertDialog(
        modal=True,
        title=theme.text(title, theme.TextRole.PRIMARY),
        content=theme.text(body, theme.TextRole.BODY),
        actions=[
            ft.TextButton(
                "Zrušit",
                style=theme.button_style(),
                on_click=lambda _e: _close(page, dialog),
            ),
            ft.FilledButton(
                confirm_label,
                style=theme.button_style(),
                on_click=lambda _e: (_close(page, dialog), on_confirm()),
            ),
        ],
    )
    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def _close(page: ft.Page, dialog: ft.AlertDialog) -> None:
    dialog.open = False
    page.update()
