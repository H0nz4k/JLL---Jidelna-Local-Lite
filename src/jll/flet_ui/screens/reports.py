"""Sestavy – záložky, filtr dne, náhled a export."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

import flet as ft

from ...read_models import DailyReport
from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..state import AppState
from ..viewmodels.reports import ReportsViewModel


class ReportTab(StrEnum):
    CATEGORIES = "Souhrn kategorií"
    NORMS = "Normy"
    NAMED = "Jmenný seznam"


class DayFilter(StrEnum):
    TODAY = "Dnes"
    TOMORROW = "Zítra"
    NEXT_COOKING = "Další varný den"


class ReportsScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = ReportsViewModel(state)
        self.tab = ReportTab.CATEGORIES
        self.day_filter = DayFilter.TODAY
        self._target: date | None = None
        self._report: DailyReport | None = None
        self.tabs_row = ft.Row(spacing=theme.SPACING["sm"], wrap=True)
        self.filter_row = ft.Row(spacing=theme.SPACING["sm"], wrap=True)
        self.content = ft.Column(
            expand=True,
            spacing=theme.SPACING["xs"],
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        )
        self.actions = ft.Row(spacing=theme.SPACING["sm"])
        self.root = ft.Column(
            [
                ft.Text(
                    "Sestavy",
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                ),
                self.tabs_row,
                self.filter_row,
                ft.Container(
                    content=self.content,
                    width=520,
                    bgcolor=theme.COLORS["surface"],
                    border=ft.border.all(
                        theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                    ),
                    border_radius=8,
                    padding=theme.SPACING["md"],
                    alignment=ft.alignment.top_left,
                ),
                self.actions,
            ],
            expand=True,
            spacing=theme.SPACING["md"],
            scroll=ft.ScrollMode.AUTO,
        )
        if self.vm.can_view():
            self._reload()
        else:
            self.content.controls = [
                empty_state("Sestavy", "Nemáte oprávnění zobrazit sestavy.")
            ]

    def control(self) -> ft.Control:
        return self.root

    def _pill(self, label: str, *, selected: bool, on_click) -> ft.Control:
        return ft.Container(
            content=ft.Text(
                label,
                size=theme.role_size(theme.TextRole.ACTION),
                color="#FFFFFF" if selected else theme.COLORS["text_primary"],
                weight=ft.FontWeight.W_700 if selected else ft.FontWeight.W_500,
            ),
            bgcolor=theme.COLORS["accent"] if selected else theme.COLORS["surface_muted"],
            border=ft.border.all(
                1,
                theme.COLORS["accent"]
                if selected
                else theme.COLORS["block_border"],
            ),
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            ink=True,
            on_click=on_click,
        )

    def _rebuild_chrome(self) -> None:
        self.tabs_row.controls = [
            self._pill(
                tab.value,
                selected=self.tab is tab,
                on_click=lambda _e, t=tab: self._set_tab(t),
            )
            for tab in ReportTab
        ]
        self.filter_row.controls = [
            self._pill(
                day.value,
                selected=self.day_filter is day,
                on_click=lambda _e, d=day: self._set_day(d),
            )
            for day in DayFilter
        ]
        buttons: list[ft.Control] = [
            ft.OutlinedButton("Náhled", on_click=lambda _e: self._preview()),
        ]
        if self.vm.can_print():
            buttons.append(
                ft.FilledButton("Export", on_click=lambda _e: self._export())
            )
        self.actions.controls = buttons

    def _set_tab(self, tab: ReportTab) -> None:
        self.tab = tab
        self._render_content()
        self.page.update()

    def _set_day(self, day_filter: DayFilter) -> None:
        self.day_filter = day_filter
        self._reload()

    def _resolve_target(self) -> date | None:
        if self.day_filter is DayFilter.TODAY:
            return self.vm.today()
        if self.day_filter is DayFilter.TOMORROW:
            return self.vm.tomorrow()
        return self.vm.next_cooking_day()

    def _reload(self) -> None:
        self._rebuild_chrome()
        self.content.controls.clear()
        if not self.vm.can_view():
            self.content.controls.append(
                empty_state("Sestavy", "Nemáte oprávnění zobrazit sestavy.")
            )
            self.page.update()
            return
        try:
            target = self._resolve_target()
        except Exception as exc:
            self.content.controls.append(empty_state("Chyba", str(exc)))
            self.page.update()
            return
        if target is None:
            self._target = None
            self._report = None
            self.content.controls.append(
                empty_state("Sestavy", "Další varný den nebyl nalezen.")
            )
            self.page.update()
            return
        try:
            report = self.vm.load(target)
        except Exception as exc:
            self.content.controls.append(empty_state("Chyba", str(exc)))
            self.page.update()
            return
        self._target = target
        self._report = report
        self._render_content()
        self.page.update()

    def _header_meta(self) -> list[ft.Control]:
        assert self._target is not None and self._report is not None
        return [
            ft.Row(
                [
                    ft.Text(
                        self._target.strftime("%d. %m. %Y"),
                        size=theme.role_size(theme.TextRole.BODY),
                        color=theme.COLORS["text_secondary"],
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Container(expand=True),
                    ft.Text(
                        "Porcí celkem",
                        size=theme.role_size(theme.TextRole.META),
                        color=theme.COLORS["text_secondary"],
                    ),
                    ft.Text(
                        str(self._report.total_portions),
                        size=theme.role_size(theme.TextRole.PRIMARY),
                        weight=ft.FontWeight.W_700,
                        color=theme.COLORS["accent"],
                    ),
                ],
                spacing=theme.SPACING["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
        ]

    def _render_content(self) -> None:
        self._rebuild_chrome()
        self.content.controls.clear()
        if self._report is None or self._target is None:
            self.content.controls.append(
                empty_state("Sestavy", "Vyberte den a sestavu.")
            )
            return
        self.content.controls.extend(self._header_meta())
        self.content.controls.append(ft.Divider(height=1, color=theme.COLORS["border"]))
        if self.tab is ReportTab.CATEGORIES:
            self.content.controls.extend(self._categories_lines(self._report))
        elif self.tab is ReportTab.NORMS:
            self.content.controls.extend(self._norms_lines(self._report))
        else:
            self.content.controls.append(self._named_list(self._report))

    def _count_row(self, label: str, count: int) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        label,
                        size=theme.role_size(theme.TextRole.BODY),
                        expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                    ft.Text(
                        str(count),
                        size=theme.role_size(theme.TextRole.BODY),
                        weight=ft.FontWeight.W_700,
                        color=theme.COLORS["accent"],
                        width=40,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                spacing=theme.SPACING["md"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=ft.padding.symmetric(vertical=2),
        )

    def _categories_lines(self, report: DailyReport) -> list[ft.Control]:
        if not report.categories:
            return [
                ft.Text(
                    "Žádný souhrn kategorií.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            ]
        return [
            self._count_row(cat.category_label, cat.orders) for cat in report.categories
        ]

    def _norms_lines(self, report: DailyReport) -> list[ft.Control]:
        if not report.norms:
            return [
                ft.Text(
                    "Žádné normy.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            ]
        return [
            self._count_row(
                f"{norm.norm_label} · {norm.meal_type} · menu {norm.menu}",
                norm.portions,
            )
            for norm in report.norms
        ]

    def _named_list(self, report: DailyReport) -> ft.Control:
        rows: list[ft.Control] = []
        for diner in report.diners[:300]:
            rows.append(
                ft.Text(
                    f"{diner.name} · {diner.meal_type} · menu {diner.menu}",
                    size=theme.role_size(theme.TextRole.BODY),
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                )
            )
        if not rows:
            return ft.Text(
                "Žádné jmenné položky.",
                size=theme.role_size(theme.TextRole.META),
                color=theme.COLORS["text_secondary"],
            )
        # Jmenný seznam scrolluje uvnitř panelu; výška podle obsahu, ne přes celou obrazovku.
        return ft.Column(controls=rows, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO)

    def _preview(self) -> None:
        if self._report is None or self._target is None:
            message_dialog(self.page, title="Náhled", body="Nejdřív načtěte sestavu.")
            return
        lines: list[ft.Control] = [
            ft.Text(
                f"{self.tab.value} · {self._target.strftime('%d. %m. %Y')}",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                f"Porcí celkem: {self._report.total_portions}",
                size=theme.role_size(theme.TextRole.BODY),
            ),
            ft.Divider(),
        ]
        if self.tab is ReportTab.CATEGORIES:
            lines.extend(self._categories_lines(self._report))
        elif self.tab is ReportTab.NORMS:
            lines.extend(self._norms_lines(self._report))
        else:
            for diner in self._report.diners[:200]:
                lines.append(
                    ft.Text(
                        f"{diner.name} · {diner.meal_type} · menu {diner.menu}",
                        size=theme.role_size(theme.TextRole.META),
                    )
                )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Náhled sestavy",
                size=theme.role_size(theme.TextRole.PRIMARY),
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(
                content=ft.Column(lines, scroll=ft.ScrollMode.AUTO, spacing=4),
                width=560,
                height=420,
            ),
            actions=[
                ft.TextButton(
                    "Zavřít",
                    on_click=lambda _e: setattr(dialog, "open", False)
                    or self.page.update(),
                )
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _export(self) -> None:
        if self._report is None:
            message_dialog(self.page, title="Export", body="Nejdřív načtěte sestavu.")
            return
        try:
            out = Path("logs") / f"jll-report-{self._report.target_date.isoformat()}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            path = self.vm.export_pdf(self._report, out)
            message_dialog(self.page, title="Export", body=f"Uloženo: {path}")
        except Exception as exc:
            message_dialog(self.page, title="Export", body=str(exc))
