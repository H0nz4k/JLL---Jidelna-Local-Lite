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
        if cfg is None:
            return False
        if cfg.reader_mode == "auto_elatec":
            return True
        return bool(cfg.reader_port and str(cfg.reader_port).strip())

    def _reader_connected(self) -> bool:
        if not self._reader_configured():
            return False
        reader = self.state.chip_reader
        if reader is None or isinstance(reader, UnavailableChipReader):
            return False
        cfg = self.state.config
        assert cfg is not None
        if cfg.reader_mode == "auto_elatec":
            try:
                from ...chip_reader import AutoElatecChipReader, ReaderState
                from ...reader_discovery import ReaderDiscoveryStatus

                if isinstance(reader, AutoElatecChipReader):
                    snap = reader.discovery_snapshot()
                    return snap.status is ReaderDiscoveryStatus.FOUND
                status = reader.status()
                return status.state not in {
                    ReaderState.DISCONNECTED,
                    ReaderState.ERROR,
                }
            except Exception:
                return False
        port = str(cfg.reader_port or "").strip()
        ports = {item.device.upper() for item in available_serial_ports()}
        return bool(port) and port.upper() in ports

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
        # Detail je workspace: bez silného bordered expand panelu (empty state).
        detail_host = ft.Container(
            content=self.detail,
            expand=True,
            bgcolor=theme.COLORS["background"],
            padding=ft.padding.only(left=theme.SPACING["sm"]),
            alignment=ft.alignment.top_left,
        )
        if not self.vm.can_view():
            return empty_state(
                "Strávníci",
                "Nemáte oprávnění zobrazit strávníky.",
            )
        self.detail.controls = [
            ft.Container(
                content=empty_state(
                    "Vyberte strávníka",
                    "Hledejte vlevo a otevřete kartu.",
                ),
                padding=theme.SPACING["md"],
                bgcolor=theme.COLORS["surface"],
                border=ft.border.all(
                    theme.CONTENT_BORDER_WIDTH, theme.COLORS["border"]
                ),
                border_radius=6,
                width=420,
            )
        ]
        root = ft.Row(
            [list_panel, detail_host],
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
        chip_view = self.state.chip_view_state()
        create = self.state.diner_create_state()

        info_size = theme.role_size(theme.TextRole.BODY)
        meta_size = theme.role_size(theme.TextRole.META)
        primary_size = theme.role_size(theme.TextRole.PRIMARY)
        credit_value = diner.available_credit
        credit_text = self.vm.format_credit(credit_value)
        credit_color = (
            theme.COLORS["danger"]
            if credit_value < 0
            else theme.COLORS["text_primary"]
        )
        chip_bit = f"Čip {diner.chip_number}" if diner.chip_number else "Bez čipu"
        row1 = ft.Row(
            [
                ft.Text(
                    diner.name,
                    size=primary_size,
                    weight=ft.FontWeight.W_700,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                ),
                ft.Text(
                    spans=[
                        ft.TextSpan(
                            "Kredit ",
                            ft.TextStyle(
                                size=meta_size,
                                color=theme.COLORS["text_secondary"],
                                weight=ft.FontWeight.W_600,
                            ),
                        ),
                        ft.TextSpan(
                            credit_text,
                            ft.TextStyle(
                                size=primary_size,
                                color=credit_color,
                                weight=ft.FontWeight.W_700,
                            ),
                        ),
                    ],
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                ),
            ],
            spacing=theme.SPACING["xl"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
            wrap=True,
        )
        row2 = ft.Text(
            f"{diner.class_name or diner.category} · ev. {diner.evidcislo} · {chip_bit}",
            size=info_size,
            color=theme.COLORS["text_secondary"],
            weight=ft.FontWeight.W_500,
            overflow=ft.TextOverflow.ELLIPSIS,
            max_lines=2,
        )
        row3 = ft.Row(
            [
                ft.OutlinedButton(
                    "Upravit",
                    disabled=not edit.allowed,
                    tooltip=disabled_hint(edit) or None,
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                    on_click=lambda _e: self._open_edit_dialog(),
                ),
                ft.OutlinedButton(
                    "Detail čipu",
                    disabled=not chip_view.allowed,
                    tooltip=disabled_hint(chip_view) or "Náhled čipu",
                    style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=12, vertical=4)),
                    on_click=lambda _e: self._open_chip_detail(),
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
                    on_click=lambda _e: self._open_create_dialog(),
                ),
            ],
            spacing=theme.SPACING["xs"],
            tight=True,
            wrap=True,
        )
        header = ft.Column(
            [row1, row2, row3],
            spacing=theme.SPACING["xs"],
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
            self._payments_panel(diner.evidcislo),
            month_row,
            self._month_grid(day),
            self._menu_panel(day),
        ]
        self.page.update()

    def _payments_panel(self, evidcislo: int) -> ft.Control:
        view = self.state.payments_view_state()
        post = self.state.payments_post_state()
        if not view.allowed:
            return ft.Container(height=0)
        rows: list[ft.Control] = []
        history = self.state.payment_history_service
        if history is not None:
            try:
                page = history.list_for_diner(evidcislo, limit=8, offset=0)
                for item in page.items:
                    amount = self.vm.format_credit(item.amount)
                    when = item.booked_on.strftime("%d.%m.%Y")
                    clock = (
                        item.booked_at.strftime("%H:%M")
                        if item.booked_at is not None
                        else ""
                    )
                    label = item.payment_method_label or item.ledger_type_label
                    sign = "+" if item.amount >= 0 else ""
                    rows.append(
                        ft.TextButton(
                            f"{when}  {clock}   {sign}{amount}   {label}".strip(),
                            style=ft.ButtonStyle(
                                padding=ft.padding.symmetric(horizontal=0, vertical=0)
                            ),
                            on_click=lambda _e, pid=item.id: self._payment_detail(pid),
                        )
                    )
                if not rows:
                    rows.append(
                        ft.Text(
                            "Žádné platby",
                            size=theme.role_size(theme.TextRole.BODY),
                            color=theme.COLORS["text_secondary"],
                        )
                    )
            except Exception as exc:
                rows.append(
                    ft.Text(
                        str(exc),
                        size=theme.role_size(theme.TextRole.BODY),
                        color=theme.COLORS["danger"],
                    )
                )
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "Platby",
                            size=theme.role_size(theme.TextRole.ACTION),
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.TextButton(
                            "Zaúčtovat platbu",
                            disabled=not post.allowed,
                            tooltip=disabled_hint(post) or None,
                            on_click=lambda _e: self._open_post_payment(),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                *rows,
            ],
            spacing=2,
            tight=True,
        )

    def _payment_detail(self, penden_id: int) -> None:
        service = self.state.payment_history_service
        if service is None:
            return
        try:
            item = service.get_detail(penden_id)
        except Exception as exc:
            message_dialog(self.page, title="Detail platby", body=str(exc))
            return
        clock = (
            item.booked_at.strftime("%H:%M:%S") if item.booked_at is not None else "—"
        )
        body = "\n".join(
            [
                f"Datum: {item.booked_on.strftime('%d.%m.%Y')} {clock}",
                f"Částka: {self.vm.format_credit(item.amount)}",
                f"Období: {item.period_month}/{item.period_year}",
                f"Typ: {item.ledger_type_label} ({item.ledger_type})",
                f"Způsob: {item.payment_method_label or item.payment_method_code or '—'}",
                f"Účet: {item.account or '—'}",
                f"Služba: {item.service_type or '—'}",
                f"Poznámka: {item.note or '—'}",
                f"Kategorie (snapshot): {item.category_snapshot or '—'}",
                f"Třída (snapshot): {item.class_snapshot or '—'}",
                f"ID deníku: {item.id}",
            ]
        )
        message_dialog(self.page, title="Detail platby", body=body)

    def _open_post_payment(self) -> None:
        if self._day is None:
            return
        state = self.state.payments_post_state()
        if not state.allowed:
            message_dialog(
                self.page, title="Zaúčtovat platbu", body=disabled_hint(state) or ""
            )
            return
        service = self.state.payment_service
        if service is None:
            return
        try:
            methods = service.list_payment_methods(include_cash=False)
            accounts = service.list_accounts()
        except Exception as exc:
            message_dialog(self.page, title="Zaúčtovat platbu", body=str(exc))
            return
        if not methods or not accounts:
            message_dialog(
                self.page,
                title="Zaúčtovat platbu",
                body="Chybí číselník způsobů platby nebo účtů.",
            )
            return
        amount_field = ft.TextField(label="Částka", autofocus=True)
        note_field = ft.TextField(label="Poznámka")
        method_dd = ft.Dropdown(
            label="Způsob platby",
            options=[ft.dropdown.Option(key=m.code, text=m.label) for m in methods],
            value=next((m.code for m in methods if m.code == "4"), methods[0].code),
        )
        account_dd = ft.Dropdown(
            label="Účet",
            options=[ft.dropdown.Option(key=a.code, text=a.label) for a in accounts],
            value=next((a.code for a in accounts if a.code == "STRAV"), accounts[0].code),
        )
        service_field = ft.TextField(label="Typ služby", value="Oběd-A")
        period_dd = ft.Dropdown(
            label="Účtovaný měsíc",
            options=[
                ft.dropdown.Option(key="this", text="Tento měsíc"),
                ft.dropdown.Option(key="next", text="Budoucí měsíc"),
            ],
            value="this",
        )

        def _save(_e=None) -> None:
            from decimal import Decimal, InvalidOperation

            from ...payment_models import ManualPaymentCommand

            raw = (amount_field.value or "").strip().replace(" ", "").replace(",", ".")
            try:
                amount = Decimal(raw)
            except (InvalidOperation, ValueError):
                message_dialog(self.page, title="Zaúčtovat platbu", body="Neplatná částka.")
                return
            actor, version = self._actor_bits()
            try:
                this_period, next_period = service.accounting_periods()
                month = this_period[1] if period_dd.value == "this" else next_period[1]
                service.post_manual(
                    ManualPaymentCommand(
                        evidcislo=self._day.diner.evidcislo,
                        amount=amount,
                        payment_method_code=method_dd.value or "",
                        account=account_dd.value or "STRAV",
                        service_type=(service_field.value or "").strip(),
                        period_month=int(month),
                        note=(note_field.value or "").strip(),
                        actor=actor,
                        client_version=version,
                    )
                )
            except Exception as exc:
                message_dialog(self.page, title="Zaúčtovat platbu", body=str(exc))
                return
            dialog.open = False
            self.page.update()
            self._open(self._day.diner.evidcislo)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Zaúčtovat platbu"),
            content=ft.Column(
                [
                    amount_field,
                    method_dd,
                    account_dd,
                    service_field,
                    period_dd,
                    note_field,
                ],
                tight=True,
                spacing=theme.SPACING["xs"],
                height=360,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(
                    "Zrušit",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Zaúčtovat", on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _month_switcher(self, day: DinerDay) -> ft.Control:
        current, future = self.vm.month_options()
        active_is_future = (
            day.target_date.year == future.year and day.target_date.month == future.month
        )

        def _btn(option, *, viewing: bool, future_month: bool) -> ft.Control:
            # Zvýrazni měsíc, na který lze přepnout; aktuálně zobrazený je tlumený.
            bg = "#6F8FA8" if viewing else theme.COLORS["accent"]
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
                ink=not viewing,
                on_click=(
                    None
                    if viewing
                    else (lambda _e, fut=future_month: self._switch_month(fut))
                ),
                tooltip="Zobrazený měsíc" if viewing else "Přepnout měsíc",
                opacity=0.72 if viewing else 1.0,
            )

        return ft.Row(
            [
                _btn(current, viewing=not active_is_future, future_month=False),
                _btn(future, viewing=active_is_future, future_month=True),
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
        label_w = int(theme.scaled(76))
        cell_h = theme.scaled(28)
        today_h = theme.scaled(32)
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
                if cell.is_ordered and cell.is_picked_up:
                    bg = (
                        theme.COLORS["picked_selected"]
                        if cell.is_selected
                        else theme.COLORS["picked"]
                    )
                    weight = ft.FontWeight.W_700
                elif cell.is_ordered:
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
        picked = False
        if self._day is not None:
            picked = meal.picked_up_on(self._day.target_date.day)

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
            if is_ordered and picked:
                label = f"{label} · odebráno"
            text_color = (
                unpublished_color
                if unpublished and is_meal_day
                else theme.COLORS["text_primary"]
            )
            if is_ordered and picked:
                row_bg = theme.COLORS["picked"]
            elif is_ordered:
                row_bg = theme.COLORS["ordered"]
            else:
                row_bg = theme.COLORS["surface"]
            option_controls.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=theme.role_size(theme.TextRole.BODY),
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        color=text_color,
                        weight=(
                            ft.FontWeight.W_600
                            if unpublished and is_meal_day
                            else ft.FontWeight.W_400
                        ),
                    ),
                    bgcolor=row_bg,
                    border=ft.border.all(1, theme.COLORS["block_border"]),
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
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
        if ordered is not None and self.vm.can_change_orders() and not picked:
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
            meals = service.meals_ready_manual(evidcislo)
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
                    ok = service.record_pickup(
                        prihlaska_id,
                        evidcislo=evidcislo,
                    )
                except Exception as exc:
                    message_dialog(self.page, title="Odběr", body=str(exc))
                    return
                dialog.open = False
                self.page.update()
                if ok:
                    self._open(evidcislo)
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

    def _actor_bits(self) -> tuple[str, str]:
        assert self.state.business is not None
        actor = self.state.business.current_actor()
        return actor.audit_actor, actor.client_version

    def _open_create_dialog(self) -> None:
        create = self.state.diner_create_state()
        if not create.allowed:
            message_dialog(
                self.page,
                title="Nový strávník",
                body=disabled_hint(create) or "Nedostupné.",
            )
            return
        cats = sorted(self.state.business.current_policy().scope()) if self.state.business else []
        name_field = ft.TextField(label="Příjmení a jméno", autofocus=True)
        class_field = ft.TextField(label="Třída")
        cat_field = ft.Dropdown(
            label="Kategorie",
            options=[ft.dropdown.Option(c) for c in cats],
            value=cats[0] if cats else None,
        )

        def _save(_e=None) -> None:
            service = self.state.diner_service
            if service is None:
                message_dialog(self.page, title="Nový strávník", body="Služba není dostupná.")
                return
            from ...diner_models import CreateDinerCommand

            actor, version = self._actor_bits()
            try:
                result = service.create(
                    CreateDinerCommand(
                        jmeno=name_field.value or "",
                        kategorie=cat_field.value or "",
                        trida=class_field.value or "",
                        actor=actor,
                        client_version=version,
                    )
                )
            except Exception as exc:
                message_dialog(self.page, title="Nový strávník", body=str(exc))
                return
            dialog.open = False
            self.page.update()
            self._open(result.evidcislo)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nový strávník", weight=ft.FontWeight.W_700),
            content=ft.Column(
                [name_field, cat_field, class_field],
                tight=True,
                spacing=8,
                width=360,
            ),
            actions=[
                ft.TextButton(
                    "Zrušit",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Uložit", on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _open_edit_dialog(self) -> None:
        if self._day is None:
            return
        edit = self.state.diner_edit_state()
        if not edit.allowed:
            message_dialog(
                self.page,
                title="Úprava strávníka",
                body=disabled_hint(edit) or "Nedostupné.",
            )
            return
        diner = self._day.diner
        name_field = ft.TextField(label="Jméno", value=diner.name, autofocus=True)
        class_field = ft.TextField(label="Třída", value=diner.class_name or "")
        note_field = ft.TextField(label="Poznámka", value=diner.poznamka or "")
        email_field = ft.TextField(label="E-mail", value=diner.email or "")
        street_field = ft.TextField(label="Ulice", value=diner.ulice or "")
        city_field = ft.TextField(label="Město", value=diner.mesto or "")

        def _save(_e=None) -> None:
            service = self.state.diner_service
            if service is None:
                message_dialog(self.page, title="Úprava", body="Služba není dostupná.")
                return
            from ...diner_models import EditDinerPersonalCommand

            actor, version = self._actor_bits()
            try:
                service.edit_personal(
                    EditDinerPersonalCommand(
                        evidcislo=diner.evidcislo,
                        expected_updated_dt=diner.updated_dt,
                        fields={
                            "jmeno": name_field.value or "",
                            "trida": class_field.value or "",
                            "poznamka": note_field.value or "",
                            "email": email_field.value or "",
                            "ulice": street_field.value or "",
                            "mesto": city_field.value or "",
                        },
                        actor=actor,
                        client_version=version,
                    )
                )
            except Exception as exc:
                message_dialog(self.page, title="Úprava", body=str(exc))
                return
            dialog.open = False
            self.page.update()
            self._open(diner.evidcislo)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Upravit strávníka", weight=ft.FontWeight.W_700),
            content=ft.Column(
                [
                    name_field,
                    class_field,
                    street_field,
                    city_field,
                    email_field,
                    note_field,
                    ft.Text(
                        "Kategorie a finance se zde nemění.",
                        size=theme.role_size(theme.TextRole.META),
                        color=theme.COLORS["text_secondary"],
                    ),
                ],
                tight=True,
                spacing=8,
                width=360,
                scroll=ft.ScrollMode.AUTO,
                height=360,
            ),
            actions=[
                ft.TextButton(
                    "Zrušit",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Uložit", on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _primary_chip_status(self) -> str | None:
        if self._day is None:
            return None
        diner = self._day.diner
        if diner.chips:
            for chip in diner.chips:
                if diner.chip_number and chip.code == diner.chip_number:
                    return chip.status_code
            return diner.chips[0].status_code
        if diner.chip_number:
            return "P"
        return None

    def _chip_actions_for_status(self, status_code: str | None) -> list[str]:
        """UI relevance labels for chip detail modal (permission still applied)."""

        if status_code is None:
            return ["assign"]
        if status_code == "P":
            return ["return", "block", "lost"]
        if status_code == "B":
            return ["unblock"]
        return ["assign"]

    def _open_chip_detail(self) -> None:
        if self._day is None:
            return
        chip_view = self.state.chip_view_state()
        if not chip_view.allowed:
            message_dialog(
                self.page,
                title="Detail čipu",
                body=disabled_hint(chip_view) or "Nedostupné.",
            )
            return
        diner = self._day.diner
        assign = self.state.chip_assign_state()
        ret = self.state.chip_return_state()
        block = self.state.chip_block_state()
        lost = self.state.chip_lost_state()
        unblock = self.state.chip_unblock_state()
        status_code = self._primary_chip_status()
        wanted = set(self._chip_actions_for_status(status_code))

        if diner.chips:
            chip_code = diner.chip_number or diner.chips[0].code
            status_label = next(
                (chip.status_label for chip in diner.chips if chip.code == chip_code),
                diner.chips[0].status_label,
            )
        elif diner.chip_number:
            chip_code = diner.chip_number
            status_label = "Přidělen"
        else:
            chip_code = "—"
            status_label = "Bez čipu"

        history_controls: list[ft.Control] = []
        service = self.state.chip_command_service
        if service is not None:
            try:
                history = service.load_history(diner.evidcislo)
                for item in history[:12]:
                    when = (
                        item.issued_at.strftime("%d.%m.%Y")
                        if item.issued_at is not None
                        else "—"
                    )
                    history_controls.append(
                        ft.Text(
                            f"{when} · {item.code} · {item.status_label}",
                            size=theme.role_size(theme.TextRole.META),
                            color=theme.COLORS["text_secondary"],
                        )
                    )
            except Exception:
                history_controls = []
        if not history_controls:
            history_controls.append(
                ft.Text(
                    "Žádná historie.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            )

        def _field(label: str, value: str) -> ft.Control:
            return ft.Column(
                [
                    ft.Text(
                        label,
                        size=theme.role_size(theme.TextRole.META),
                        color=theme.COLORS["text_secondary"],
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        value,
                        size=theme.role_size(theme.TextRole.BODY),
                        weight=ft.FontWeight.W_600,
                        selectable=True,
                    ),
                ],
                spacing=2,
                tight=True,
            )

        actions: list[ft.Control] = []
        if "assign" in wanted:
            actions.append(
                ft.FilledButton(
                    "Přidělit čip",
                    disabled=not assign.allowed,
                    tooltip=disabled_hint(assign) or None,
                    on_click=lambda _e: self._chip_assign(),
                )
            )
        if "return" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Vrátit",
                    disabled=not ret.allowed,
                    tooltip=disabled_hint(ret) or None,
                    on_click=lambda _e: self._chip_return(),
                )
            )
        if "block" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Blokovat",
                    disabled=not block.allowed,
                    tooltip=disabled_hint(block) or None,
                    on_click=lambda _e: self._chip_block(),
                )
            )
        if "lost" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Označit jako ztracený",
                    disabled=not lost.allowed,
                    tooltip=disabled_hint(lost) or None,
                    on_click=lambda _e: self._chip_lost(),
                )
            )
        if "unblock" in wanted:
            actions.append(
                ft.FilledButton(
                    "Odblokovat",
                    disabled=not unblock.allowed,
                    tooltip=disabled_hint(unblock) or None,
                    on_click=lambda _e: self._chip_unblock(),
                )
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Detail čipu",
                size=theme.role_size(theme.TextRole.PRIMARY),
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        _field("Čip", chip_code),
                        _field("Stav", status_label),
                        _field("Držitel", f"{diner.name} · ev. {diner.evidcislo}"),
                        ft.Text(
                            "Historie",
                            size=theme.role_size(theme.TextRole.META),
                            color=theme.COLORS["text_secondary"],
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Container(
                            content=ft.Column(
                                history_controls,
                                spacing=2,
                                tight=True,
                                scroll=ft.ScrollMode.AUTO,
                            ),
                            height=160,
                        ),
                        ft.Row(actions, spacing=theme.SPACING["sm"], wrap=True, tight=True),
                    ],
                    spacing=theme.SPACING["sm"],
                    tight=True,
                ),
                width=560,
            ),
            actions=[
                ft.TextButton(
                    "Zavřít",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                )
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _chip_code_for_action(self) -> str | None:
        if self._day is None:
            return None
        diner = self._day.diner
        if diner.chip_number:
            return diner.chip_number
        for chip in diner.chips:
            if chip.status_code == "P":
                return chip.code
        if diner.chips:
            return diner.chips[0].code
        return None

    def _chip_assign(self) -> None:
        if self._day is None:
            return
        state = self.state.chip_assign_state()
        if not state.allowed:
            message_dialog(self.page, title="Přidělit čip", body=disabled_hint(state) or "")
            return
        code_field = ft.TextField(label="Číslo čipu", autofocus=True)

        def _save(_e=None) -> None:
            service = self.state.chip_command_service
            if service is None:
                return
            from ...diner_models import ChipCommand

            actor, version = self._actor_bits()
            try:
                service.assign(
                    ChipCommand(
                        chip_code=code_field.value or "",
                        evidcislo=self._day.diner.evidcislo,
                        actor=actor,
                        client_version=version,
                    )
                )
            except Exception as exc:
                message_dialog(self.page, title="Přidělit čip", body=str(exc))
                return
            dialog.open = False
            self.page.update()
            self._open(self._day.diner.evidcislo)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Přidělit čip"),
            content=code_field,
            actions=[
                ft.TextButton(
                    "Zrušit",
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Přidělit", on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _chip_op(self, title: str, state_fn, handler_name: str) -> None:
        if self._day is None:
            return
        state = state_fn()
        if not state.allowed:
            message_dialog(self.page, title=title, body=disabled_hint(state) or "")
            return
        code = self._chip_code_for_action()
        if not code:
            message_dialog(self.page, title=title, body="Strávník nemá čip.")
            return
        service = self.state.chip_command_service
        if service is None:
            return
        from ...diner_models import ChipCommand

        actor, version = self._actor_bits()
        try:
            getattr(service, handler_name)(
                ChipCommand(
                    chip_code=code,
                    evidcislo=self._day.diner.evidcislo,
                    actor=actor,
                    client_version=version,
                )
            )
        except Exception as exc:
            message_dialog(self.page, title=title, body=str(exc))
            return
        self._open(self._day.diner.evidcislo)

    def _chip_block(self) -> None:
        self._chip_op("Blokovat čip", self.state.chip_block_state, "block")

    def _chip_return(self) -> None:
        self._chip_op("Vrátit čip", self.state.chip_return_state, "return_chip")

    def _chip_unblock(self) -> None:
        self._chip_op("Odblokovat čip", self.state.chip_unblock_state, "unblock")

    def _chip_lost(self) -> None:
        self._chip_op("Ztracený čip", self.state.chip_lost_state, "lost")
