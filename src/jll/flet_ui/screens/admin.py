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
    def __init__(self, page: ft.Page, state: AppState, *, on_text_scale) -> None:
        self.page = page
        self.state = state
        self.vm = AdminViewModel(state)
        self.on_text_scale = on_text_scale
        self.section = "Uživatelé"
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=6, tight=False)
        self.nav = ft.Column(spacing=0, tight=True)
        self._rebuild_nav()
        self.root = ft.Column(
            [
                ft.Text(
                    "Administrace",
                    size=theme.role_size(theme.TextRole.PRIMARY),
                    weight=ft.FontWeight.W_700,
                ),
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
        self._open_section("Uživatelé")

    def control(self) -> ft.Control:
        return self.root

    def _rebuild_nav(self) -> None:
        self.nav.controls.clear()
        for name in SECTIONS:
            active = name == self.section
            self.nav.controls.append(
                ft.Container(
                    content=ft.Text(
                        name,
                        size=theme.role_size(theme.TextRole.ACTION),
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
            cats = sorted(self.state.config.allowed_categories) if self.state.config else []
            self.body.controls.append(
                self._content_card(
                    name,
                    [
                        ft.Text(
                            "Povolené kategorie",
                            size=theme.role_size(theme.TextRole.ACTION),
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            ", ".join(cats) or "—",
                            size=theme.role_size(theme.TextRole.BODY),
                        ),
                    ],
                )
            )
        elif name == "Info":
            self._render_info()
        elif name == "Čtečka":
            self._render_reader()
        self.page.update()

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
                self._content_card("Čtečka", [ft.Text("Config není načten.")])
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
                    ft.Radio(value="auto_elatec", label="Automaticky – ELATEC"),
                    ft.Radio(value="manual", label="Ručně vybrat COM port"),
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
        )
        baud_dd = ft.Dropdown(
            label="Baud",
            options=[
                ft.dropdown.Option(key=str(b), text=str(b))
                for b in (9600, 19200, 38400, 57600, 115200)
            ],
            value=str(cfg.reader_baud_rate),
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
                message_dialog(
                    self.page,
                    title="Test čtečky",
                    body=f"Načteno: ••••{chip.code[-4:]}\nPort: {chip.device.port or '—'}",
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
            ft.Text(
                "Čtečka",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                f"Režim: {'Automaticky – ELATEC' if mode == 'auto_elatec' else 'Ruční COM'}",
                size=theme.role_size(theme.TextRole.BODY),
            ),
            ft.Text(
                f"Stav: {state_text}",
                size=theme.role_size(theme.TextRole.BODY),
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                "\n".join(device_lines),
                size=theme.role_size(theme.TextRole.BODY),
            ),
        ]
        if status_line and status_line != state_text:
            controls.append(
                ft.Text(
                    status_line,
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            )
        controls.extend(
            [
                mode_group,
                port_dd,
                baud_dd,
                line_dd,
                ft.Row(
                    [
                        ft.FilledButton("Uložit", on_click=_save),
                        ft.OutlinedButton("Test čtečky", on_click=_test),
                    ],
                    spacing=theme.SPACING["sm"],
                ),
            ]
        )
        self.body.controls.append(self._content_card("Čtečka", controls))

    def _render_info(self) -> None:
        cfg = self.state.config
        controls: list[ft.Control] = [
            ft.Text(
                "Info",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                "Databáze",
                size=theme.role_size(theme.TextRole.META),
                weight=ft.FontWeight.W_700,
                color=theme.COLORS["text_secondary"],
            ),
            ft.Text(
                f"{cfg.host}:{cfg.port} / {cfg.database}" if cfg else "—",
                size=theme.role_size(theme.TextRole.BODY),
            ),
            ft.Text(
                "Stanice",
                size=theme.role_size(theme.TextRole.META),
                weight=ft.FontWeight.W_700,
                color=theme.COLORS["text_secondary"],
            ),
            ft.Text(
                f"Provozovna: {cfg.site_name}\nStanice: {cfg.instance_id}"
                if cfg
                else "—",
                size=theme.role_size(theme.TextRole.BODY),
            ),
            ft.Text(
                "Audit (posledních 50)",
                size=theme.role_size(theme.TextRole.META),
                weight=ft.FontWeight.W_700,
                color=theme.COLORS["text_secondary"],
            ),
        ]
        events = self.state.identity_store.read_audit() if self.state.identity_store else []
        if not events:
            controls.append(
                ft.Text(
                    "Žádné auditní záznamy.",
                    size=theme.role_size(theme.TextRole.META),
                    color=theme.COLORS["text_secondary"],
                )
            )
        else:
            for event in events[-50:]:
                controls.append(
                    ft.Text(
                        f"{event.get('timestamp')} · {event.get('action')} · {event.get('target')}",
                        size=theme.role_size(theme.TextRole.META),
                    )
                )
        self.body.controls.append(self._content_card("Info", controls))

    def _render_sup_gate(self) -> None:
        password = ft.TextField(
            label="Heslo administrátora SUP",
            password=True,
            can_reveal_password=True,
            text_size=theme.role_size(theme.TextRole.BODY),
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
                    ft.FilledButton("Ověřit", on_click=_unlock),
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

        header_style = dict(
            size=theme.role_size(theme.TextRole.META),
            weight=ft.FontWeight.W_700,
            color=theme.COLORS["text_secondary"],
        )
        rows: list[ft.Control] = [
            ft.FilledButton("+ Nový uživatel", on_click=self._new_user_dialog),
            ft.Row(
                [
                    ft.Container(ft.Text("Jméno/kód", **header_style), width=_USERS_NAME_W),
                    ft.Container(ft.Text("Stav", **header_style), width=_USERS_STATUS_W),
                    ft.Container(
                        ft.Text("JLL profil", **header_style), width=_USERS_PROFILE_W
                    ),
                    ft.Text("Akce", **header_style),
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
                            content=ft.Text(
                                f"{user.code} · {user.display_name}",
                                size=theme.role_size(theme.TextRole.BODY),
                                overflow=ft.TextOverflow.ELLIPSIS,
                                max_lines=1,
                            ),
                            width=_USERS_NAME_W,
                        ),
                        ft.Container(
                            content=ft.Text(
                                status, size=theme.role_size(theme.TextRole.META)
                            ),
                            width=_USERS_STATUS_W,
                        ),
                        ft.Container(
                            content=ft.Text(
                                perms, size=theme.role_size(theme.TextRole.META)
                            ),
                            width=_USERS_PROFILE_W,
                        ),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Oprávnění",
                                    visible=profile is not None and not user.is_admin,
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.symmetric(
                                            horizontal=8, vertical=0
                                        )
                                    ),
                                    on_click=lambda _e, u=user: self._edit_permissions(u),
                                ),
                                ft.TextButton(
                                    "Zavést profil",
                                    visible=profile is None and not user.is_admin,
                                    style=ft.ButtonStyle(
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
            ft.Text(
                f"Oprávnění · {user.code}",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            )
        ]
        current_group = None
        for item in PERMISSION_CATALOG:
            if item.group != current_group:
                current_group = item.group
                groups.append(
                    ft.Text(
                        current_group,
                        size=theme.role_size(theme.TextRole.META),
                        weight=ft.FontWeight.W_700,
                        color=theme.COLORS["text_secondary"],
                    )
                )
            cb = ft.Checkbox(
                label=item.title_cs,
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
            title=ft.Text(
                "Upravit oprávnění",
                size=theme.role_size(theme.TextRole.PRIMARY),
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(
                content=ft.Column(groups, scroll=ft.ScrollMode.AUTO, spacing=4),
                width=560,
                height=460,
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

    def _new_user_dialog(self, _e) -> None:
        code = ft.TextField(label="Kód uživatele", text_size=theme.role_size(theme.TextRole.BODY))
        name = ft.TextField(label="Jméno", text_size=theme.role_size(theme.TextRole.BODY))

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
            title=ft.Text("Nový uživatel", size=theme.role_size(theme.TextRole.PRIMARY), weight=ft.FontWeight.W_700),
            content=ft.Column([code, name], tight=True, height=140),
            actions=[
                ft.TextButton("Zrušit", on_click=lambda _e: setattr(dialog, "open", False) or self.page.update()),
                ft.FilledButton("Vytvořit", on_click=_create),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _render_permissions_help(self) -> None:
        controls: list[ft.Control] = [
            ft.Text(
                "Uživatelská oprávnění",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                "Vyberte uživatele a upravte česká oprávnění. "
                "SUP zůstává oddělený přes heslo administrátora.",
                size=theme.role_size(theme.TextRole.BODY),
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
                                    ft.Text(
                                        f"{user.code} · {user.display_name}",
                                        size=theme.role_size(theme.TextRole.BODY),
                                        weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        f"{count} oprávnění"
                                        if profile
                                        else "bez JLL profilu",
                                        size=theme.role_size(theme.TextRole.META),
                                        color=theme.COLORS["text_secondary"],
                                    ),
                                ],
                                spacing=0,
                                tight=True,
                            ),
                            ft.TextButton(
                                "Upravit",
                                style=ft.ButtonStyle(
                                    padding=ft.padding.symmetric(horizontal=8, vertical=0)
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
        controls.append(
            ft.Text(
                "Katalog oprávnění",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            )
        )
        current_group = None
        for item in PERMISSION_CATALOG:
            if item.group != current_group:
                current_group = item.group
                controls.append(
                    ft.Text(
                        current_group,
                        size=theme.role_size(theme.TextRole.META),
                        weight=ft.FontWeight.W_700,
                    )
                )
            controls.append(
                ft.Text(
                    f"{item.title_cs} — {item.description_cs}",
                    size=theme.role_size(theme.TextRole.META),
                )
            )
        self.body.controls.append(self._content_card("Oprávnění", controls))

    def _render_appearance(self) -> None:
        group = ft.RadioGroup(
            content=ft.Column(
                [
                    ft.Radio(
                        value=scale.name,
                        label=scale.label_cs,
                    )
                    for scale in theme.TextScale
                ],
                tight=True,
                spacing=2,
            ),
            value=self.state.text_scale.name,
            on_change=lambda e: self.on_text_scale(theme.TextScale[e.control.value]),
        )
        self.body.controls.append(
            self._content_card(
                "Vzhled",
                [
                    ft.Text(
                        "Velikost textu",
                        size=theme.role_size(theme.TextRole.ACTION),
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "Zvolte velikost textu v celé aplikaci.",
                        size=theme.role_size(theme.TextRole.META),
                        color=theme.COLORS["text_secondary"],
                    ),
                    group,
                ],
            )
        )
