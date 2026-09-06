"""Strávníci – hlavní workspace."""

from __future__ import annotations

from datetime import date

import flet as ft

from ...chip_reader import available_serial_ports
from ...read_models import DinerDay, MealDay
from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..components.permission_state import disabled_hint
from ..state import AppState
from ..viewmodels.diners import DinersViewModel


class DinersScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = DinersViewModel(state)
        self._day: DinerDay | None = None
        self.search = ft.TextField(
            hint_text="Hledat jméno / ev. číslo / čip…",
            expand=True,
            on_change=self._on_search,
            text_size=theme.role_size(theme.TextRole.BODY),
        )
        self.list_view = ft.ListView(expand=True, spacing=2, padding=0)
        self.detail = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=theme.SPACING["md"])
        self.root = self._build()

    def control(self) -> ft.Control:
        return self.root

    def _build(self) -> ft.Control:
        create = self.state.diner_create_state()
        new_btn = ft.FilledButton(
            "+ Nový",
            disabled=not create.allowed,
            tooltip=disabled_hint(create) or None,
            on_click=lambda _e: message_dialog(
                self.page,
                title="Nový strávník",
                body=disabled_hint(create) or "Zápis zatím není povolen.",
            ),
        )
        identify = ft.OutlinedButton(
            "Identifikovat čip",
            on_click=self._identify_chip,
        )
        toolbar = ft.Row(
            [self.search, identify, new_btn],
            spacing=theme.SPACING["sm"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        list_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Strávníci",
                        size=theme.role_size(theme.TextRole.PRIMARY),
                        weight=ft.FontWeight.W_700,
                    ),
                    self.list_view,
                ],
                expand=True,
                spacing=theme.SPACING["sm"],
            ),
            bgcolor=theme.COLORS["surface"],
            border_radius=8,
            padding=theme.SPACING["md"],
            expand=3,
        )
        detail_panel = ft.Container(
            content=self.detail,
            bgcolor=theme.COLORS["surface"],
            border_radius=8,
            padding=theme.SPACING["lg"],
            expand=7,
        )
        if not self.vm.can_view():
            return empty_state(
                "Strávníci",
                "Nemáte oprávnění zobrazit strávníky.",
            )
        self.detail.controls = [
            empty_state("Vyberte strávníka", "Hledejte vlevo a otevřete kartu.")
        ]
        return ft.Column(
            [
                toolbar,
                ft.Row([list_panel, detail_panel], expand=True, spacing=theme.SPACING["md"]),
            ],
            expand=True,
            spacing=theme.SPACING["md"],
        )

    def _on_search(self, e: ft.ControlEvent) -> None:
        results = self.vm.search(e.control.value or "")
        self.list_view.controls.clear()
        for item in results:
            selected = item.evidcislo == self.state.selected_evidcislo
            self.list_view.controls.append(
                ft.Container(
                    content=ft.Text(
                        item.name,
                        size=theme.role_size(theme.TextRole.BODY),
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        color=theme.COLORS["text_primary"],
                    ),
                    bgcolor=theme.COLORS["selected"] if selected else None,
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=6,
                    on_click=lambda _e, evid=item.evidcislo: self._open(evid),
                    ink=True,
                )
            )
        self.page.update()

    def _open(self, evidcislo: int) -> None:
        try:
            self._day = self.vm.select_diner(evidcislo)
        except Exception as exc:
            message_dialog(self.page, title="Strávník", body=str(exc))
            return
        self._render_detail()
        self._on_search(type("E", (), {"control": self.search})())

    def _render_detail(self) -> None:
        day = self._day
        assert day is not None
        diner = day.diner
        edit = self.state.diner_edit_state()
        chip_state = self.state.chip_assign_state()
        header = ft.Column(
            [
                ft.Text(
                    diner.name,
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                ),
                ft.Text(
                    f"{diner.category} · ev. {diner.evidcislo}",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                ),
            ],
            spacing=4,
            tight=True,
        )
        credit = ft.Column(
            [
                ft.Text("Kredit", size=theme.role_size(theme.TextRole.META), color=theme.COLORS["text_secondary"]),
                ft.Text(
                    self.vm.format_credit(diner.available_credit),
                    size=theme.role_size(theme.TextRole.BODY),
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=2,
            tight=True,
        )
        chip = ft.Column(
            [
                ft.Text("Čip", size=theme.role_size(theme.TextRole.META), color=theme.COLORS["text_secondary"]),
                ft.Text(
                    diner.chip_number or "—",
                    size=theme.role_size(theme.TextRole.BODY),
                ),
            ],
            spacing=2,
            tight=True,
        )
        actions = ft.Row(
            [
                ft.OutlinedButton(
                    "Upravit",
                    disabled=not edit.allowed,
                    tooltip=disabled_hint(edit) or None,
                    on_click=lambda _e: message_dialog(
                        self.page,
                        title="Úprava strávníka",
                        body=disabled_hint(edit) or "Nedostupné.",
                    ),
                ),
                ft.TextButton(
                    "Detail čipu",
                    disabled=not chip_state.allowed and True,
                    tooltip=disabled_hint(chip_state) or "Náhled čipu",
                    on_click=lambda _e: message_dialog(
                        self.page,
                        title="Čip",
                        body=disabled_hint(chip_state)
                        if not chip_state.allowed
                        else (diner.chip_number or "Bez čipu"),
                    ),
                ),
            ]
        )
        month_title = ft.Text(
            f"Přihlášky · {day.target_date.strftime('%B %Y')}",
            size=theme.role_size(theme.TextRole.ACTION),
            weight=ft.FontWeight.W_600,
        )
        self.detail.controls = [
            header,
            ft.Row([credit, chip], spacing=theme.SPACING["xl"]),
            actions,
            month_title,
            self._month_grid(day),
            self._menu_panel(day),
        ]
        self.page.update()

    def _month_grid(self, day: DinerDay) -> ft.Control:
        rows = self.vm.month_rows(day)
        if not rows:
            return ft.Text("Žádná data přihlášek.", size=theme.role_size(theme.TextRole.META))
        header_cells = [
            ft.Container(width=72, content=ft.Text("", size=theme.role_size(theme.TextRole.META)))
        ]
        for cell in rows[0].cells:
            header_cells.append(
                ft.Container(
                    width=28,
                    alignment=ft.alignment.center,
                    content=ft.Text(str(cell.day), size=theme.role_size(theme.TextRole.META)),
                )
            )
        grid_rows = [ft.Row(header_cells, spacing=2)]
        for row in rows:
            cells = [
                ft.Container(
                    width=72,
                    content=ft.Text(
                        row.meal_type,
                        size=theme.role_size(theme.TextRole.META),
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                )
            ]
            for cell in row.cells:
                bg = None
                if cell.is_selected:
                    bg = theme.COLORS["today"]
                if cell.is_ordered:
                    bg = (
                        theme.COLORS["ordered_selected"]
                        if cell.is_selected
                        else theme.COLORS["ordered"]
                    )
                elif not cell.is_cooking and cell.state == "*":
                    bg = theme.COLORS["non_cooking"]
                label = cell.state or ""
                cells.append(
                    ft.Container(
                        width=28,
                        height=28,
                        alignment=ft.alignment.center,
                        bgcolor=bg,
                        border_radius=4,
                        content=ft.Text(label, size=theme.role_size(theme.TextRole.META)),
                        on_click=lambda _e, d=cell.day: self._pick_day(d),
                    )
                )
            grid_rows.append(ft.Row(cells, spacing=2))
        return ft.Container(
            content=ft.Column(grid_rows, spacing=2, scroll=ft.ScrollMode.AUTO),
            bgcolor=theme.COLORS["surface_muted"],
            padding=theme.SPACING["sm"],
            border_radius=6,
        )

    def _pick_day(self, day_num: int) -> None:
        if self._day is None:
            return
        current = self._day.target_date
        target = date(current.year, current.month, day_num)
        try:
            self._day = self.vm.set_day(target)
        except Exception as exc:
            message_dialog(self.page, title="Den", body=str(exc))
            return
        self._render_detail()

    def _menu_panel(self, day: DinerDay) -> ft.Control:
        title = ft.Text(
            f"Jídelníček · {day.target_date.day}. {day.target_date.strftime('%B')}",
            size=theme.role_size(theme.TextRole.ACTION),
            weight=ft.FontWeight.W_600,
        )
        blocks: list[ft.Control] = [title]
        for meal in day.meals:
            blocks.append(self._meal_block(day, meal))
        return ft.Column(blocks, spacing=theme.SPACING["sm"])

    def _meal_block(self, day: DinerDay, meal: MealDay) -> ft.Control:
        options = []
        ordered = getattr(meal, "ordered_menu", None)
        if ordered is None and meal.current_state and meal.current_state.isdigit():
            ordered = int(meal.current_state)
        for option in meal.options:
            is_ordered = ordered == option.menu
            btn = ft.Container(
                content=ft.Text(
                    f"{option.menu} · {option.dish_name or 'Menu'}",
                    size=theme.role_size(theme.TextRole.BODY),
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                bgcolor=theme.COLORS["ordered"] if is_ordered else theme.COLORS["surface_muted"],
                padding=theme.SPACING["sm"],
                border_radius=6,
                on_click=(
                    None
                    if is_ordered
                    else lambda _e, m=meal.meal_type, menu=option.menu: self._order(
                        m, menu
                    )
                ),
            )
            options.append(btn)
        if not meal.options:
            options.append(
                ft.Text(
                    "Zatím není zveřejněn.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            )
        unsub = None
        if ordered is not None and self.vm.can_change_orders():
            unsub = ft.TextButton(
                "Odhlásit",
                on_click=lambda _e, m=meal.meal_type, menu=ordered: self._unsubscribe(m, menu),
            )
        children: list[ft.Control] = [
            ft.Text(meal.meal_type, size=theme.role_size(theme.TextRole.BODY), weight=ft.FontWeight.W_600),
            *options,
        ]
        if unsub is not None:
            children.append(unsub)
        return ft.Column(children, spacing=4, tight=True)

    def _order(self, meal_type: str, menu: int) -> None:
        if self._day is None or not self.vm.can_change_orders():
            message_dialog(self.page, title="Objednávka", body="Nemáte oprávnění měnit objednávky.")
            return
        outcome = self.vm.apply_menu(
            self._day.diner.evidcislo, self._day.target_date, meal_type, menu
        )
        if outcome.error is not None:
            message_dialog(self.page, title="Objednávka", body=outcome.error.user_message)
        if outcome.refreshed is not None:
            self._day = outcome.refreshed
            self._render_detail()

    def _unsubscribe(self, meal_type: str, menu: int) -> None:
        if self._day is None:
            return
        outcome = self.vm.unsubscribe(
            self._day.diner.evidcislo, self._day.target_date, meal_type, menu
        )
        if outcome.error is not None:
            message_dialog(self.page, title="Odhlášení", body=outcome.error.user_message)
        if outcome.refreshed is not None:
            self._day = outcome.refreshed
            self._render_detail()

    def _identify_chip(self, _e) -> None:
        reader = self.state.chip_reader
        configured = self.state.config.reader_port if self.state.config else None
        port_names = {item.device.upper() for item in available_serial_ports()}
        if configured and configured.upper() not in port_names:
            message_dialog(
                self.page,
                title="Čtečka není dostupná",
                body=(
                    f"Nakonfigurovaný port {configured} není dostupný.\n\n"
                    "Zkontrolujte připojení čtečky nebo nastavení\n"
                    "v Administraci."
                ),
            )
            return
        if reader is None:
            message_dialog(
                self.page,
                title="Čtečka není dostupná",
                body="Čtečka není nakonfigurována.\n\nNastavte port v Administraci.",
            )
            return
        code = ""
        try:
            reader.start()
            chip_read = reader.read_once(timeout_seconds=8.0)
            code = chip_read.code
        except Exception:
            message_dialog(
                self.page,
                title="Čtečka není dostupná",
                body=(
                    f"Nakonfigurovaný port {configured or '—'} není dostupný.\n\n"
                    "Zkontrolujte připojení čtečky nebo nastavení\n"
                    "v Administraci."
                ),
            )
            return
        finally:
            try:
                reader.stop()
            except Exception:
                pass
        if not code:
            message_dialog(self.page, title="Čip", body="Čip nebyl načten.")
            return
        try:
            identified = self.state.read_service.identify_chip(code)
        except Exception as exc:
            message_dialog(self.page, title="Čip", body=str(exc))
            return
        if identified.opens_card and identified.owner is not None:
            self._open(identified.owner.evidcislo)
            return
        message_dialog(self.page, title="Čip", body=identified.message)
