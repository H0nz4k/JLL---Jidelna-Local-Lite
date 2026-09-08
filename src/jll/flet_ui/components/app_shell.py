"""Application shell: header + top nav + workspace."""

from __future__ import annotations

import flet as ft

from ...version import application_version
from .. import theme
from ..state import AppState
from .badges import lab_badge
from .navigation import navigation_bar
from .user_menu import build_user_switch_dialog, user_chip

_HEADER_ROW_HEIGHT = 44


def app_shell(
    page: ft.Page,
    state: AppState,
    *,
    workspace: ft.Control,
    on_route,
    on_user_switched,
    on_diagnostics,
    on_logo=None,
) -> ft.Control:
    meta_color = theme.COLORS["text_secondary"]

    def _open_users(_e):
        if state.business is None or not state.business.can_switch_users():
            return
        dialog = build_user_switch_dialog(page, state, on_user_switched)
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    app_version = application_version()
    brand_title = ft.Text(
        spans=[
            ft.TextSpan(
                "JidelnaLocalLite",
                theme.role_style(
                    theme.TextRole.PRIMARY,
                    color=theme.COLORS["text_primary"],
                ),
            ),
            ft.TextSpan(
                f"  v{app_version}",
                theme.role_style(theme.TextRole.META, color=meta_color),
            ),
        ],
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    left = ft.Container(
        content=ft.Container(
            content=brand_title,
            on_click=(lambda _e: on_logo()) if on_logo is not None else None,
            ink=on_logo is not None,
            tooltip="Domů – Strávníci" if on_logo is not None else None,
        ),
        expand=True,
        height=_HEADER_ROW_HEIGHT,
        alignment=ft.alignment.center_left,
    )
    center = ft.Container(
        content=navigation_bar(state.route, on_route),
        height=_HEADER_ROW_HEIGHT,
        alignment=ft.alignment.center,
    )
    right = ft.Container(
        content=ft.Row(
            [
                user_chip(state, _open_users),
                ft.IconButton(
                    icon=ft.Icons.MONITOR_HEART_OUTLINED,
                    tooltip="Diagnostika",
                    icon_size=20,
                    style=ft.ButtonStyle(padding=4),
                    on_click=lambda _e: on_diagnostics(),
                ),
                lab_badge(),
            ],
            spacing=theme.SPACING["sm"],
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        height=_HEADER_ROW_HEIGHT,
        alignment=ft.alignment.center_right,
    )

    header = ft.Container(
        content=ft.Row(
            [left, center, right],
            spacing=theme.SPACING["lg"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(
            horizontal=theme.SPACING["lg"], vertical=theme.SPACING["sm"]
        ),
        bgcolor=theme.COLORS["surface"],
        border=ft.border.only(bottom=ft.BorderSide(2, theme.COLORS["block_border"])),
    )

    body = ft.Container(
        content=workspace,
        expand=True,
        bgcolor=theme.COLORS["background"],
        padding=theme.SPACING["md"],
    )
    theme.set_typography(state.typography)
    return ft.Column([header, body], expand=True, spacing=0)
