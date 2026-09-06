"""Application shell: header + top nav + workspace."""

from __future__ import annotations

import flet as ft

from ...version import application_version
from .. import theme
from ..state import AppState
from .badges import lab_badge
from .navigation import navigation_bar
from .user_menu import build_user_switch_dialog, user_chip


def app_shell(
    page: ft.Page,
    state: AppState,
    *,
    workspace: ft.Control,
    on_route,
    on_user_switched,
    on_diagnostics,
) -> ft.Control:
    subject = "—"
    if state.config is not None:
        subject = state.config.site_name or state.config.site_id
    if state.diagnostics is not None and getattr(state.diagnostics, "subject_name", None):
        subject = state.diagnostics.subject_name

    calendar = state.business_calendar
    if calendar is not None:
        date_line = calendar.header_label
    else:
        date_line = "Datum —"

    meta_size = theme.role_size(theme.TextRole.META)
    meta_color = theme.COLORS["text_secondary"]
    subtitle = f"{subject}   {date_line}"

    def _open_users(_e):
        dialog = build_user_switch_dialog(page, state, on_user_switched)
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    app_version = application_version()
    brand = ft.Column(
        [
            ft.Text(
                spans=[
                    ft.TextSpan(
                        "JidelnaLocalLite",
                        ft.TextStyle(
                            size=theme.role_size(theme.TextRole.PRIMARY),
                            weight=ft.FontWeight.W_700,
                            color=theme.COLORS["text_primary"],
                        ),
                    ),
                    ft.TextSpan(
                        f"  v{app_version}",
                        ft.TextStyle(
                            size=meta_size,
                            weight=ft.FontWeight.W_400,
                            color=meta_color,
                        ),
                    ),
                ],
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Text(
                subtitle,
                size=meta_size,
                color=meta_color,
                overflow=ft.TextOverflow.ELLIPSIS,
                max_lines=1,
            ),
        ],
        spacing=0,
        tight=True,
    )

    header = ft.Container(
        content=ft.Row(
            [
                brand,
                ft.Container(content=navigation_bar(state.route, on_route), expand=True),
                user_chip(state, _open_users),
                ft.IconButton(
                    icon=ft.Icons.MONITOR_HEART_OUTLINED,
                    tooltip="Diagnostika",
                    on_click=lambda _e: on_diagnostics(),
                ),
                lab_badge(),
            ],
            spacing=theme.SPACING["md"],
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
    return ft.Column([header, body], expand=True, spacing=0)
