"""Strávníci – hlavní workspace."""

from __future__ import annotations

import threading
from datetime import date

import flet as ft

from ...chip_reader import (
    ChipReaderCancelled,
    ChipReaderTimeout,
    UnavailableChipReader,
    available_serial_ports,
)
from ...policy import Permission
from ...read_models import DinerDay, MealDay
from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..components.permission_state import disabled_hint
from ..state import AppState
from ..viewmodels.diners import DinersViewModel

_READER_HINT = "čtečka nepřipojena"
_SEARCH_HINT = "Hledat jméno / ev. číslo / čip…"


class DinersScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = DinersViewModel(state)
        self._day: DinerDay | None = None
        self._results: list = []
        self._focus_index = 0
        self.search = ft.TextField(
            hint_text=_SEARCH_HINT,
            dense=True,
            autofocus=True,
            on_change=self._on_search,
            on_submit=self._on_search_submit,
            text_size=theme.role_size(theme.TextRole.BODY),
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_color=theme.COLORS["block_border"],
            focused_border_color=theme.COLORS["accent"],
        )
        self.list_view = ft.ListView(expand=True, spacing=2, padding=0)
        self.detail = ft.Column(expand=True, spacing=theme.SPACING["sm"], scroll=None)
        self.page.on_keyboard_event = self._on_page_key
        self.root = self._build()
        self._apply_reader_hint()
        self._start_chip_listen()

    def control(self) -> ft.Control:
        return self.root

    def focus_search(self) -> None:
        try:
            self.search.focus()
        except Exception:
            pass

    def _reader_configured(self) -> bool:
        cfg = self.state.config
        return bool(cfg and cfg.reader_port and str(cfg.reader_port).strip())

    def _reader_connected(self) -> bool:
        if not self._reader_configured():
            return False
        port = str(self.state.config.reader_port).strip()
        ports = {item.device.upper() for item in available_serial_ports()}
        if port.upper() not in ports:
            return False
        reader = self.state.chip_reader
        if reader is None or isinstance(reader, UnavailableChipReader):
            return False
        return True

    def _apply_reader_hint(self) -> None:
        if self._reader_configured() and not self._reader_connected():
            self.search.hint_text = _READER_HINT
            self.search.hint_style = ft.TextStyle(
                color=theme.COLORS["hint_warning"],
                size=theme.role_size(theme.TextRole.META),
            )
        else:
            self.search.hint_text = _SEARCH_HINT
            self.search.hint_style = ft.TextStyle(
                color=theme.COLORS["text_secondary"],
                size=theme.role_size(theme.TextRole.META),
            )

    def _start_chip_listen(self) -> None:
        self.state.stop_chip_listen()
        if not self._reader_connected():
            return
        reader = self.state.chip_reader
        if reader is None:
            return
        stop = threading.Event()
        self.state.chip_listen_stop = stop

        def _loop() -> None:
            try:
                reader.start()
            except Exception:
                return
            while not stop.is_set():
                try:
                    chip = reader.read_once(
                        timeout_seconds=1.0,
                        cancel_event=stop,
                    )
                except ChipReaderTimeout:
                    continue
                except ChipReaderCancelled:
                    break
                except Exception:
                    break
                code = chip.code
                self.page.run_thread(lambda c=code: self._on_chip_code(c))
            try:
                reader.stop()
            except Exception:
                pass

        threading.Thread(target=_loop, name="jll-chip-listen", daemon=True).start()

    def _on_chip_code(self, code: str) -> None:
        if not code:
            return
        try:
            identified = self.state.read_service.identify_chip(code)
        except Exception as exc:
            message_dialog(self.page, title="Čip", body=str(exc))
            self.focus_search()
            return
        if identified.opens_card and identified.owner is not None:
            self._open(identified.owner.evidcislo)
            self.focus_search()
            return
        message_dialog(self.page, title="Čip", body=identified.message)
        self.focus_search()

    def _panel(self, content: ft.Control, *, expand: bool | int | None = None) -> ft.Container:
        return ft.Container(
            content=content,
            bgcolor=theme.COLORS["surface"],
            border=ft.border.all(
                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
            ),
            border_radius=6,
            padding=theme.SPACING["md"],
            expand=expand,
        )

    def _build(self) -> ft.Control:
        list_panel = self._panel(
            ft.Column(
                [
                    self.search,
                    ft.Text(
                        "Strávníci",
                        size=theme.role_size(theme.TextRole.ACTION),
                        weight=ft.FontWeight.W_700,
                    ),
                    self.list_view,
                ],
                expand=True,
                spacing=theme.SPACING["sm"],
            ),
            expand=False,
        )
        list_panel.width = theme.LIST_WIDTH
        detail_panel = self._panel(self.detail, expand=True)
        if not self.vm.can_view():
            return empty_state(
                "Strávníci",
                "Nemáte oprávnění zobrazit strávníky.",
            )
        self.detail.controls = [
            empty_state("Vyberte strávníka", "Hledejte vlevo a otevřete kartu.")
        ]
        root = ft.Row(
            [list_panel, detail_panel],
            expand=True,
            spacing=theme.SPACING["md"],
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self._refresh_list(self.vm.list_initial())
        return root

    def _refresh_list(self, results, *, prefer_evid: int | None = None) -> None:
        self._results = list(results)
        self.list_view.controls.clear()
        if not self._results:
            self._focus_index = 0
            self.list_view.controls.append(
                ft.Text(
                    "Žádní strávníci v povolených kategoriích.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            )
            return

        if prefer_evid is not None:
            for idx, item in enumerate(self._results):
                if item.evidcislo == prefer_evid:
                    self._focus_index = idx
                    break
            else:
                self._focus_index = 0
        else:
            self._focus_index = 0

        self._render_list_rows()

    def _render_list_rows(self) -> None:
        self.list_view.controls.clear()
        for idx, item in enumerate(self._results):
            focused = idx == self._focus_index
            opened = item.evidcislo == self.state.selected_evidcislo
            class_bit = f" {item.class_name}" if item.class_name else ""
            if focused:
                bg = theme.COLORS["selected"]
            elif opened:
                bg = theme.COLORS["accent_soft"]
            else:
                bg = None
            self.list_view.controls.append(
                ft.Container(
                    content=ft.Text(
                        f"{item.name}{class_bit}",
                        size=theme.role_size(theme.TextRole.BODY),
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        weight=ft.FontWeight.W_600 if focused else ft.FontWeight.W_400,
                        color=theme.COLORS["text_primary"],
                    ),
                    bgcolor=bg,
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    border_radius=4,
                    border=(
                        ft.border.all(1, theme.COLORS["accent"]) if focused else None
                    ),
                    on_click=lambda _e, evid=item.evidcislo: self._open(evid),
                    ink=True,
                )
            )

    def _move_focus(self, delta: int) -> None:
        if not self._results:
            return
        self._focus_index = max(
            0, min(len(self._results) - 1, self._focus_index + delta)
        )
        self._render_list_rows()
        self.page.update()
        self.focus_search()

    def _confirm_focused(self) -> None:
        if not self._results:
            return
        idx = max(0, min(self._focus_index, len(self._results) - 1))
        self._open(self._results[idx].evidcislo)

    def _on_search(self, e: ft.ControlEvent) -> None:
        results = self.vm.search(e.control.value or "")
        self._refresh_list(results)
        self.page.update()

    def _on_search_submit(self, _e: ft.ControlEvent) -> None:
        self._confirm_focused()

    def _on_page_key(self, e: ft.KeyboardEvent) -> None:
        key = (e.key or "").casefold().replace(" ", "")
        if key in {"arrowdown", "down"}:
            self._move_focus(1)
        elif key in {"arrowup", "up"}:
            self._move_focus(-1)

    def _open(self, evidcislo: int) -> None:
        try:
            self._day = self.vm.select_diner(evidcislo)
        except Exception as exc:
            message_dialog(self.page, title="Strávník", body=str(exc))
            return
        self._render_detail()
        query = self.search.value or ""
        self._refresh_list(self.vm.search(query), prefer_evid=evidcislo)
        self.page.update()
        self.focus_search()

    def _render_detail(self) -> None:
        day = self._day
        assert day is not None
        diner = day.diner
        edit = self.state.diner_edit_state()
        chip_state = self.state.chip_assign_state()
        create = self.state.diner_create_state()

        title = ft.Text(
            diner.name,
            size=theme.role_size(theme.TextRole.PRIMARY),
            weight=ft.FontWeight.W_700,
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        )
        meta = ft.Text(
            f"{diner.class_name or diner.category} · ev. {diner.evidcislo}",
            size=theme.role_size(theme.TextRole.META),
            color=theme.COLORS["text_secondary"],
        )
        finance = ft.Text(
            f"Kredit {self.vm.format_credit(diner.available_credit)}"
            f"   Čip {diner.chip_number or '—'}",
            size=theme.role_size(theme.TextRole.META),
            color=theme.COLORS["text_secondary"],
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=1,
        )
        actions = ft.Row(
            [
                ft.OutlinedButton(
                    "Upravit",
                    disabled=not edit.allowed,
                    tooltip=disabled_hint(edit) or None,
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                    on_click=lambda _e: message_dialog(
                        self.page,
                        title="Úprava strávníka",
                        body=disabled_hint(edit) or "Nedostupné.",
                    ),
                ),
                ft.TextButton(
                    "Detail čipu",
                    tooltip=disabled_hint(chip_state) or "Náhled čipu",
                    on_click=lambda _e: message_dialog(
                        self.page,
                        title="Čip",
                        body=disabled_hint(chip_state)
                        if not chip_state.allowed
                        else (diner.chip_number or "Bez čipu"),
                    ),
                ),
                ft.FilledButton(
                    "Ruční odběr",
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                    on_click=lambda _e: self._manual_pickup(),
                ),
                ft.OutlinedButton(
                    "+ Nový",
                    disabled=not create.allowed,
                    tooltip=disabled_hint(create) or None,
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                    on_click=lambda _e: message_dialog(
                        self.page,
                        title="Nový strávník",
                        body=disabled_hint(create) or "Zápis zatím není povolen.",
                    ),
                ),
            ],
            spacing=theme.SPACING["xs"],
            tight=True,
            wrap=False,
        )
        header = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column([title, meta, finance], spacing=2, tight=True, expand=True),
                        actions,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=theme.SPACING["sm"],
                ),
            ],
            spacing=0,
            tight=True,
        )
        month_row = ft.Row(
            [
                self._month_switcher(day),
                ft.Text(
                    f"Přihlášky · {self.vm.format_month_year(day.target_date)}",
                    size=theme.role_size(theme.TextRole.ACTION),
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=theme.SPACING["md"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.detail.controls = [
            header,
            month_row,
            self._month_grid(day),
            self._menu_panel(day),
        ]
        self.page.update()

    def _month_switcher(self, day: DinerDay) -> ft.Control:
        current, future = self.vm.month_options()
        active_is_future = (
            day.target_date.year == future.year and day.target_date.month == future.month
        )

        def _btn(option, *, selected: bool, future_month: bool) -> ft.Control:
            bg = theme.COLORS["accent"] if selected else "#6F8FA8"
            border = ft.border.all(2, "#FFFFFF") if selected else None
            return ft.Container(
                content=ft.Text(
                    option.label,
                    size=theme.role_size(theme.TextRole.ACTION),
                    color="#FFFFFF",
                    weight=ft.FontWeight.W_700,
                ),
                bgcolor=bg,
                padding=ft.padding.symmetric(horizontal=14, vertical=6),
                border_radius=20,
                border=border,
                ink=True,
                on_click=lambda _e, fut=future_month: self._switch_month(fut),
                tooltip="Aktivní měsíc" if selected else "Přepnout měsíc",
            )

        return ft.Row(
            [
                _btn(current, selected=not active_is_future, future_month=False),
                _btn(future, selected=active_is_future, future_month=True),
            ],
            spacing=theme.SPACING["sm"],
            tight=True,
        )

    def _switch_month(self, future: bool) -> None:
        try:
            refreshed = self.vm.switch_month(future=future)
        except Exception as exc:
            message_dialog(self.page, title="Měsíc", body=str(exc))
            return
        if refreshed is None:
            return
        self._day = refreshed
        self._render_detail()
        self.focus_search()

    def _month_grid(self, day: DinerDay) -> ft.Control:
        rows = self.vm.month_rows(day)
        if not rows:
            return ft.Text("Žádná data přihlášek.", size=theme.role_size(theme.TextRole.META))
        label_w = int(theme.scaled(64))
        cell_h = theme.scaled(22)
        today_h = theme.scaled(26)
        meta_size = theme.role_size(theme.TextRole.META)
        actual_today = day.server_now.date()
        selected_day = day.target_date.day
        viewing_actual_today = day.target_date == actual_today

        header_cells: list[ft.Control] = [ft.Container(width=label_w)]
        for cell in rows[0].cells:
            is_today_col = viewing_actual_today and cell.day == actual_today.day
            is_selected_col = cell.day == selected_day and not is_today_col
            if is_today_col:
                header_bg, header_color, header_weight = (
                    theme.COLORS["accent"],
                    "#FFFFFF",
                    ft.FontWeight.W_700,
                )
            elif is_selected_col:
                header_bg, header_color, header_weight = (
                    theme.COLORS["accent_soft"],
                    theme.COLORS["text_primary"],
                    ft.FontWeight.W_600,
                )
            else:
                header_bg, header_color, header_weight = (
                    None,
                    theme.COLORS["text_secondary"],
                    ft.FontWeight.W_400,
                )
            header_cells.append(
                ft.Container(
                    expand=True,
                    alignment=ft.alignment.center,
                    bgcolor=header_bg,
                    border_radius=4,
                    padding=ft.padding.symmetric(vertical=2),
                    content=ft.Text(
                        str(cell.day),
                        size=meta_size if (is_today_col or is_selected_col) else max(10.0, meta_size - 1),
                        weight=header_weight,
                        color=header_color,
                    ),
                )
            )
        grid_rows = [ft.Row(header_cells, spacing=1)]
        for row in rows:
            cells: list[ft.Control] = [
                ft.Container(
                    width=label_w,
                    content=ft.Text(
                        row.meal_type,
                        size=meta_size,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                )
            ]
            for cell in row.cells:
                is_today_col = viewing_actual_today and cell.day == actual_today.day
                is_selected_col = cell.day == selected_day
                bg = None
                weight = ft.FontWeight.W_400
                if cell.is_selected and not cell.is_ordered and not cell.is_subscribed:
                    bg = (
                        theme.COLORS["today_column"]
                        if is_today_col
                        else theme.COLORS["accent_soft"]
                    )
                if cell.is_ordered:
                    bg = (
                        theme.COLORS["ordered_selected"]
                        if cell.is_selected
                        else theme.COLORS["ordered"]
                    )
                    weight = ft.FontWeight.W_700
                elif cell.is_subscribed:
                    bg = (
                        theme.COLORS["subscribed_selected"]
                        if cell.is_selected
                        else theme.COLORS["subscribed"]
                    )
                elif not cell.is_cooking and cell.state == "*":
                    bg = theme.COLORS["non_cooking"]
                if is_today_col and bg is None:
                    bg = theme.COLORS["today_column"]
                elif is_selected_col and not is_today_col and bg is None:
                    bg = theme.COLORS["accent_soft"]
                label = cell.state or ""
                border = None
                if is_today_col:
                    border = ft.border.all(2, theme.COLORS["today_column_border"])
                elif is_selected_col:
                    border = ft.border.all(1, theme.COLORS["accent"])
                cells.append(
                    ft.Container(
                        expand=True,
                        height=today_h if is_today_col else cell_h,
                        alignment=ft.alignment.center,
                        bgcolor=bg,
                        border_radius=3,
                        border=border,
                        content=ft.Text(
                            label,
                            size=meta_size if is_today_col else max(10.0, meta_size - 1),
                            weight=ft.FontWeight.W_700 if is_today_col else weight,
                        ),
                        on_click=lambda _e, d=cell.day: self._pick_day(d),
                    )
                )
            grid_rows.append(ft.Row(cells, spacing=1))
        return ft.Container(
            content=ft.Column(grid_rows, spacing=1, tight=True),
            bgcolor=theme.COLORS["surface_muted"],
            border=ft.border.all(
                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
            ),
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
        self.focus_search()

    def _menu_panel(self, day: DinerDay) -> ft.Control:
        title = ft.Text(
            f"Jídelníček · {self.vm.format_day_month(day.target_date)}",
            size=theme.role_size(theme.TextRole.ACTION),
            weight=ft.FontWeight.W_600,
        )
        blocks: list[ft.Control] = [title]
        for meal in day.meals:
            blocks.append(self._meal_block(meal))
        return ft.Container(
            content=ft.Column(blocks, spacing=theme.SPACING["xs"], tight=True),
            bgcolor=theme.COLORS["surface_muted"],
            border=ft.border.all(
                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
            ),
            padding=theme.SPACING["sm"],
            border_radius=6,
        )

    def _meal_block(self, meal: MealDay) -> ft.Control:
        ordered = getattr(meal, "ordered_menu", None)
        if ordered is None and meal.current_state and meal.current_state.isdigit():
            ordered = int(meal.current_state)

        # Stravný den (S/N/objednáno) bez zveřejněného jídelníčku → světle červená hláška.
        is_meal_day = meal.current_state in {"S", "N"} or (
            meal.current_state is not None and meal.current_state.isdigit()
        )
        unpublished_color = (
            theme.COLORS["hint_warning"]
            if is_meal_day
            else theme.COLORS["text_secondary"]
        )

        option_controls: list[ft.Control] = []
        if not meal.options:
            option_controls.append(
                ft.Text(
                    "Jídelníček není zveřejněn",
                    size=theme.role_size(theme.TextRole.META),
                    color=unpublished_color,
                    weight=ft.FontWeight.W_600 if is_meal_day else ft.FontWeight.W_400,
                )
            )
        for option in meal.options:
            is_ordered = ordered == option.menu
            price = self.vm.format_money(option.price)
            unpublished = not getattr(option, "published", True)
            dish = option.dish_name or ("Jídelníček není zveřejněn" if unpublished else "Menu")
            label = f"{option.menu} · cena {price} · {dish}"
            text_color = (
                unpublished_color
                if unpublished and is_meal_day
                else theme.COLORS["text_primary"]
            )
            option_controls.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=theme.role_size(theme.TextRole.META),
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        color=text_color,
                        weight=(
                            ft.FontWeight.W_600
                            if unpublished and is_meal_day
                            else ft.FontWeight.W_400
                        ),
                    ),
                    bgcolor=(
                        theme.COLORS["ordered"]
                        if is_ordered
                        else theme.COLORS["surface"]
                    ),
                    border=ft.border.all(1, theme.COLORS["block_border"]),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=4,
                    expand=True,
                    on_click=(
                        None
                        if is_ordered
                        else lambda _e, m=meal.meal_type, menu=option.menu: self._order(
                            m, menu
                        )
                    ),
                )
            )

        unsub = ft.Container(width=0)
        if ordered is not None and self.vm.can_change_orders():
            unsub = ft.TextButton(
                "Odhlásit",
                style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=8, vertical=0)),
                on_click=lambda _e, m=meal.meal_type, menu=ordered: self._unsubscribe(
                    m, menu
                ),
            )

        return ft.Row(
            [
                ft.Container(
                    width=72,
                    content=ft.Text(
                        meal.meal_type,
                        size=theme.role_size(theme.TextRole.META),
                        weight=ft.FontWeight.W_600,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ),
                *option_controls,
                unsub,
            ],
            spacing=theme.SPACING["xs"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

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
        self.focus_search()

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
        self.focus_search()

    def _manual_pickup(self) -> None:
        if self._day is None:
            return
        service = self.state.serving_service
        if service is None:
            message_dialog(self.page, title="Odběr", body="Výdejní služba není dostupná.")
            return
        if not self.state.has_perm(Permission.ORDERS_CHANGE):
            message_dialog(self.page, title="Odběr", body="Nemáte oprávnění k odběru stravy.")
            return
        evidcislo = self._day.diner.evidcislo
        try:
            meals = service.meals_ready(evidcislo)
        except Exception as exc:
            message_dialog(self.page, title="Odběr", body=str(exc))
            return
        ready = []
        for meal in meals:
            raw = meal.raw
            vydat = raw.get("vydat")
            if vydat is False or str(vydat).lower() in {"f", "false", "0"}:
                continue
            ready.append(meal)
        if not ready:
            message_dialog(
                self.page,
                title="Ruční odběr",
                body="Pro tohoto strávníka dnes není žádná strava k výdeji.",
            )
            return

        list_view = ft.Column(spacing=6, tight=True)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Ruční odběr stravy",
                size=theme.role_size(theme.TextRole.PRIMARY),
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(content=list_view, width=420),
            actions=[
                ft.TextButton(
                    "Zavřít",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                )
            ],
        )

        def _serve(prihlaska_id: int, label: str):
            def _handler(_e):
                try:
                    ok = service.record_pickup(prihlaska_id)
                except Exception as exc:
                    message_dialog(self.page, title="Odběr", body=str(exc))
                    return
                dialog.open = False
                self.page.update()
                if ok:
                    message_dialog(
                        self.page,
                        title="Odběr",
                        body=f"Odběr zaznamenán: {label}",
                    )
                else:
                    message_dialog(
                        self.page,
                        title="Odběr",
                        body="Databáze odběr nepotvrdila (zapis_odber=false).",
                    )

            return _handler

        for meal in ready:
            raw = meal.raw
            typ = str(raw.get("typ_stravy") or "Strava")
            menu = raw.get("menu")
            place = raw.get("vydejni_misto")
            prihlaska_id = int(raw["id_prihlasky"])
            label = f"{typ} · menu {menu}"
            if place:
                label = f"{label} · {place}"
            list_view.controls.append(
                ft.Row(
                    [
                        ft.Text(label, size=theme.role_size(theme.TextRole.BODY), expand=True),
                        ft.FilledButton("Vydat", on_click=_serve(prihlaska_id, label)),
                    ]
                )
            )

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()
