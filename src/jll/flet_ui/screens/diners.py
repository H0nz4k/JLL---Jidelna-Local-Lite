"""Strávníci – hlavní workspace."""

from __future__ import annotations

import logging
import threading
import time
from datetime import date

import flet as ft

from ...application import ERROR_TEXTS
from ...chip_reader import (
    ChipReaderCancelled,
    ChipReaderTimeout,
    UnavailableChipReader,
    available_serial_ports,
)
from ...orders.concurrency import OrderVersionToken, ProbeStatus
from ...orders.errors import ErrorCode, OrderBusinessError
from ...orders.models import OrderAction
from ...policy import Permission
from ...read_models import DinerDay, HomeTodayOverview, MealDay
from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..components.home_overview import build_home_overview
from ..components.permission_state import disabled_hint
from ..idle_home import DINER_IDLE_HOME_SECONDS, IdleHomeController
from ..state import AppState
from ..viewmodels.diners import DinersViewModel

_SEARCH_HINT = "Hledat jméno / ev. číslo / čip…"
_HOME_REFRESH_SECONDS = 60
_ORDER_MARKER_POLL_SECONDS = 2.0
_SETTLE_DELAY_SECONDS = 0.4
# List keyboard focus: -1 = search field, 0..n-1 = list row.
_SEARCH_FOCUS = -1
LOGGER = logging.getLogger(__name__)


def next_list_focus(focus: int, delta: int, count: int) -> int:
    """Keyboard focus in diner list: search (−1) ↔ rows."""

    if count <= 0:
        return _SEARCH_FOCUS
    if focus < 0:
        return 0 if delta > 0 else _SEARCH_FOCUS
    nxt = focus + delta
    if nxt < 0:
        return _SEARCH_FOCUS
    return min(count - 1, nxt)


