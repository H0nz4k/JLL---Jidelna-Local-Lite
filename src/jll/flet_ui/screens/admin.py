"""Administrace – sekce + SUP reauth."""

from __future__ import annotations

import flet as ft

from ...permission_catalog import PERMISSION_CATALOG
from ...policy import Permission
from .. import theme
from ..components.dialogs import message_dialog
from ..components.empty_state import empty_state
from ..state import AppState
from ..viewmodels.admin import AdminViewModel

SECTIONS = (
    "Uživatelé",
    "Oprávnění",
    "Kategorie",
    "Info",
    "Čtečka",
    "Vzhled",
)

_USERS_NAME_W = 280
_USERS_STATUS_W = 90
_USERS_PROFILE_W = 140


class AdminScreen:
    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        *,
        on_typography_save,
        on_activity=None,
        on_installation_reset=None,
        initial_section: str = "Uživatelé",
    ) -> None:
        self.page = page
        self.state = state
        self.on_typography_save = on_typography_save
        self.on_activity = on_activity or (lambda: None)
        self.on_installation_reset = on_installation_reset
        self._reset_busy = False
        self.vm = AdminViewModel(state)
        self.section = (
            initial_section if initial_section in SECTIONS else "Uživatelé"
        )
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=6, tight=False)
        self.nav = ft.Column(spacing=0, tight=True)
        self._rebuild_nav()
        self.root = ft.Column(
            [
                theme.text("Administrace", theme.TextRole.PRIMARY),
                ft.Row(
                    [
                        ft.Container(
                            content=self.nav,
                            width=140,
                            bgcolor=theme.COLORS["surface"],
                            padding=theme.SPACING["sm"],
                            border=ft.border.all(
                                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                            ),
                            border_radius=8,
                        ),
                        ft.Container(
                            content=self.body,
                            expand=True,
                            alignment=ft.alignment.top_left,
                            bgcolor=theme.COLORS["background"],
                        ),
                    ],
                    expand=True,
                    spacing=theme.SPACING["md"],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            expand=True,
            spacing=theme.SPACING["sm"],
        )
        # SUP se ověřuje modalem v app.py před vstupem; tady už jen obsah.
        self._open_section(self.section)

    def control(self) -> ft.Control:
        return self.root

    def _rebuild_nav(self) -> None:
        self.nav.controls.clear()
        for name in SECTIONS:
            active = name == self.section
            self.nav.controls.append(
                ft.Container(
                    content=theme.text(
                        name,
                        theme.TextRole.ACTION,
                        color=theme.COLORS["accent"],
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=4,
                    bgcolor=theme.COLORS["accent_soft"] if active else None,
                    border=(
                        ft.border.only(left=ft.BorderSide(3, theme.COLORS["accent"]))
                        if active
                        else None
                    ),
                    ink=True,
                    on_click=lambda _e, n=name: self._open_section(n),
                )
            )

    def _content_card(self, section_name: str, controls: list[ft.Control]) -> ft.Container:
        width = theme.ADMIN_CONTENT_WIDTH.get(section_name, 680)
        return ft.Container(
            content=ft.Column(controls, spacing=6, tight=True),
            width=width,
            bgcolor=theme.COLORS["surface"],
            border=ft.border.all(theme.CONTENT_BORDER_WIDTH, theme.COLORS["border"]),
            border_radius=8,
            padding=theme.SPACING["md"],
            alignment=ft.alignment.top_left,
        )

    def _open_section(self, name: str) -> None:
        self.on_activity()
        self.section = name
        self._rebuild_nav()
        self.body.controls.clear()
        if name == "Vzhled":
            self._render_appearance()
        elif not self.vm.business.sup_unlocked():
            self._render_sup_gate()
        elif name == "Uživatelé":
            self._render_users()
        elif name == "Oprávnění":
            self._render_permissions_help()
        elif name == "Kategorie":
            self._render_categories()
        elif name == "Info":
            self._render_info()
        elif name == "Čtečka":
            self._render_reader()
        self.page.update()

    def _render_categories(self) -> None:
        from ...setup_probe import CategoryOption

        cfg = self.state.config
        if cfg is None:
            self.body.controls.append(
                self._content_card(
                    "Kategorie",
                    [theme.text("Config není načten.", theme.TextRole.BODY)],
                )
            )
            return

        try:
            options = self.vm.list_category_options()
        except Exception as exc:
            self.body.controls.append(
                self._content_card("Kategorie", [empty_state("Kategorie", str(exc))])
            )
            return

        by_code = {item.code: item for item in options}
        selected = set(cfg.allowed_categories)
        for code in selected:
            by_code.setdefault(code, CategoryOption(code=code))

        list_col = ft.Column(spacing=2, tight=True)
        add_dd = ft.Dropdown(
            label="Další kategorie z DB",
            options=[],
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
            expand=True,
        )
        add_btn = ft.FilledButton("Přidat", style=theme.button_style())

        def _rebuild_list() -> None:
            list_col.controls.clear()
            if not selected:
                list_col.controls.append(
                    theme.text(
                        "Žádná povolená kategorie.",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    )
                )
                return
            for code in sorted(selected):
                item = by_code.get(code) or CategoryOption(code=code)
                list_col.controls.append(
                    ft.Row(
                        [
                            ft.Container(
                                content=theme.text(item.label, theme.TextRole.BODY),
                                expand=True,
                            ),
                            ft.TextButton(
                                "Odebrat",
                                style=theme.button_style(
                                    padding=ft.padding.symmetric(
                                        horizontal=8, vertical=0
                                    )
                                ),
                                on_click=lambda _e, c=code: _remove(c),
                            ),
                        ],
                        spacing=theme.SPACING["sm"],
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )

        def _refresh_add_dropdown() -> None:
            available = [item for item in options if item.code not in selected]
            add_dd.options = [
                ft.dropdown.Option(key=item.code, text=item.label) for item in available
            ]
            add_dd.value = available[0].code if available else None
            add_dd.disabled = not available
            add_btn.disabled = not available

        def _remove(code: str) -> None:
            selected.discard(code)
            _rebuild_list()
            _refresh_add_dropdown()
            self.page.update()

        def _add(_e=None) -> None:
            code = (add_dd.value or "").strip()
            if not code or code in selected:
                return
            selected.add(code)
            _rebuild_list()
            _refresh_add_dropdown()
            self.page.update()

        def _save(_e=None) -> None:
            try:
                self.vm.save_allowed_categories(frozenset(selected))
                message_dialog(
                    self.page,
                    title="Kategorie",
                    body="Povolené kategorie uloženy.",
                )
                self._open_section("Kategorie")
            except Exception as exc:
                message_dialog(self.page, title="Kategorie", body=str(exc))

        add_btn.on_click = _add
        _rebuild_list()
        _refresh_add_dropdown()

        self.body.controls.append(
            self._content_card(
                "Kategorie",
                [
                    theme.text("Povolené kategorie", theme.TextRole.ACTION),
                    theme.text(
                        "Kódy a názvy z public.kategor. Scope platí pro celou instalaci.",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    list_col,
                    ft.Row(
                        [add_dd, add_btn],
                        spacing=theme.SPACING["sm"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.FilledButton(
                        "Uložit", style=theme.button_style(), on_click=_save
                    ),
                ],
            )
        )

    def _render_reader(self) -> None:
        from ...chip_reader import (
            AutoElatecChipReader,
            UnavailableChipReader,
            available_serial_ports,
            build_chip_reader,
        )
        from ...reader_discovery import ReaderDiscoveryStatus, select_elatec_reader

        cfg = self.state.config
        if cfg is None:
            self.body.controls.append(
                self._content_card(
                    "Čtečka", [theme.text("Config není načten.", theme.TextRole.BODY)]
                )
            )
            return

        mode = cfg.reader_mode
        discovery = select_elatec_reader(preferred_serial=cfg.reader_device_serial)
        reader = self.state.chip_reader
        if isinstance(reader, AutoElatecChipReader):
            status = reader.status()
        elif reader is not None and not isinstance(reader, UnavailableChipReader):
            status = reader.status()
        else:
            status = None

        if discovery.status is ReaderDiscoveryStatus.FOUND and discovery.selected:
            state_text = "Připojena"
            device_lines = [
                f"Zařízení: {discovery.selected.description or discovery.selected.product or '—'}",
                f"Výrobce: {discovery.selected.manufacturer or '—'}",
                f"Port nyní: {discovery.selected.device}",
                f"Sériové číslo: {discovery.selected.serial_number or '—'}",
            ]
        elif discovery.status is ReaderDiscoveryStatus.AMBIGUOUS:
            state_text = "Vyžaduje výběr"
            device_lines = [discovery.message]
            for match in discovery.matches:
                device_lines.append(f"• {match.label}")
        else:
            state_text = "Nepřipojena"
            device_lines = [discovery.message]

        mode_group = ft.RadioGroup(
            value=mode,
            content=ft.Column(
                [
                    ft.Radio(
                        value="auto_elatec",
                        label="Automaticky – ELATEC",
                        label_style=theme.role_style(theme.TextRole.BODY),
                    ),
                    ft.Radio(
                        value="manual",
                        label="Ručně vybrat COM port",
                        label_style=theme.role_style(theme.TextRole.BODY),
                    ),
                ],
                tight=True,
            ),
        )
        ports = available_serial_ports()
        port_dd = ft.Dropdown(
            label="COM port",
            options=[ft.dropdown.Option(key="", text="(nenastaveno)")]
            + [ft.dropdown.Option(key=p.device, text=p.label) for p in ports],
            value=cfg.reader_port or "",
            disabled=mode != "manual",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        baud_dd = ft.Dropdown(
            label="Baud",
            options=[
                ft.dropdown.Option(key=str(b), text=str(b))
                for b in (9600, 19200, 38400, 57600, 115200)
            ],
            value=str(cfg.reader_baud_rate),
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        line_dd = ft.Dropdown(
            label="Ukončení řádku",
            options=[
                ft.dropdown.Option(key="CR", text="CR"),
                ft.dropdown.Option(key="LF", text="LF"),
                ft.dropdown.Option(key="CRLF", text="CRLF"),
            ],
            value={"\r": "CR", "\n": "LF", "\r\n": "CRLF"}.get(
                cfg.reader_line_end, "CR"
            ),
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        ikonverze_cb = ft.Checkbox(
            label="IKonverze (HEX → DEC dle JídelnaSQL)",
            value=bool(cfg.reader_ikonverze),
            label_style=theme.role_style(theme.TextRole.BODY),
        )
        pridat00_cb = ft.Checkbox(
            label="Přidat 00 na konec (Pridat00)",
            value=bool(cfg.reader_pridat00),
            label_style=theme.role_style(theme.TextRole.BODY),
        )

        def _on_mode_change(_e=None) -> None:
            port_dd.disabled = mode_group.value != "manual"
            self.page.update()

        mode_group.on_change = _on_mode_change

        def _save(_e=None) -> None:
            business = self.state.business
            if business is None:
                return
            try:
                from ...config import save_lab_config
                import dataclasses

                line_map = {"CR": "\r", "LF": "\n", "CRLF": "\r\n"}
                selected_mode = mode_group.value or "auto_elatec"
                updated = dataclasses.replace(
                    cfg,
                    reader_mode=selected_mode,
                    reader_port=(port_dd.value or None)
                    if selected_mode == "manual"
                    else None,
                    reader_device_serial=cfg.reader_device_serial,
                    reader_baud_rate=int(baud_dd.value or 19200),
                    reader_line_end=line_map.get(line_dd.value or "CR", "\r"),
                    reader_ikonverze=bool(ikonverze_cb.value),
                    reader_pridat00=bool(pridat00_cb.value),
                )
                if Permission.ADMIN_READER not in business.current_policy().permissions:
                    message_dialog(
                        self.page,
                        title="Čtečka",
                        body="Nemáte oprávnění nastavit čtečku.",
                    )
                    return
                save_lab_config(updated, self.state.config_path)
                self.state.config = updated
                if self.state.chip_reader is not None:
                    try:
                        self.state.chip_reader.stop()
                    except Exception:
                        pass
                self.state.chip_reader = build_chip_reader(
                    updated.reader_port,
                    mode=updated.reader_mode,
                    preferred_serial=updated.reader_device_serial,
                    baud_rate=updated.reader_baud_rate,
                    line_end=updated.reader_line_end,
                )
                message_dialog(
                    self.page,
                    title="Čtečka",
                    body="Nastavení uloženo.",
                )
                self._open_section("Čtečka")
            except Exception as exc:
                message_dialog(self.page, title="Čtečka", body=str(exc))

        def _test(_e=None) -> None:
            test_reader = self.state.chip_reader
            if test_reader is None or isinstance(test_reader, UnavailableChipReader):
                message_dialog(
                    self.page,
                    title="Test čtečky",
                    body="Čtečka není dostupná.",
                )
                return
            try:
                test_reader.start()
                chip = test_reader.read_once(timeout_seconds=8.0)
                raw = chip.code
                canonical = (
                    cfg.transform_chip_from_reader(raw)
                    if self.state.config is not None
                    else raw
                )
                body = f"Načteno (raw): ••••{raw[-4:]}\n"
                if canonical != raw:
                    body += f"Po úpravě: ••••{canonical[-4:]}\n"
                body += f"Port: {chip.device.port or '—'}"
                message_dialog(
                    self.page,
                    title="Test čtečky",
                    body=body,
                )
            except Exception as exc:
                message_dialog(self.page, title="Test čtečky", body=str(exc))
            finally:
                try:
                    test_reader.stop()
                except Exception:
                    pass

        status_line = status.message if status else None
        controls: list[ft.Control] = [
            theme.text("Čtečka", theme.TextRole.ACTION),
            theme.text(
                f"Režim: {'Automaticky – ELATEC' if mode == 'auto_elatec' else 'Ruční COM'}",
                theme.TextRole.BODY,
            ),
            theme.text(
                f"Stav: {state_text}",
                theme.TextRole.BODY,
                color=theme.COLORS["accent"],
            ),
            theme.text("\n".join(device_lines), theme.TextRole.BODY),
        ]
        if status_line and status_line != state_text:
            controls.append(
                theme.text(
                    status_line,
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
        controls.extend(
            [
                mode_group,
                port_dd,
                baud_dd,
                line_dd,
                theme.text(
                    "Úprava kódu ze čtečky",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                ),
                theme.text(
                    "Pokud je zapnuté IKonverze a/nebo Přidat 00, JLL upraví "
                    "vstup ze čtečky před lookupem a zápisem (DB formát 16 znaků).",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                ),
                ikonverze_cb,
                pridat00_cb,
                ft.Row(
                    [
                        ft.FilledButton(
                            "Uložit", style=theme.button_style(), on_click=_save
                        ),
                        ft.OutlinedButton(
                            "Test čtečky", style=theme.button_style(), on_click=_test
                        ),
                    ],
                    spacing=theme.SPACING["sm"],
                ),
            ]
        )
        self.body.controls.append(self._content_card("Čtečka", controls))

    def _render_info(self) -> None:
        from ...dev_credits import AUTHOR_SIGNATURE, format_development_hours
        from ...version import application_version

        cfg = self.state.config
        hours_label = theme.text(
            f"Autor: {AUTHOR_SIGNATURE}\n"
            f"Verze: {application_version()}\n"
            f"Strávený čas (odhad): {format_development_hours()}",
            theme.TextRole.BODY,
        )
        controls: list[ft.Control] = [
            theme.text("Info", theme.TextRole.ACTION),
            theme.text(
                "Vývoj",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
            hours_label,
            theme.text(
                "Databáze",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
            theme.text(
                f"{cfg.host}:{cfg.port} / {cfg.database}" if cfg else "—",
                theme.TextRole.BODY,
            ),
            theme.text(
                "Stanice",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
            theme.text(
                f"Provozovna: {cfg.site_name}\nStanice: {cfg.instance_id}"
                if cfg
                else "—",
                theme.TextRole.BODY,
            ),
            ft.Divider(height=12, color=theme.COLORS["border"]),
            theme.text("Počáteční nastavení", theme.TextRole.ACTION),
            theme.text(
                "Vrátí tuto instalaci JLL do stavu prvního spuštění.\n"
                "Databázová data zůstanou beze změny.\n"
                "Lokální JLL profily a jejich JLL oprávnění budou vráceny do výchozího stavu.\n"
                "Databázoví uživatelé v JídelnaSQL zůstanou beze změny.",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
            ft.OutlinedButton(
                "Obnovit počáteční nastavení",
                style=theme.button_style(
                    color=theme.COLORS["danger"],
                    bgcolor=theme.COLORS["surface"],
                ),
                on_click=lambda _e: self._open_installation_reset_dialog(),
            ),
            ft.Divider(height=12, color=theme.COLORS["border"]),
            theme.text(
                "Changelog",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
            ft.OutlinedButton(
                "Zobrazit changelog",
                style=theme.button_style(),
                on_click=lambda _e: self._open_changelog_dialog(),
            ),
            theme.text(
                "Audit (posledních 50)",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
        ]
        events = self.state.identity_store.read_audit() if self.state.identity_store else []
        if not events:
            controls.append(
                theme.text(
                    "Žádné auditní záznamy.",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
        else:
            for event in events[-50:]:
                controls.append(
                    theme.text(
                        f"{event.get('timestamp')} · {event.get('action')} · {event.get('target')}",
                        theme.TextRole.META,
                    )
                )
        self.body.controls.append(self._content_card("Info", controls))

        # Průběžná aktualizace hodin, dokud je sekce Info otevřená.
        stop = getattr(self, "_info_hours_stop", None)
        if stop is not None:
            stop.set()
        import threading

        stop = threading.Event()
        self._info_hours_stop = stop

        def _tick() -> None:
            while not stop.wait(30.0):
                if self.section != "Info":
                    break

                def _apply() -> None:
                    if self.section != "Info":
                        return
                    hours_label.value = (
                        f"Autor: {AUTHOR_SIGNATURE}\n"
                        f"Verze: {application_version()}\n"
                        f"Strávený čas (odhad): {format_development_hours()}"
                    )
                    self.page.update()

                self.page.run_thread(_apply)

        threading.Thread(target=_tick, name="jll-info-hours", daemon=True).start()

    def _open_changelog_dialog(self) -> None:
        self.on_activity()
        from ...changelog_preview import load_changelog_preview

        entries = load_changelog_preview(limit=20)
        content_controls: list[ft.Control] = []
        if not entries:
            content_controls.append(
                theme.text(
                    "CHANGELOG.md není dostupný.",
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
        else:
            for entry in entries:
                content_controls.append(theme.text(entry.title, theme.TextRole.ACTION))
                for line in entry.summary_lines[:6]:
                    content_controls.append(
                        theme.text(
                            f"• {line}",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        )
                    )
        dialog_holder: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def _close(_e=None) -> None:
            dialog = dialog_holder["dialog"]
            if dialog is None:
                return
            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Changelog", theme.TextRole.PRIMARY),
            content=ft.Container(
                content=ft.Column(
                    content_controls,
                    tight=True,
                    spacing=theme.SPACING["sm"],
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=520,
                height=420,
            ),
            actions=[
                ft.TextButton("Zavřít", style=theme.button_style(), on_click=_close),
            ],
        )
        dialog_holder["dialog"] = dialog
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _open_installation_reset_dialog(self) -> None:
        self.on_activity()
        if self.on_installation_reset is None:
            message_dialog(
                self.page,
                title="Počáteční nastavení",
                body="Obnovení není v této session dostupné.",
            )
            return
        password = ft.TextField(
            label="Heslo administrátora SUP",
            password=True,
            can_reveal_password=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        confirm_btn = ft.FilledButton(
            "Obnovit počáteční nastavení",
            style=theme.button_style(bgcolor=theme.COLORS["danger"], color="#FFFFFF"),
        )
        dialog_holder: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def _close(_e=None) -> None:
            dialog = dialog_holder["dialog"]
            if dialog is None:
                return
            dialog.open = False
            self.page.update()

        def _confirm(_e=None) -> None:
            if self._reset_busy:
                return
            self._reset_busy = True
            confirm_btn.disabled = True
            self.page.update()
            try:
                ok, error = self.on_installation_reset(password.value or "")
            finally:
                self._reset_busy = False
            if ok:
                _close()
                return
            confirm_btn.disabled = False
            self.page.update()
            message_dialog(
                self.page,
                title="Počáteční nastavení",
                body=error
                or "Obnovení počátečního nastavení se nepodařilo. "
                "Původní nastavení bylo zachováno.",
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Obnovit počáteční nastavení?", theme.TextRole.PRIMARY),
            content=ft.Container(
                content=ft.Column(
                    [
                        theme.text(
                            "JLL zapomene místní nastavení této instalace a znovu spustí "
                            "průvodce prvním nastavením.",
                            theme.TextRole.BODY,
                        ),
                        theme.text(
                            "Bude resetováno:\n"
                            "• připojení a volba stanice\n"
                            "• povolené kategorie\n"
                            "• nastavení čtečky\n"
                            "• vzhled aplikace\n"
                            "• lokální JLL profily a oprávnění",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        ),
                        theme.text(
                            "NEBUDE změněno:\n"
                            "• databáze strávníků\n"
                            "• objednávky\n"
                            "• platby\n"
                            "• čipy\n"
                            "• databázoví uživatelé",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        ),
                        password,
                    ],
                    tight=True,
                    spacing=theme.SPACING["sm"],
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=480,
                height=360,
            ),
            actions=[
                ft.TextButton("Zrušit", style=theme.button_style(), on_click=_close),
                confirm_btn,
            ],
        )
        confirm_btn.on_click = _confirm
        dialog_holder["dialog"] = dialog
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _render_sup_gate(self) -> None:
        password = ft.TextField(
            label="Heslo administrátora SUP",
            password=True,
            can_reveal_password=True,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )

        def _unlock(_e):
            if self.vm.require_sup_password(password.value or ""):
                self._open_section(self.section)
            else:
                message_dialog(self.page, title="SUP", body="Neplatné heslo administrátora.")

        self.body.controls.append(
            self._content_card(
                self.section,
                [
                    empty_state(
                        "Ověření SUP",
                        "Citlivé administrativní akce vyžadují heslo administrátora SUP.",
                    ),
                    password,
                    ft.FilledButton(
                        "Ověřit", style=theme.button_style(), on_click=_unlock
                    ),
                ],
            )
        )

    def _render_users(self) -> None:
        try:
            users = self.vm.list_db_users()
        except Exception as exc:
            self.body.controls.append(
                self._content_card("Uživatelé", [empty_state("Uživatelé", str(exc))])
            )
            return

        rows: list[ft.Control] = [
            ft.FilledButton(
                "+ Nový uživatel",
                style=theme.button_style(),
                on_click=self._new_user_dialog,
            ),
            ft.Row(
                [
                    ft.Container(
                        theme.text(
                            "Jméno/kód",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        ),
                        width=_USERS_NAME_W,
                    ),
                    ft.Container(
                        theme.text(
                            "Stav",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        ),
                        width=_USERS_STATUS_W,
                    ),
                    ft.Container(
                        theme.text(
                            "JLL profil",
                            theme.TextRole.META,
                            color=theme.COLORS["text_secondary"],
                        ),
                        width=_USERS_PROFILE_W,
                    ),
                    theme.text(
                        "Akce",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                ],
                spacing=theme.SPACING["sm"],
                tight=True,
            ),
        ]
        for user in users:
            status = "zakázaný" if user.disabled else "aktivní"
            profile = None
            for item in self.state.identity_store.list_users() if self.state.identity_store else []:
                if item.short_code.casefold() == user.code.casefold():
                    profile = item
                    break
            perms = (
                f"{len(profile.permissions)} oprávnění"
                if profile is not None
                else "bez JLL profilu"
            )
            rows.append(
                ft.Row(
                    [
                        ft.Container(
                            content=theme.text(
                                f"{user.code} · {user.display_name}",
                                theme.TextRole.BODY,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                max_lines=1,
                            ),
                            width=_USERS_NAME_W,
                        ),
                        ft.Container(
                            content=theme.text(status, theme.TextRole.META),
                            width=_USERS_STATUS_W,
                        ),
                        ft.Container(
                            content=theme.text(perms, theme.TextRole.META),
                            width=_USERS_PROFILE_W,
                        ),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Oprávnění",
                                    visible=profile is not None and not user.is_admin,
                                    style=theme.button_style(
                                        padding=ft.padding.symmetric(
                                            horizontal=8, vertical=0
                                        )
                                    ),
                                    on_click=lambda _e, u=user: self._edit_permissions(u),
                                ),
                                ft.TextButton(
                                    "Zavést profil",
                                    visible=profile is None and not user.is_admin,
                                    style=theme.button_style(
                                        padding=ft.padding.symmetric(
                                            horizontal=8, vertical=0
                                        )
                                    ),
                                    on_click=lambda _e, u=user: self._ensure(u),
                                ),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                    ],
                    spacing=theme.SPACING["sm"],
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        self.body.controls.append(self._content_card("Uživatelé", rows))

    def _ensure(self, user) -> None:
        try:
            self.vm.ensure_profile(user)
            message_dialog(self.page, title="Profil", body=f"JLL profil pro {user.code} vytvořen.")
            self._open_section("Uživatelé")
        except Exception as exc:
            message_dialog(self.page, title="Profil", body=str(exc))

    def _edit_permissions(self, user) -> None:
        try:
            profile = self.vm.ensure_profile(user)
        except Exception as exc:
            message_dialog(self.page, title="Oprávnění", body=str(exc))
            return
        selected = set(profile.permissions)
        checks: list[tuple[Permission, ft.Checkbox]] = []
        groups: list[ft.Control] = [
            theme.text(f"Oprávnění · {user.code}", theme.TextRole.ACTION)
        ]
        current_group = None
        for item in PERMISSION_CATALOG:
            if item.group != current_group:
                current_group = item.group
                groups.append(
                    theme.text(
                        current_group,
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    )
                )
            cb = ft.Checkbox(
                label=item.title_cs,
                label_style=theme.role_style(theme.TextRole.BODY),
                value=item.permission in selected,
                tooltip=item.description_cs,
            )
            checks.append((item.permission, cb))
            groups.append(cb)

        def _save(_e):
            try:
                perms = frozenset(p for p, cb in checks if cb.value)
                self.vm.set_permissions(user.code, perms)
                dialog.open = False
                self.page.update()
                message_dialog(
                    self.page,
                    title="Oprávnění",
                    body=f"Uloženo pro {user.code} ({len(perms)} oprávnění).",
                )
                self._open_section("Uživatelé")
            except Exception as exc:
                message_dialog(self.page, title="Oprávnění", body=str(exc))

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Upravit oprávnění", theme.TextRole.PRIMARY),
            content=ft.Container(
                content=ft.Column(groups, scroll=ft.ScrollMode.AUTO, spacing=4),
                width=560,
                height=460,
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

    def _new_user_dialog(self, _e) -> None:
        code = ft.TextField(
            label="Kód uživatele",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )
        name = ft.TextField(
            label="Jméno",
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
        )

        def _create(_ev):
            try:
                created = self.vm.create_user(code.value or "", name.value or "")
                dialog.open = False
                self.page.update()
                message_dialog(
                    self.page,
                    title="Uživatel",
                    body=f"Vytvořen {created.code} · {created.display_name}",
                )
                self._open_section("Uživatelé")
            except Exception as exc:
                message_dialog(self.page, title="Uživatel", body=str(exc))

        dialog = ft.AlertDialog(
            modal=True,
            title=theme.text("Nový uživatel", theme.TextRole.PRIMARY),
            content=ft.Column([code, name], tight=True, height=140),
            actions=[
                ft.TextButton(
                    "Zrušit",
                    style=theme.button_style(),
                    on_click=lambda _e: setattr(dialog, "open", False) or self.page.update(),
                ),
                ft.FilledButton(
                    "Vytvořit", style=theme.button_style(), on_click=_create
                ),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _render_permissions_help(self) -> None:
        controls: list[ft.Control] = [
            theme.text("Uživatelská oprávnění", theme.TextRole.ACTION),
            theme.text(
                "Vyberte uživatele a upravte česká oprávnění. "
                "SUP zůstává oddělený přes heslo administrátora.",
                theme.TextRole.BODY,
                color=theme.COLORS["text_secondary"],
            ),
        ]
        try:
            users = self.vm.list_db_users()
        except Exception as exc:
            controls.append(empty_state("Oprávnění", str(exc)))
            self.body.controls.append(self._content_card("Oprávnění", controls))
            return
        for user in users:
            if user.is_admin or user.code.upper() == "SUP":
                continue
            profile = None
            for item in self.state.identity_store.list_users() if self.state.identity_store else []:
                if item.short_code.casefold() == user.code.casefold():
                    profile = item
                    break
            count = len(profile.permissions) if profile is not None else 0
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    theme.text(
                                        f"{user.code} · {user.display_name}",
                                        theme.TextRole.BODY,
                                    ),
                                    theme.text(
                                        f"{count} oprávnění"
                                        if profile
                                        else "bez JLL profilu",
                                        theme.TextRole.META,
                                        color=theme.COLORS["text_secondary"],
                                    ),
                                ],
                                spacing=0,
                                tight=True,
                            ),
                            ft.TextButton(
                                "Upravit",
                                style=theme.button_style(
                                    padding=ft.padding.symmetric(
                                        horizontal=8, vertical=0
                                    )
                                ),
                                on_click=lambda _e, u=user: self._edit_permissions(u),
                            ),
                        ],
                        spacing=theme.SPACING["md"],
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(vertical=2),
                )
            )
        controls.append(ft.Divider(height=1))
        controls.append(theme.text("Katalog oprávnění", theme.TextRole.ACTION))
        current_group = None
        for item in PERMISSION_CATALOG:
            if item.group != current_group:
                current_group = item.group
                controls.append(theme.text(current_group, theme.TextRole.META))
            controls.append(
                theme.text(
                    f"{item.title_cs} — {item.description_cs}",
                    theme.TextRole.META,
                )
            )
        self.body.controls.append(self._content_card("Oprávnění", controls))

    def _render_appearance(self) -> None:
        from ...typography_settings import (
            DEFAULT_TYPOGRAPHY,
            ROLE_KEYS,
            ROLE_LABELS_CS,
            SIZE_MAX,
            SIZE_MIN,
            TypographyRoleSettings,
            TypographySettings,
            validate_role_size,
        )

        draft = {
            key: self.state.typography.for_key(key) for key in ROLE_KEYS
        }
        size_fields: dict[str, ft.TextField] = {}
        bold_boxes: dict[str, ft.Checkbox] = {}
        after_hosts: dict[str, ft.Container] = {}
        error_hosts: dict[str, ft.Container] = {}
        preview_samples = {
            "primary": "Scio Kuchyně · Jarov",
            "body": "Oběd-A · Menu 1",
            "action": "Dnešní objednávky",
            "meta": "Úterý 8. září 2026",
        }
        role_enum = {
            "primary": theme.TextRole.PRIMARY,
            "body": theme.TextRole.BODY,
            "action": theme.TextRole.ACTION,
            "meta": theme.TextRole.META,
        }

        def _after_label(key: str) -> str:
            role = draft[key]
            weight = "tučně" if role.bold else "normální"
            return f"Po uložení: {role.size:g} px · {weight}"

        def _refresh_after(key: str) -> None:
            after_hosts[key].content = theme.text(
                _after_label(key),
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            )
            self.page.update()

        def _parse_size(key: str) -> float | None:
            raw = (size_fields[key].value or "").strip().replace(",", ".")
            try:
                return validate_role_size(float(raw))
            except (TypeError, ValueError) as exc:
                error_hosts[key].content = theme.text(
                    str(exc),
                    theme.TextRole.META,
                    color=theme.COLORS["danger"],
                )
                return None

        def _on_size_change(key: str) -> None:
            self.on_activity()
            value = _parse_size(key)
            if value is None:
                self.page.update()
                return
            error_hosts[key].content = ft.Container(height=0)
            draft[key] = TypographyRoleSettings(value, bold_boxes[key].value is True)
            _refresh_after(key)

        def _on_bold_change(key: str) -> None:
            self.on_activity()
            value = _parse_size(key)
            if value is None:
                value = draft[key].size
            else:
                error_hosts[key].content = ft.Container(height=0)
            draft[key] = TypographyRoleSettings(value, bold_boxes[key].value is True)
            _refresh_after(key)

        def _reset(_e=None) -> None:
            self.on_activity()
            for key in ROLE_KEYS:
                role = DEFAULT_TYPOGRAPHY.for_key(key)
                draft[key] = role
                size_fields[key].value = f"{role.size:g}"
                bold_boxes[key].value = role.bold
                error_hosts[key].content = ft.Container(height=0)
                after_hosts[key].content = theme.text(
                    _after_label(key),
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            self.page.update()

        def _save(_e=None) -> None:
            self.on_activity()
            roles: dict[str, TypographyRoleSettings] = {}
            ok = True
            for key in ROLE_KEYS:
                value = _parse_size(key)
                if value is None:
                    ok = False
                    continue
                roles[key] = TypographyRoleSettings(
                    value, bold_boxes[key].value is True
                )
            if not ok:
                self.page.update()
                return
            try:
                settings = TypographySettings(**roles)
            except ValueError as exc:
                message_dialog(self.page, title="Vzhled", body=str(exc))
                return
            self.on_typography_save(settings)

        rows: list[ft.Control] = [
            theme.text("Písmo", theme.TextRole.ACTION),
            theme.text(
                "Upravte čtyři styly používané v celé aplikaci. "
                "Změna se projeví až po Uložit.",
                theme.TextRole.META,
                color=theme.COLORS["text_secondary"],
            ),
        ]
        for key in ROLE_KEYS:
            role = draft[key]
            text_role = role_enum[key]
            size_field = ft.TextField(
                label="Velikost (px)",
                value=f"{role.size:g}",
                width=140,
                text_size=theme.field_text_size(),
                label_style=theme.field_label_style(),
                on_change=lambda _e, k=key: _on_size_change(k),
                on_blur=lambda _e, k=key: _on_size_change(k),
            )
            bold = ft.Checkbox(
                label="Tučně",
                value=role.bold,
                label_style=theme.role_style(theme.TextRole.BODY),
                on_change=lambda _e, k=key: _on_bold_change(k),
            )
            sample = ft.Column(
                [
                    theme.text(
                        "Aktuální vzhled",
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    theme.text(preview_samples[key], text_role),
                ],
                spacing=2,
                tight=True,
            )
            after = ft.Container(
                content=theme.text(
                    _after_label(key),
                    theme.TextRole.META,
                    color=theme.COLORS["text_secondary"],
                )
            )
            err = ft.Container(height=0)
            size_fields[key] = size_field
            bold_boxes[key] = bold
            after_hosts[key] = after
            error_hosts[key] = err
            rows.extend(
                [
                    theme.text(ROLE_LABELS_CS[key], theme.TextRole.ACTION),
                    ft.Row(
                        [
                            size_field,
                            theme.text(
                                f"{SIZE_MIN:g}–{SIZE_MAX:g}",
                                theme.TextRole.META,
                                color=theme.COLORS["text_secondary"],
                            ),
                            bold,
                        ],
                        spacing=theme.SPACING["sm"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        wrap=True,
                    ),
                    sample,
                    after,
                    err,
                ]
            )

        rows.append(
            ft.Row(
                [
                    ft.OutlinedButton(
                        "Obnovit výchozí",
                        style=theme.button_style(),
                        on_click=_reset,
                    ),
                    ft.FilledButton(
                        "Uložit",
                        style=theme.button_style(),
                        on_click=_save,
                    ),
                ],
                spacing=theme.SPACING["sm"],
            )
        )
        self.body.controls.append(self._content_card("Vzhled", rows))
