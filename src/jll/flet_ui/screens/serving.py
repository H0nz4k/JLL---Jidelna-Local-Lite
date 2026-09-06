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
        self.body = ft.Column(expand=True, spacing=theme.SPACING["md"], scroll=None)
        self.root = ft.Column(
            [
                ft.Text(
                    "Stav výdeje",
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                ),
                self.body,
            ],
            expand=True,
            spacing=theme.SPACING["md"],
        )
        self.refresh()

    def control(self) -> ft.Control:
        return self.root

    def _card(self, content: ft.Control, *, expand: bool = False) -> ft.Container:
        return ft.Container(
            content=content,
            bgcolor=theme.COLORS["surface"],
            border=ft.border.all(
                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
            ),
            border_radius=8,
            padding=theme.SPACING["md"],
            expand=expand,
        )

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

        remaining = self.vm.remaining_total(rows)
        hero = self._card(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(
                                day.strftime("%d. %m. %Y"),
                                size=theme.role_size(theme.TextRole.META),
                                color=theme.COLORS["text_secondary"],
                            ),
                            ft.Text(
                                "ZBÝVÁ CELKEM",
                                size=theme.role_size(theme.TextRole.ACTION),
                                color=theme.COLORS["text_secondary"],
                                weight=ft.FontWeight.W_600,
                            ),
                        ],
                        spacing=2,
                        tight=True,
                        expand=True,
                    ),
                    ft.Text(
                        str(remaining),
                        size=48,
                        weight=ft.FontWeight.W_700,
                        color=theme.COLORS["accent"],
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.body.controls.append(hero)

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.meal_type, []).append(row)

        cards: list[ft.Control] = []
        for meal_type, items in groups.items():
            meal_remaining = sum(max(0, item.remaining) for item in items)
            menu_rows: list[ft.Control] = []
            for item in items:
                menu_rows.append(
                    ft.Row(
                        [
                            ft.Text(
                                f"Menu {item.menu}",
                                size=theme.role_size(theme.TextRole.BODY),
                                expand=True,
                            ),
                            ft.Text(
                                str(max(0, item.remaining)),
                                size=theme.role_size(theme.TextRole.PRIMARY),
                                weight=ft.FontWeight.W_700,
                                color=theme.COLORS["accent"],
                            ),
                            ft.Text(
                                f"obj. {item.ordered} · vyd. {item.picked_up}",
                                size=theme.role_size(theme.TextRole.META),
                                color=theme.COLORS["text_secondary"],
                                width=120,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
            cards.append(
                self._card(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        meal_type,
                                        size=theme.role_size(theme.TextRole.ACTION),
                                        weight=ft.FontWeight.W_700,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        str(meal_remaining),
                                        size=32,
                                        weight=ft.FontWeight.W_700,
                                        color=theme.COLORS["accent"],
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Divider(height=1, color=theme.COLORS["border"]),
                            *menu_rows,
                        ],
                        spacing=theme.SPACING["sm"],
                        tight=True,
                    )
                )
            )

        if not cards:
            self.body.controls.append(
                empty_state("Stav výdeje", "Pro dnešek nejsou žádné porce k výdeji.")
            )
            return

        # Dvě karty vedle sebe, zbytek pod sebou — přehledné bez scrolleru.
        row_chunk: list[ft.Control] = []
        for idx, card in enumerate(cards):
            row_chunk.append(ft.Container(content=card, expand=True))
            if len(row_chunk) == 2 or idx == len(cards) - 1:
                self.body.controls.append(
                    ft.Row(row_chunk, spacing=theme.SPACING["md"])
                )
                row_chunk = []
