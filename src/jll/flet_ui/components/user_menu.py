"""User menu / switcher."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..state import AppState


def user_chip(state: AppState, on_open) -> ft.Control:
    if state.business is None:
        return theme.text("—", theme.TextRole.META)
    legacy = state.business.current_legacy()
    label = f"{legacy.code} · {legacy.display_name}"
    return ft.TextButton(
        content=theme.text(
            label,
            theme.TextRole.ACTION,
            color=theme.COLORS["text_primary"],
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        ),
        style=theme.button_style(),
        on_click=on_open,
        tooltip="Přepnout uživatele",
    )


def build_user_switch_dialog(page: ft.Page, state: AppState, on_switched) -> ft.AlertDialog:
    assert state.business is not None
    users = state.business.list_switchable_users()
    list_view = ft.ListView(expand=True, spacing=4)

    def _pick(code: str):
        def _handler(_e):
            state.business.switch_user(code)
            dialog.open = False
            page.update()
            on_switched()

        return _handler

    for user in users:
        selected = user.code.casefold() == state.business.current_code.casefold()
        list_view.controls.append(
            ft.ListTile(
                title=theme.text(
                    f"{user.code} · {user.display_name}",
                    theme.TextRole.BODY,
                    color=theme.COLORS["accent"] if selected else None,
                ),
                selected=selected,
                on_click=_pick(user.code),
            )
        )

    dialog = ft.AlertDialog(
        modal=True,
        title=theme.text("Přepnout uživatele", theme.TextRole.PRIMARY),
        content=ft.Container(content=list_view, width=420, height=360),
        actions=[
            ft.TextButton(
                "Zavřít",
                style=theme.button_style(),
                on_click=lambda _e: setattr(dialog, "open", False) or page.update(),
            )
        ],
    )
    return dialog
