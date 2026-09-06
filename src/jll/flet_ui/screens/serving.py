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
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
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
        self.body.controls.extend(
            [
                ft.Text(
                    day.strftime("%d. %m. %Y"),
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                ),
                ft.Text(
                    "ZBÝVÁ",
                    size=theme.role_size(theme.TextRole.ACTION),
                    color=theme.COLORS["text_secondary"],
                ),
                ft.Text(
                    str(remaining),
                    size=theme.role_size(theme.TextRole.PRIMARY) * 2.2,
                    weight=ft.FontWeight.W_700,
                    color=theme.COLORS["accent"],
                ),
            ]
        )
        groups: dict[str, list] = {}
        for row in rows:
            groups.setdefault(row.meal_type, []).append(row)
        for meal_type, items in groups.items():
            self.body.controls.append(
                ft.Text(
                    meal_type,
                    size=theme.role_size(theme.TextRole.BODY),
                    weight=ft.FontWeight.W_600,
                )
            )
            for item in items:
                self.body.controls.append(
                    ft.Text(
                        f"Menu {item.menu}: zbývá {item.remaining} "
                        f"(obj. {item.ordered} / vyd. {item.picked_up})",
                        size=theme.role_size(theme.TextRole.BODY),
                    )
                )
