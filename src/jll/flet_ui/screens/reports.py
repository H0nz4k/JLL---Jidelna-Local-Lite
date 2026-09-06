"""Sestavy."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import flet as ft

from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..state import AppState
from ..viewmodels.reports import ReportsViewModel


class ReportsScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = ReportsViewModel(state)
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=theme.SPACING["sm"])
        self.root = ft.Column(
            [
                ft.Text(
                    "Sestavy",
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                ),
                ft.Row(
                    [
                        ft.FilledButton("Dnes", on_click=lambda _e: self.load(self.vm.today())),
                        ft.OutlinedButton("Zítra", on_click=lambda _e: self.load(self.vm.tomorrow())),
                        ft.OutlinedButton(
                            "Další varný den",
                            on_click=self._next_cooking,
                        ),
                    ],
                    wrap=True,
                ),
                self.body,
            ],
            expand=True,
            spacing=theme.SPACING["md"],
        )
        if self.vm.can_view():
            self.load(self.vm.today())
        else:
            self.body.controls = [
                empty_state("Sestavy", "Nemáte oprávnění zobrazit sestavy.")
            ]

    def control(self) -> ft.Control:
        return self.root

    def _next_cooking(self, _e) -> None:
        day = self.vm.next_cooking_day()
        if day is None:
            message_dialog(self.page, title="Sestavy", body="Další varný den nebyl nalezen.")
            return
        self.load(day)

    def load(self, target: date) -> None:
        self.body.controls.clear()
        if not self.vm.can_view():
            self.body.controls.append(
                empty_state("Sestavy", "Nemáte oprávnění zobrazit sestavy.")
            )
            self.page.update()
            return
        try:
            report = self.vm.load(target)
        except Exception as exc:
            self.body.controls.append(empty_state("Chyba", str(exc)))
            self.page.update()
            return
        self.body.controls.append(
            ft.Text(
                target.strftime("%d. %m. %Y"),
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            )
        )
        self.body.controls.append(
            ft.Text(
                f"Porcí celkem: {report.total_portions}",
                size=theme.role_size(theme.TextRole.BODY),
            )
        )
        self.body.controls.append(
            ft.Text("Souhrn kategorií", size=theme.role_size(theme.TextRole.ACTION), weight=ft.FontWeight.W_600)
        )
        for cat in report.categories:
            self.body.controls.append(
                ft.Text(
                    f"{cat.category_label}: {cat.orders}",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )
        self.body.controls.append(
            ft.Text("Normy", size=theme.role_size(theme.TextRole.ACTION), weight=ft.FontWeight.W_600)
        )
        for norm in report.norms:
            self.body.controls.append(
                ft.Text(
                    f"{norm.norm_label} · {norm.meal_type} · menu {norm.menu}: {norm.portions}",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )
        self.body.controls.append(
            ft.Text("Jmenný seznam", size=theme.role_size(theme.TextRole.ACTION), weight=ft.FontWeight.W_600)
        )
        for diner in report.diners[:200]:
            self.body.controls.append(
                ft.Text(
                    f"{diner.name} · {diner.meal_type} · menu {diner.menu}",
                    size=theme.role_size(theme.TextRole.META),
                )
            )
        if self.vm.can_print():
            self.body.controls.append(
                ft.FilledButton(
                    "Export PDF",
                    on_click=lambda _e, r=report: self._pdf(r),
                )
            )
        self.page.update()

    def _pdf(self, report) -> None:
        try:
            out = Path("logs") / f"jll-report-{report.target_date.isoformat()}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            path = self.vm.export_pdf(report, out)
            message_dialog(self.page, title="PDF", body=f"Uloženo: {path}")
        except Exception as exc:
            message_dialog(self.page, title="PDF", body=str(exc))
