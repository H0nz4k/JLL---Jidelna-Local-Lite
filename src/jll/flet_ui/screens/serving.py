"""Stav výdeje."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..components.empty_state import empty_state
from ..state import AppState
from ..viewmodels.serving import ServingViewModel


class ServingScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = ServingViewModel(state)
        self.body = ft.Column(
            expand=True,
            spacing=theme.SPACING["sm"],
            scroll=ft.ScrollMode.AUTO,
            tight=False,
        )
        self.root = ft.Column(
            [
                self.body,
            ],
            expand=True,
            spacing=0,
        )
        self.refresh()

    def control(self) -> ft.Control:
        return self.root

    def refresh(self) -> None:
        self.body.controls.clear()
        if not self.vm.can_view():
            self.body.controls.append(
                empty_state("Stav výdeje", "Nemáte oprávnění zobrazit stav výdeje.")
            )
            return
        try:
            day, rows = self.vm.load()
        except Exception as exc:
            self.body.controls.append(empty_state("Chyba", str(exc)))
            return

        ordered_total = self.vm.ordered_total(rows)
        remaining_total = self.vm.remaining_total(rows)

        self.body.controls.append(
            ft.Row(
                [
                    ft.Text(
                        "Stav výdeje",
                        size=theme.role_size(theme.TextRole.PRIMARY),
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        day.strftime("%d. %m. %Y"),
                        size=theme.role_size(theme.TextRole.BODY),
                        color=theme.COLORS["text_secondary"],
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Container(expand=True),
                    ft.Text(
                        f"celkem {ordered_total}",
                        size=theme.role_size(theme.TextRole.BODY),
                        color=theme.COLORS["text_secondary"],
                    ),
                    ft.Text(
                        f"zbývá {remaining_total}",
                        size=theme.role_size(theme.TextRole.BODY),
                        weight=ft.FontWeight.W_700,
                        color=theme.COLORS["accent"],
                    ),
                ],
                spacing=theme.SPACING["md"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            )
        )

        if not rows:
            self.body.controls.append(
                empty_state("Stav výdeje", "Pro dnešek nejsou žádné porce k výdeji.")
            )
            return

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.meal_type, []).append(row)

        list_rows: list[ft.Control] = []
        for meal_type, items in groups.items():
            for index, item in enumerate(items):
                remaining = max(0, item.remaining)
                list_rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    meal_type if index == 0 else "",
                                    size=theme.role_size(theme.TextRole.BODY),
                                    weight=ft.FontWeight.W_700,
                                    width=110,
                                ),
                                ft.Text(
                                    f"Menu {item.menu}",
                                    size=theme.role_size(theme.TextRole.BODY),
                                    weight=ft.FontWeight.W_600,
                                    width=72,
                                ),
                                ft.Text(
                                    f"celkem {item.ordered}",
                                    size=theme.role_size(theme.TextRole.BODY),
                                    color=theme.COLORS["text_secondary"],
                                    width=96,
                                ),
                                ft.Text(
                                    f"zbývá {remaining}",
                                    size=theme.role_size(theme.TextRole.BODY),
                                    weight=ft.FontWeight.W_700,
                                    color=theme.COLORS["accent"],
                                ),
                            ],
                            spacing=theme.SPACING["md"],
                            tight=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        bgcolor=theme.COLORS["surface"],
                        border=ft.border.all(
                            theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                        )
                        if index == 0
                        else ft.border.only(
                            left=ft.BorderSide(
                                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                            ),
                            right=ft.BorderSide(
                                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                            ),
                            bottom=ft.BorderSide(
                                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                            ),
                        ),
                        border_radius=ft.border_radius.only(
                            top_left=6 if index == 0 else 0,
                            top_right=6 if index == 0 else 0,
                            bottom_left=6 if index == len(items) - 1 else 0,
                            bottom_right=6 if index == len(items) - 1 else 0,
                        ),
                        padding=ft.padding.symmetric(
                            horizontal=theme.SPACING["md"],
                            vertical=theme.SPACING["sm"],
                        ),
                    )
                )
            list_rows.append(ft.Container(height=theme.SPACING["sm"]))

        self.body.controls.append(
            ft.Container(
                content=ft.Column(list_rows, spacing=0, tight=True, scroll=None),
                width=480,
                alignment=ft.alignment.top_left,
            )
        )