class DinersScreen:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        self.vm = DinersViewModel(state)
        self._day: DinerDay | None = None
        self._order_version: OrderVersionToken | None = None
        self._order_fingerprint: str | None = None
        self._order_poll_paused = False
        self._order_poll_generation = 0
        self._mutation_generation = 0
        self._results: list = []
        self._focus_index = _SEARCH_FOCUS
        self._home: HomeTodayOverview | None = None
        self._home_error: str | None = None
        self._home_visible = True
        self._idle = IdleHomeController(timeout_seconds=DINER_IDLE_HOME_SECONDS)
        self._idle.route_is_diners = True
        self._home_refresh_stop = threading.Event()
        self._idle_watch_stop = threading.Event()
        self._order_poll_stop = threading.Event()
        self._order_poll_stop.set()
        self.search = ft.TextField(
            hint_text=_SEARCH_HINT,
            hint_style=theme.role_style(
                theme.TextRole.META, color=theme.COLORS["text_secondary"]
            ),
            dense=True,
            autofocus=True,
            on_change=self._on_search,
            on_submit=self._on_search_submit,
            text_size=theme.field_text_size(),
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_color=theme.COLORS["accent"],
            focused_border_color=theme.COLORS["accent"],
            border_width=2,
        )
        self.list_view = ft.ListView(
            expand=True,
            spacing=2,
            padding=0,
            on_scroll=lambda _e: self.note_activity(),
        )
        self.detail = ft.Column(
            expand=True,
            spacing=theme.SPACING["sm"],
            scroll=ft.ScrollMode.AUTO,
            # Stretch children to panel width so month-grid day columns share
            # space equally (expand=1). Without this, Rows size to text ("S"
            # wider than "*") and the grid looks stretched between days.
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            on_scroll=lambda _e: self.note_activity(),
        )
        self.page.on_keyboard_event = self._on_page_key
        self.root = self._build()
        self._show_home()
        self._start_chip_listen()
        self._start_home_refresh()
        self._start_idle_watch()

    def control(self) -> ft.Control:
        # Tap/drag na workspace resetuje idle timer (klávesnice už přes on_keyboard).
        return ft.GestureDetector(
            content=self.root,
            on_tap_down=lambda _e: self.note_activity(),
            on_pan_start=lambda _e: self.note_activity(),
            expand=True,
        )

    def dispose(self) -> None:
        self._home_refresh_stop.set()
        self._idle_watch_stop.set()
        self._stop_order_marker_poll()

    def go_home(self, *, clear_search: bool = True) -> None:
        """Privacy reset → HOME."""

        self._stop_order_marker_poll()
        self._day = None
        self._order_version = None
        self._order_fingerprint = None
        self.state.selected_evidcislo = None
        self._idle.set_diner_open(False)
        self._idle.modal_open = False
        self._idle.dirty_form = False
        self._idle.write_in_flight = False
        self._home_visible = True
        if clear_search:
            self.search.value = ""
            self.state.search_query = ""
            self._refresh_list(self.vm.list_initial())
        self._show_home()
        self.page.update()
        self.focus_search()

    def note_activity(self) -> None:
        self._idle.note_activity()

    def set_idle_suppressed(
        self,
        *,
        modal: bool | None = None,
        dirty: bool | None = None,
        write: bool | None = None,
    ) -> None:
        if modal is not None:
            self._idle.modal_open = modal
        if dirty is not None:
            self._idle.dirty_form = dirty
        if write is not None:
            self._idle.write_in_flight = write
        self.note_activity()

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

    def _any_dialog_open(self) -> bool:
        for item in self.page.overlay:
            if getattr(item, "open", False):
                return True
        return False

    def _show_home(self) -> None:
        self._home_visible = True
        self._home_error = None
        try:
            self._home = self.vm.load_home_overview()
        except Exception as exc:
            self._home = None
            self._home_error = str(exc)
        self.detail.controls = [
            build_home_overview(
                self._home,
                error=self._home_error,
                on_retry=lambda _e: self._show_home() or self.page.update(),
            )
        ]

    def _start_home_refresh(self) -> None:
        stop = self._home_refresh_stop

        def _loop() -> None:
            while not stop.wait(_HOME_REFRESH_SECONDS):
                if not self._home_visible or self._day is not None:
                    continue
                try:
                    overview = self.vm.load_home_overview()

                    def _apply(o=overview) -> None:
                        if self._day is not None or not self._home_visible:
                            return
                        self._home = o
                        self._home_error = None
                        self.detail.controls = [
                            build_home_overview(
                                self._home,
                                error=None,
                                on_retry=lambda _e: self._show_home()
                                or self.page.update(),
                            )
                        ]
                        self.page.update()

                    self.page.run_thread(_apply)
                except Exception:
                    continue

        threading.Thread(target=_loop, name="jll-home-refresh", daemon=True).start()

    def _start_idle_watch(self) -> None:
        stop = self._idle_watch_stop

        def _loop() -> None:
            while not stop.wait(2.0):
                self._idle.modal_open = self._any_dialog_open()
                if self._idle.should_return_home():

                    def _go() -> None:
                        if self._idle.should_return_home():
                            self.go_home(clear_search=True)

                    self.page.run_thread(_go)

        threading.Thread(target=_loop, name="jll-diner-idle", daemon=True).start()

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
                cfg = self.state.config
                if cfg is not None:
                    try:
                        code = cfg.transform_chip_from_reader(code)
                    except ValueError as exc:
                        self.page.run_thread(
                            lambda m=str(exc): message_dialog(
                                self.page, title="Čip", body=m
                            )
                        )
                        continue
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
        create = self.state.diner_create_state()
        list_body = ft.Column(
            [
                self.search,
                ft.Container(height=theme.SPACING["md"]),
                self.list_view,
            ],
            expand=True,
            spacing=0,
            tight=False,
        )
        list_panel = self._panel(list_body, expand=True)
        list_panel.width = theme.LIST_WIDTH

        left_blocks: list[ft.Control] = []
        if create.allowed:
            create_panel = self._panel(
                ft.Container(
                    content=ft.OutlinedButton(
                        "přidat strávníka",
                        style=theme.button_style(
                            padding=ft.padding.symmetric(horizontal=14, vertical=6)
                        ),
                        on_click=lambda _e: self._open_create_dialog(),
                    ),
                    alignment=ft.alignment.center,
                ),
            )
            create_panel.width = theme.LIST_WIDTH
            left_blocks.append(create_panel)
        left_blocks.append(list_panel)

        left = ft.Container(
            content=ft.Column(
                left_blocks,
                spacing=theme.SPACING["sm"],
                expand=True,
                tight=False,
            ),
            width=theme.LIST_WIDTH,
        )

        detail_host = ft.Container(
            content=self.detail,
            expand=True,
            bgcolor=theme.COLORS["background"],
            padding=ft.padding.only(left=theme.SPACING["sm"]),
            # No alignment: Align would pass loose width and day columns
            # would size to cell text again.
        )
        if not self.vm.can_view():
            return empty_state(
                "Strávníci",
                "Nemáte oprávnění zobrazit strávníky.",
            )
        self.detail.controls = []
        root = ft.Row(
            [left, detail_host],
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
            self._focus_index = _SEARCH_FOCUS
            self.list_view.controls.append(
                theme.text(
                    "Žádní strávníci v povolených kategoriích.",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
            self._apply_list_focus_chrome()
            return

        if prefer_evid is not None:
            for idx, item in enumerate(self._results):
                if item.evidcislo == prefer_evid:
                    self._focus_index = idx
                    break
            else:
                self._focus_index = _SEARCH_FOCUS
        else:
            # Prázdné hledání → fokus ve vyhledávání; po filtru → 1. shoda.
            query = (self.search.value or "").strip()
            self._focus_index = _SEARCH_FOCUS if not query else 0

        self._render_list_rows()
        self._apply_list_focus_chrome()

    def _apply_list_focus_chrome(self) -> None:
        """Modrý rámeček: vyhledávání (−1) nebo vybraný řádek seznamu."""

        in_search = self._focus_index < 0
        accent = theme.COLORS["accent"]
        muted = theme.COLORS["block_border"]
        self.search.border_color = accent if in_search else muted
        self.search.focused_border_color = accent if in_search else muted
        self.search.border_width = 2 if in_search else 1

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
                    content=theme.text(
                        f"{item.name}{class_bit}",
                        theme.TextRole.BODY,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
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
        if not self._results and delta != 0:
            self._focus_index = _SEARCH_FOCUS
            self._apply_list_focus_chrome()
            self.page.update()
            self.focus_search()
            return
        self._focus_index = next_list_focus(
            self._focus_index, delta, len(self._results)
        )
        self._render_list_rows()
        self._apply_list_focus_chrome()
        self.page.update()
        self.focus_search()

    def _confirm_focused(self) -> None:
        if not self._results:
            return
        if self._focus_index < 0:
            # Enter ve vyhledávání s filtrem → otevři první shodu.
            if not (self.search.value or "").strip():
                return
            self._focus_index = 0
        idx = max(0, min(self._focus_index, len(self._results) - 1))
        self._open(self._results[idx].evidcislo)

    def _on_search(self, e: ft.ControlEvent) -> None:
        self.note_activity()
        results = self.vm.search(e.control.value or "")
        self._refresh_list(results)
        self.page.update()

    def _on_search_submit(self, _e: ft.ControlEvent) -> None:
        self.note_activity()
        self._confirm_focused()

    def _on_page_key(self, e: ft.KeyboardEvent) -> None:
        key = (e.key or "").casefold().replace(" ", "")
        self.note_activity()
        if key in {"escape", "esc"}:
            self._handle_escape()
            return
        if key in {"arrowdown", "down"}:
            self._move_focus(1)
        elif key in {"arrowup", "up"}:
            self._move_focus(-1)

    def _handle_escape(self) -> None:
        # 1) otevřený dialog → zavři poslední
        for item in reversed(list(self.page.overlay)):
            if getattr(item, "open", False):
                item.open = False
                self._idle.modal_open = False
                self._idle.dirty_form = False
                self.page.update()
                return
        # 2) diner detail → HOME
        if self._day is not None:
            self.go_home(clear_search=True)
            return
        # 3) search / highlight → clear → HOME
        if (self.search.value or "").strip() or self.state.selected_evidcislo is not None:
            self.go_home(clear_search=True)
            return
        # 4) už HOME → no-op

    def apply_snapshot(self, snapshot: DinerDaySnapshot) -> None:
        """Nastaví den a version token ze stejného DB snapshotu."""

        self._day = snapshot.day
        self._order_version = snapshot.order_version
        self._order_fingerprint = snapshot.order_version.fingerprint()

    def _open(self, evidcislo: int) -> None:
        self.note_activity()
        try:
            snapshot = self.vm.select_diner(evidcislo)
            self.apply_snapshot(snapshot)
        except Exception as exc:
            message_dialog(self.page, title="Strávník", body=str(exc))
            return
        self.state.selected_evidcislo = evidcislo
        self._home_visible = False
        self._idle.set_diner_open(True)
        self._render_detail()
        self._arm_order_marker_poll()
        query = self.search.value or ""
        self._refresh_list(self.vm.search(query), prefer_evid=evidcislo)
        self.page.update()
        self.focus_search()

    def _render_detail(self) -> None:
        day = self._day
        if day is not None and self._order_version is None:
            try:
                self._reload_day_snapshot()
                day = self._day
            except Exception:
                LOGGER.exception("order snapshot capture failed")
        assert day is not None
        diner = day.diner
        edit = self.state.diner_edit_state()
        chip_view = self.state.chip_view_state()

        credit_value = diner.available_credit
        credit_text = self.vm.format_credit(credit_value)
        if credit_value < 0:
            credit_color = theme.COLORS["danger"]
        elif credit_value > 0:
            credit_color = theme.COLORS["credit_positive"]
        else:
            credit_color = theme.COLORS["text_primary"]
        chip_code = self._display_chip_code(diner)
        chip_bit = f"Čip {chip_code}" if chip_code else "Bez čipu"
        btn_h = int(theme.scaled(34))
        _btn_pad = theme.button_style(
            padding=ft.padding.symmetric(horizontal=12, vertical=6)
        )
        payments_view = self.state.payments_view_state()
        diner_actions: list[ft.Control] = [
            ft.OutlinedButton(
                "Upravit",
                disabled=not edit.allowed,
                tooltip=disabled_hint(edit) or None,
                style=_btn_pad,
                height=btn_h,
                on_click=lambda _e: self._open_edit_dialog(),
            ),
            ft.OutlinedButton(
                "Detail čipu",
                disabled=not chip_view.allowed,
                tooltip=disabled_hint(chip_view) or "Náhled čipu",
                style=_btn_pad,
                height=btn_h,
                on_click=lambda _e: self._open_chip_detail(),
            ),
        ]
        if payments_view.allowed:
            diner_actions.append(
                ft.OutlinedButton(
                    "Platby",
                    style=_btn_pad,
                    height=btn_h,
                    on_click=lambda _e: self._open_payments_list(diner.evidcislo),
                )
            )
        diner_actions.append(
            ft.FilledButton(
                "Ruční odběr",
                style=_btn_pad,
                height=btn_h,
                on_click=lambda _e: self._manual_pickup(),
            )
        )
        # Řádek 1: jméno + kredit vlevo, meta (třída/ev/čip) vpravo.
        # Bez expand na potomcích – STRETCH + SPACE_BETWEEN stačí a ve
        # scroll Column expand=True rozbíjí výšku (šedý „prázdný“ blok).
        identity_row = ft.Row(
            [
                ft.Row(
                    [
                        theme.text(
                            diner.name,
                            theme.TextRole.PRIMARY,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            max_lines=1,
                        ),
                        ft.Text(
                            spans=[
                                ft.TextSpan(
                                    "Kredit ",
                                    theme.role_style(
                                        theme.TextRole.META,
                                        color=theme.COLORS["text_secondary"],
                                    ),
                                ),
                                ft.TextSpan(
                                    credit_text,
                                    theme.role_style(
                                        theme.TextRole.PRIMARY, color=credit_color
                                    ),
                                ),
                            ],
                            overflow=ft.TextOverflow.ELLIPSIS,
                            max_lines=1,
                        ),
                    ],
                    spacing=theme.SPACING["md"],
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                theme.text(
                    f"{diner.class_name or diner.category} · ev. {diner.evidcislo} · {chip_bit}",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                    text_align=ft.TextAlign.RIGHT,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # Řádek 2: měsíce vlevo, všechna akční tlačítka stejné výšky vpravo.
        actions_row = ft.Row(
            [
                ft.Row(
                    [
                        self._month_switcher(day),
                        theme.text(
                            f"Přihlášky · {self.vm.format_month_year(day.target_date)}",
                            theme.TextRole.ACTION,
                        ),
                    ],
                    spacing=theme.SPACING["md"],
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    diner_actions,
                    spacing=theme.SPACING["xs"],
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.detail.controls = [
            identity_row,
            actions_row,
            self._month_grid(day),
            self._menu_panel(day),
        ]
        self.page.update()

    def _open_payments_list(self, evidcislo: int) -> None:
        self.note_activity()
        view = self.state.payments_view_state()
        if not view.allowed:
            message_dialog(
                self.page, title="Platby", body=disabled_hint(view) or ""
            )
            return
        post = self.state.payments_post_state()
        dialog_holder: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def _close(_e=None) -> None:
            dialog = dialog_holder["dialog"]
            if dialog is None:
                return
            dialog.open = False
            self.page.update()

        def _open_detail(penden_id: int) -> None:
            _close()
            self._payment_detail(penden_id)

        def _open_post(_e=None) -> None:
            if not post.allowed:
                return
            _close()
            self._open_post_payment()

        rows: list[ft.Control] = []
        history = self.state.payment_history_service
        if history is None:
            rows.append(
                theme.text(
                    "Služba historie plateb není dostupná.",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                )
            )
        else:
            try:
                page = history.list_for_diner(evidcislo, limit=20, offset=0)
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
                            style=theme.button_style(
                                padding=ft.padding.symmetric(horizontal=0, vertical=2)
                            ),
                            on_click=lambda _e, pid=item.id: _open_detail(pid),
                        )
                    )
                if not rows:
                    rows.append(
                        theme.text(
                            "Žádné platby",
                            theme.TextRole.BODY,
                            color=theme.COLORS["text_secondary"],
                        )
                    )
            except Exception as exc:
                rows.append(
                    theme.text(
                        str(exc),
                        theme.TextRole.BODY,
                        color=theme.COLORS["danger"],
                    )
                )

        actions: list[ft.Control] = []
        if post.allowed:
            actions.append(
                ft.FilledButton(
                    "Zaúčtovat platbu",
                    style=theme.button_style(),
                    on_click=_open_post,
                )
            )
        actions.append(
            ft.TextButton("Zavřít", style=theme.button_style(), on_click=_close)
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Platby", theme.TextRole.PRIMARY),
            content=ft.Column(
                rows,
                tight=True,
                spacing=theme.SPACING["xs"],
                width=440,
                height=320,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=actions,
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialog_holder["dialog"] = dialog
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

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
        amount_field = ft.TextField(
            label="Částka",
            autofocus=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        note_field = ft.TextField(
            label="Poznámka",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        method_dd = ft.Dropdown(
            label="Způsob platby",
            options=[ft.dropdown.Option(key=m.code, text=m.label) for m in methods],
            value=next((m.code for m in methods if m.code == "4"), methods[0].code),
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        account_dd = ft.Dropdown(
            label="Účet",
            options=[ft.dropdown.Option(key=a.code, text=a.label) for a in accounts],
            value=next((a.code for a in accounts if a.code == "STRAV"), accounts[0].code),
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        service_field = ft.TextField(
            label="Typ služby",
            value="Oběd-A",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        period_dd = ft.Dropdown(
            label="Účtovaný měsíc",
            options=[
                ft.dropdown.Option(key="this", text="Tento měsíc"),
                ft.dropdown.Option(key="next", text="Budoucí měsíc"),
            ],
            value="this",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
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
            title=theme.text("Zaúčtovat platbu", theme.TextRole.PRIMARY),
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
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton(
                    "Zaúčtovat", style=theme.button_style(), on_click=_save
                ),
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
        chip_h = int(theme.scaled(34))

        def _btn(option, *, viewing: bool, future_month: bool) -> ft.Control:
            # Zvýrazni měsíc, na který lze přepnout; aktuálně zobrazený je tlumený.
            bg = "#6F8FA8" if viewing else theme.COLORS["accent"]
            return ft.Container(
                content=theme.text(
                    option.label,
                    theme.TextRole.ACTION,
                    color="#FFFFFF",
                ),
                bgcolor=bg,
                height=chip_h,
                padding=ft.padding.symmetric(horizontal=14, vertical=0),
                alignment=ft.alignment.center,
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
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _switch_month(self, future: bool) -> None:
        self.note_activity()
        try:
            refreshed = self.vm.switch_month(future=future)
        except Exception as exc:
            message_dialog(self.page, title="Měsíc", body=str(exc))
            return
        if refreshed is None:
            return
        self.apply_snapshot(refreshed)
        self._render_detail()
        self._arm_order_marker_poll()
        self.focus_search()

    def _month_grid(self, day: DinerDay) -> ft.Control:
        rows = self.vm.month_rows(day)
        if not rows:
            return theme.text("Žádná data přihlášek.", theme.TextRole.META)
        label_w = int(theme.scaled(76))
        cell_h = theme.scaled(28)
        # Same border width on every day cell so selection/today never
        # changes column geometry (1 vs 2 px used to nudge widths).
        border_w = 2
        transparent = "#00000000"
        actual_today = day.server_now.date()
        selected_day = day.target_date.day
        viewing_actual_today = day.target_date == actual_today

        def _day_mark(value: str, *, color: str | None = None) -> ft.Control:
            return theme.text(
                value,
                theme.TextRole.META,
                color=color,
                text_align=ft.TextAlign.CENTER,
                max_lines=1,
                overflow=ft.TextOverflow.CLIP,
                no_wrap=True,
            )

        def _day_col(
            *,
            content: ft.Control,
            bgcolor: str | None,
            border_color: str,
            height: float | int | None = None,
            on_click=None,
            radius: int = 3,
        ) -> ft.Container:
            return ft.Container(
                expand=1,
                height=height,
                alignment=ft.alignment.center,
                bgcolor=bgcolor,
                border_radius=radius,
                border=ft.border.all(border_w, border_color),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=content,
                on_click=on_click,
            )

        header_cells: list[ft.Control] = [ft.Container(width=label_w)]
        for cell in rows[0].cells:
            is_today_col = viewing_actual_today and cell.day == actual_today.day
            is_selected_col = cell.day == selected_day and not is_today_col
            if is_today_col:
                header_bg, header_color = theme.COLORS["accent"], "#FFFFFF"
                header_border = theme.COLORS["today_column_border"]
            elif is_selected_col:
                header_bg, header_color = (
                    theme.COLORS["accent_soft"],
                    theme.COLORS["text_primary"],
                )
                header_border = theme.COLORS["accent"]
            else:
                header_bg, header_color = None, theme.COLORS["text_secondary"]
                header_border = transparent
            header_cells.append(
                _day_col(
                    content=_day_mark(str(cell.day), color=header_color),
                    bgcolor=header_bg,
                    border_color=header_border,
                    radius=4,
                )
            )
        grid_rows = [ft.Row(header_cells, spacing=1)]
        for row in rows:
            cells: list[ft.Control] = [
                ft.Container(
                    width=label_w,
                    content=theme.text(
                        row.meal_type,
                        theme.TextRole.META,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                )
            ]
            for cell in row.cells:
                is_today_col = viewing_actual_today and cell.day == actual_today.day
                is_selected_col = cell.day == selected_day
                bg = None
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
                elif cell.is_ordered:
                    bg = (
                        theme.COLORS["ordered_selected"]
                        if cell.is_selected
                        else theme.COLORS["ordered"]
                    )
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
                if is_today_col:
                    border_color = theme.COLORS["today_column_border"]
                elif is_selected_col:
                    border_color = theme.COLORS["accent"]
                else:
                    border_color = transparent
                cells.append(
                    _day_col(
                        content=_day_mark(label),
                        bgcolor=bg,
                        border_color=border_color,
                        height=cell_h,
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
        self.note_activity()
        if self._day is None:
            return
        current = self._day.target_date
        target = date(current.year, current.month, day_num)
        try:
            snapshot = self.vm.set_day(target)
            if snapshot is None:
                return
            self.apply_snapshot(snapshot)
        except Exception as exc:
            message_dialog(self.page, title="Den", body=str(exc))
            return
        self._render_detail()
        self._arm_order_marker_poll()
        self.focus_search()

    def _reload_day_snapshot(self) -> None:
        if self._day is None:
            return
        snapshot = self.vm.set_day(self._day.target_date)
        if snapshot is not None:
            self.apply_snapshot(snapshot)

    def _stop_order_marker_poll(self) -> None:
        self._order_poll_stop.set()
        self._order_poll_generation += 1

    def _arm_order_marker_poll(self) -> None:
        self._stop_order_marker_poll()
        if self._day is None:
            return
        self._order_poll_stop = threading.Event()
        stop = self._order_poll_stop
        generation = self._order_poll_generation

        def _loop() -> None:
            while not stop.wait(_ORDER_MARKER_POLL_SECONDS):
                if generation != self._order_poll_generation:
                    return
                if self._order_poll_paused or self._day is None:
                    continue
                try:
                    snapshot = self.vm.set_day(self._day.target_date)
                except Exception:
                    LOGGER.exception("order marker poll failed")
                    continue
                if snapshot is None:
                    continue
                fingerprint = snapshot.order_version.fingerprint()
                if (
                    self._order_fingerprint is not None
                    and fingerprint != self._order_fingerprint
                ):
                    evid = self._day.diner.evidcislo

                    def _apply(e=evid, snap=snapshot) -> None:
                        if self._day is None or self._day.diner.evidcislo != e:
                            return
                        try:
                            self.apply_snapshot(snap)
                            self._render_detail()
                            self.page.update()
                            message_dialog(
                                self.page,
                                title="Objednávka",
                                body=ERROR_TEXTS[ErrorCode.ORDER_STALE_STATE],
                            )
                        except Exception as exc:
                            LOGGER.exception("order marker refresh failed")
                            message_dialog(
                                self.page, title="Objednávka", body=str(exc)
                            )

                    self.page.run_thread(_apply)
                else:
                    self.apply_snapshot(snapshot)

        threading.Thread(target=_loop, name="jll-order-marker-poll", daemon=True).start()

    def _schedule_settle_probe(self, outcome) -> None:
        result = outcome.result
        if result is None or getattr(result, "committed_version", None) is None:
            return
        if getattr(result, "post_commit_expectations", None) is None:
            return
        day = self._day
        if day is None:
            return
        evid = day.diner.evidcislo
        generation = self._mutation_generation

        def _run() -> None:
            time.sleep(_SETTLE_DELAY_SECONDS)
            if generation != self._mutation_generation or self._day is None:
                return
            if self._day.diner.evidcislo != evid:
                return
            try:
                probe = self.vm.orders.order_service.settle_verify_result(result)
            except Exception:
                LOGGER.exception("settle verify failed")
                return

            def _apply() -> None:
                if generation != self._mutation_generation or self._day is None:
                    return
                if probe.status is ProbeStatus.CONFLICT:
                    message_dialog(
                        self.page,
                        title="Konflikt souběžné změny",
                        body=probe.message
                        or ERROR_TEXTS[ErrorCode.ORDER_EXTERNAL_CHANGE],
                    )
                    try:
                        self._reload_day_snapshot()
                        self._render_detail()
                        self.page.update()
                    except Exception as exc:
                        message_dialog(self.page, title="Objednávka", body=str(exc))
                elif probe.status is ProbeStatus.EXTERNAL_OK and probe.message:
                    try:
                        self._reload_day_snapshot()
                        self._render_detail()
                        self.page.update()
                    except Exception:
                        pass
                elif probe.status is ProbeStatus.CONSISTENCY:
                    message_dialog(
                        self.page,
                        title="Nekonzistence",
                        body=probe.message
                        or ERROR_TEXTS[ErrorCode.POSTCONDITION_FAILED],
                    )
                    try:
                        self._reload_day_snapshot()
                        self._render_detail()
                        self.page.update()
                    except Exception:
                        pass

            self.page.run_thread(_apply)

        threading.Thread(target=_run, name="jll-order-settle", daemon=True).start()

    def _handle_mutation_outcome(self, outcome, *, title: str) -> None:
        if outcome.error is not None:
            message_dialog(self.page, title=title, body=outcome.error.user_message)
        if outcome.notice:
            message_dialog(self.page, title="Upozornění", body=outcome.notice)
        if outcome.refreshed is not None:
            self._day = outcome.refreshed
            try:
                self._reload_day_snapshot()
            except Exception:
                LOGGER.exception("post-mutation snapshot reload failed")
            self._render_detail()
        if outcome.succeeded:
            self._schedule_settle_probe(outcome)
        self.note_activity()
        self.focus_search()

    def _order(self, meal_type: str, menu: int) -> None:
        if self._day is None or not self.vm.can_change_orders():
            message_dialog(self.page, title="Objednávka", body="Nemáte oprávnění měnit objednávky.")
            return
        if self._order_version is None:
            try:
                self._reload_day_snapshot()
            except Exception as exc:
                message_dialog(self.page, title="Objednávka", body=str(exc))
                return
        if self._order_version is None:
            message_dialog(
                self.page,
                title="Objednávka",
                body="Stav objednávky nelze bezpečně načíst.",
            )
            return
        try:
            expected_action, expected_ordered = self.vm.rendered_order_intent(
                self._day, meal_type, menu
            )
        except OrderBusinessError as exc:
            message_dialog(
                self.page,
                title="Objednávka",
                body=ERROR_TEXTS.get(exc.code, str(exc)),
            )
            return
        self._mutation_generation += 1
        self._order_poll_paused = True
        self.set_idle_suppressed(write=True)
        try:
            outcome = self.vm.apply_menu(
                self._day.diner.evidcislo,
                self._day.target_date,
                meal_type,
                menu,
                expected_action=expected_action,
                expected_version=self._order_version,
                expected_ordered_menu=expected_ordered,
            )
        finally:
            self._order_poll_paused = False
            self.set_idle_suppressed(write=False)
        self._handle_mutation_outcome(outcome, title="Objednávka")

    def _unsubscribe(self, meal_type: str, menu: int) -> None:
        if self._day is None:
            return
        if self._order_version is None:
            try:
                self._reload_day_snapshot()
            except Exception as exc:
                message_dialog(self.page, title="Odhlášení", body=str(exc))
                return
        if self._order_version is None:
            message_dialog(
                self.page,
                title="Odhlášení",
                body="Stav objednávky nelze bezpečně načíst.",
            )
            return
        try:
            expected_action, expected_ordered = self.vm.rendered_order_intent(
                self._day, meal_type, menu
            )
        except OrderBusinessError as exc:
            message_dialog(
                self.page,
                title="Odhlášení",
                body=ERROR_TEXTS.get(exc.code, str(exc)),
            )
            return
        if expected_action is not OrderAction.MENU_DELETE:
            message_dialog(
                self.page,
                title="Odhlášení",
                body=ERROR_TEXTS[ErrorCode.ORDER_STALE_STATE],
            )
            try:
                self._reload_day_snapshot()
                self._render_detail()
            except Exception:
                pass
            return
        self._mutation_generation += 1
        self._order_poll_paused = True
        self.set_idle_suppressed(write=True)
        try:
            outcome = self.vm.unsubscribe(
                self._day.diner.evidcislo,
                self._day.target_date,
                meal_type,
                menu,
                expected_version=self._order_version,
                expected_ordered_menu=expected_ordered,
            )
        finally:
            self._order_poll_paused = False
            self.set_idle_suppressed(write=False)
        self._handle_mutation_outcome(outcome, title="Odhlášení")

    def _menu_panel(self, day: DinerDay) -> ft.Control:
        title = theme.text(
            f"Jídelníček · {self.vm.format_day_month(day.target_date)}",
            theme.TextRole.ACTION,
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

        # Stabilní výška – žlutá = odběr (bez textu), Odhlásit uvnitř zeleného řádku.
        row_h = int(theme.scaled(34))
        can_unsub = (
            ordered is not None
            and self.vm.can_change_orders()
            and not picked
        )

        option_controls: list[ft.Control] = []
        if not meal.options:
            option_controls.append(
                ft.Container(
                    content=theme.text(
                        "Jídelníček není zveřejněn",
                        theme.TextRole.META,
                        color=unpublished_color,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    bgcolor=theme.COLORS["surface"],
                    border=ft.border.all(1, theme.COLORS["block_border"]),
                    padding=ft.padding.symmetric(horizontal=8, vertical=0),
                    border_radius=4,
                    height=row_h,
                    alignment=ft.alignment.center_left,
                    expand=True,
                )
            )
        for option in meal.options:
            is_ordered = ordered == option.menu
            price = self.vm.format_money(option.price)
            unpublished = not getattr(option, "published", True)
            dish = option.dish_name or (
                "Jídelníček není zveřejněn" if unpublished else "Menu"
            )
            label = f"{option.menu} · cena {price} · {dish}"
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

            row_children: list[ft.Control] = [
                ft.Container(
                    content=theme.text(
                        label,
                        theme.TextRole.BODY,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        color=text_color,
                    ),
                    expand=True,
                    alignment=ft.alignment.center_left,
                )
            ]
            if is_ordered and can_unsub:
                row_children.append(
                    ft.TextButton(
                        "Odhlásit",
                        style=theme.button_style(
                            padding=ft.padding.symmetric(horizontal=8, vertical=0)
                        ),
                        on_click=lambda _e, m=meal.meal_type, menu=ordered: self._unsubscribe(
                            m, menu
                        ),
                    )
                )

            option_controls.append(
                ft.Container(
                    content=ft.Row(
                        row_children,
                        spacing=theme.SPACING["xs"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    bgcolor=row_bg,
                    border=ft.border.all(1, theme.COLORS["block_border"]),
                    padding=ft.padding.symmetric(horizontal=8, vertical=0),
                    border_radius=4,
                    height=row_h,
                    alignment=ft.alignment.center_left,
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

        return ft.Row(
            [
                ft.Container(
                    width=72,
                    height=row_h,
                    alignment=ft.alignment.center_left,
                    content=theme.text(
                        meal.meal_type,
                        theme.TextRole.META,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ),
                *option_controls,
            ],
            spacing=theme.SPACING["xs"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )

    def _manual_pickup(self) -> None:
        self.note_activity()
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
            title=theme.text("Ruční odběr stravy", theme.TextRole.PRIMARY),
            content=ft.Container(content=list_view, width=420),
            actions=[
                ft.TextButton(
                    "Zavřít",
                    style=theme.button_style(),
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
                        theme.text(label, theme.TextRole.BODY, expand=True),
                        ft.FilledButton(
                            "Vydat",
                            style=theme.button_style(),
                            on_click=_serve(prihlaska_id, label),
                        ),
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
        name_field = ft.TextField(
            label="Příjmení a jméno",
            autofocus=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        class_field = ft.TextField(
            label="Třída",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        cat_field = ft.Dropdown(
            label="Kategorie",
            options=[ft.dropdown.Option(c) for c in cats],
            value=cats[0] if cats else None,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
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
            title=theme.text("Nový strávník", theme.TextRole.PRIMARY),
            content=ft.Column(
                [name_field, cat_field, class_field],
                tight=True,
                spacing=8,
                width=360,
            ),
            actions=[
                ft.TextButton(
                    "Zrušit",
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Uložit", style=theme.button_style(), on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _open_edit_dialog(self) -> None:
        self.note_activity()
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
        name_field = ft.TextField(
            label="Jméno",
            value=diner.name,
            autofocus=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        class_field = ft.TextField(
            label="Třída",
            value=diner.class_name or "",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        note_field = ft.TextField(
            label="Poznámka",
            value=diner.poznamka or "",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        email_field = ft.TextField(
            label="E-mail",
            value=diner.email or "",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        street_field = ft.TextField(
            label="Ulice",
            value=diner.ulice or "",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        city_field = ft.TextField(
            label="Město",
            value=diner.mesto or "",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )

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
            title=theme.text("Upravit strávníka", theme.TextRole.PRIMARY),
            content=ft.Column(
                [
                    name_field,
                    class_field,
                    street_field,
                    city_field,
                    email_field,
                    note_field,
                    theme.text(
                        "Kategorie a finance se zde nemění.",
                        theme.TextRole.META,
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
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Uložit", style=theme.button_style(), on_click=_save),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _display_chip_code(self, diner) -> str | None:
        """Číslo čipu pro hlavičku: preferuj aktivní `cipy`, pak legacy `stravnik.cip`."""

        for chip in diner.chips:
            if chip.status_code == "P":
                return chip.code
        if diner.chip_number:
            return diner.chip_number
        if diner.chips:
            return diner.chips[0].code
        return None

    def _primary_chip_status(self) -> str | None:
        if self._day is None:
            return None
        diner = self._day.diner
        code = self._display_chip_code(diner)
        if diner.chips and code:
            for chip in diner.chips:
                if chip.code == code:
                    return chip.status_code
            return diner.chips[0].status_code
        if code:
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
        self.note_activity()
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
            chip_code = self._display_chip_code(diner) or diner.chips[0].code
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
                        theme.text(
                            f"{when} · {item.code} · {item.status_label}",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        )
                    )
            except Exception:
                history_controls = []
        if not history_controls:
            history_controls.append(
                theme.text(
                    "Žádná historie.",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )

        def _field(label: str, value: str) -> ft.Control:
            return ft.Column(
                [
                    theme.text(
                        label,
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    theme.text(
                        value,
                        theme.TextRole.BODY,
                        selectable=True,
                    ),
                ],
                spacing=0,
                tight=True,
            )

        actions: list[ft.Control] = []
        if "assign" in wanted:
            actions.append(
                ft.FilledButton(
                    "Přidělit čip",
                    style=theme.button_style(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)
                    ),
                    disabled=not assign.allowed,
                    tooltip=disabled_hint(assign) or None,
                    on_click=lambda _e: self._chip_assign(),
                )
            )
        if "return" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Vrátit",
                    style=theme.button_style(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)
                    ),
                    disabled=not ret.allowed,
                    tooltip=disabled_hint(ret) or None,
                    on_click=lambda _e: self._chip_return(),
                )
            )
        if "block" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Blokovat",
                    style=theme.button_style(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)
                    ),
                    disabled=not block.allowed,
                    tooltip=disabled_hint(block) or None,
                    on_click=lambda _e: self._chip_block(),
                )
            )
        if "lost" in wanted:
            actions.append(
                ft.OutlinedButton(
                    "Označit jako ztracený",
                    style=theme.button_style(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)
                    ),
                    disabled=not lost.allowed,
                    tooltip=disabled_hint(lost) or None,
                    on_click=lambda _e: self._chip_lost(),
                )
            )
        if "unblock" in wanted:
            actions.append(
                ft.FilledButton(
                    "Odblokovat",
                    style=theme.button_style(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4)
                    ),
                    disabled=not unblock.allowed,
                    tooltip=disabled_hint(unblock) or None,
                    on_click=lambda _e: self._chip_unblock(),
                )
            )

        history_block: ft.Control
        if len(history_controls) <= 1:
            history_block = ft.Column(
                [
                    theme.text(
                        "Historie",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    *history_controls,
                ],
                spacing=0,
                tight=True,
            )
        else:
            history_block = ft.Column(
                [
                    theme.text(
                        "Historie",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    ft.Container(
                        content=ft.Column(
                            history_controls,
                            spacing=1,
                            tight=True,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=min(120, 18 * len(history_controls) + 8),
                    ),
                ],
                spacing=0,
                tight=True,
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Detail čipu", theme.TextRole.PRIMARY),
            content=ft.Container(
                content=ft.Column(
                    [
                        _field("Čip", chip_code),
                        _field("Stav", status_label),
                        _field("Držitel", f"{diner.name} · ev. {diner.evidcislo}"),
                        history_block,
                        ft.Row(
                            actions,
                            spacing=theme.SPACING["xs"],
                            wrap=True,
                            tight=True,
                        ),
                    ],
                    spacing=theme.SPACING["xs"],
                    tight=True,
                ),
                width=480,
            ),
            actions=[
                ft.TextButton(
                    "Zavřít",
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _chip_code_for_action(self) -> str | None:
        if self._day is None:
            return None
        return self._display_chip_code(self._day.diner)

    def _chip_assign(self) -> None:
        if self._day is None:
            return
        state = self.state.chip_assign_state()
        if not state.allowed:
            message_dialog(self.page, title="Přidělit čip", body=disabled_hint(state) or "")
            return
        code_field = ft.TextField(
            label="Číslo čipu",
            autofocus=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )

        def _save(_e=None) -> None:
            service = self.state.chip_command_service
            if service is None:
                return
            from ...diner_models import ChipCommand

            actor, version = self._actor_bits()
            raw_code = code_field.value or ""
            cfg = self.state.config
            if cfg is not None and (cfg.reader_ikonverze or cfg.reader_pridat00):
                try:
                    raw_code = cfg.transform_chip_from_reader(raw_code)
                except ValueError as exc:
                    message_dialog(self.page, title="Přidělit čip", body=str(exc))
                    return
            try:
                service.assign(
                    ChipCommand(
                        chip_code=raw_code,
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
            title=theme.text("Přidělit čip", theme.TextRole.PRIMARY),
            content=code_field,
            actions=[
                ft.TextButton(
                    "Zrušit",
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton("Přidělit", style=theme.button_style(), on_click=_save),
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
