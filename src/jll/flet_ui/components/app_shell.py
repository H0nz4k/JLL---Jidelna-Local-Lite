"""Application shell: header + nav + workspace."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..routes import Route
from ..state import AppState
from .badges import lab_badge
from .navigation import navigation_rail
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
    # Prefer human provozovna label if stored as display via diagnostics
    if state.diagnostics is not None and getattr(state.diagnostics, "subject_name", None):
        subject = state.diagnostics.subject_name

    def _open_users(_e):
        dialog = build_user_switch_dialog(page, state, on_user_switched)
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    header = ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    "JidelnaLocalLite",
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                    color=theme.COLORS["text_primary"],
                ),
                ft.Text(
                    subject,
                    size=theme.role_size(theme.TextRole.BODY),
                    color=theme.COLORS["text_secondary"],
                    expand=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                    text_align=ft.TextAlign.CENTER,
                ),
                user_chip(state, _open_users),
                ft.IconButton(
                    icon=ft.Icons.MONITOR_HEART_OUTLINED,
                    tooltip="Diagnostika",
                    on_click=lambda _e: on_diagnostics(),
                ),
                lab_badge(),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=theme.SPACING["lg"], vertical=theme.SPACING["md"]),
        bgcolor=theme.COLORS["surface"],
        border=ft.border.only(bottom=ft.BorderSide(1, theme.COLORS["border"])),
    )

    body = ft.Row(
        [
            ft.Container(
                content=navigation_rail(state.route, on_route),
                width=theme.NAV_WIDTH,
                bgcolor=theme.COLORS["nav"],
            ),
            ft.Container(
                content=workspace,
                expand=True,
                bgcolor=theme.COLORS["background"],
                padding=theme.SPACING["lg"],
            ),
        ],
        expand=True,
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return ft.Column([header, body], expand=True, spacing=0)
