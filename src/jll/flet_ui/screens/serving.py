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

    def _card(self, content: ft.Control) -> ft.Container:
        return ft.Container(
            content=content,
            bgcolor=theme.COLORS["surface"],
            border=ft.border.all(
                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
            ),
            border_radius=8,
            padding=theme.SPACING["md"],
        )

    def _metric(self, label: str, value: int, *, emphasize: bool = False) -> ft.Control:
        return ft.Column(
            [
                ft.Text(
                    label,
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    str(value),
                    size=theme.role_size(theme.TextRole.PRIMARY) + (6 if emphasize else 0),
                    weight=ft.FontWeight.W_700,
                    color=theme.COLORS["accent"] if emphasize else theme.COLORS["text_primary"],
                ),
            ],
            spacing=0,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.START,
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

        ordered_total = self.vm.ordered_total(rows)
        remaining_total = self.vm.remaining_total(rows)
        hero = self._card(
            ft.Row(
                [
                    ft.Text(
                        day.strftime("%d. %m. %Y"),
                        size=theme.role_size(theme.TextRole.BODY),
                        color=theme.COLORS["text_secondary"],
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Container(expand=True),
                    self._metric("Celkem", ordered_total),
                    ft.Container(width=theme.SPACING["xl"]),
                    self._metric("Zbývá", remaining_total, emphasize=True),
                ],
                spacing=theme.SPACING["lg"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.body.controls.append(hero)

        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.meal_type, []).append(row)

        cards: list[ft.Control] = []
        for meal_type, items in groups.items():
            meal_ordered = sum(max(0, item.ordered) for item in items)
            meal_remaining = sum(max(0, item.remaining) for item in items)
            menu_rows: list[ft.Control] = []
            for item in items:
                remaining = max(0, item.remaining)
                menu_rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
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
                        padding=ft.padding.symmetric(vertical=2),
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
                                    ),
                                    ft.Container(expand=True),
                                    ft.Text(
                                        f"celkem {meal_ordered}",
                                        size=theme.role_size(theme.TextRole.META),
                                        color=theme.COLORS["text_secondary"],
                                    ),
                                    ft.Text(
                                        f"zbývá {meal_remaining}",
                                        size=theme.role_size(theme.TextRole.ACTION),
                                        weight=ft.FontWeight.W_700,
                                        color=theme.COLORS["accent"],
                                    ),
                                ],
                                spacing=theme.SPACING["md"],
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

        # Kompaktní mřížka max 2 sloupce, karty bez zbytečného roztahování textu.
        grid = ft.ResponsiveRow(
            [
                ft.Container(
                    content=card,
                    col={"xs": 12, "md": 6, "lg": 6},
                    padding=ft.padding.only(bottom=theme.SPACING["sm"]),
                )
                for card in cards
            ],
            spacing=theme.SPACING["md"],
            run_spacing=theme.SPACING["md"],
        )
        self.body.controls.append(
            ft.Container(content=grid, width=920, alignment=ft.alignment.top_left)
        )
