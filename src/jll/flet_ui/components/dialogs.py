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
        title=ft.Text(
            title,
            size=theme.role_size(theme.TextRole.PRIMARY),
            weight=ft.FontWeight.W_700,
        ),
        content=ft.Text(
            body,
            size=theme.role_size(theme.TextRole.BODY),
            color=theme.COLORS["text_primary"],
        ),
        actions=[
            ft.TextButton(primary, on_click=lambda _e: _close(page, dialog)),
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
        title=ft.Text(title, size=theme.role_size(theme.TextRole.PRIMARY), weight=ft.FontWeight.W_700),
        content=ft.Text(body, size=theme.role_size(theme.TextRole.BODY)),
        actions=[
            ft.TextButton("Zrušit", on_click=lambda _e: _close(page, dialog)),
            ft.FilledButton(
                confirm_label,
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
