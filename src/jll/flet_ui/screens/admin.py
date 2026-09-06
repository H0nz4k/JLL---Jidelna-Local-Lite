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
    "Databáze",
    "Stanice",
    "Čtečka",
    "Audit",
    "Vzhled",
)


class AdminScreen:
    def __init__(self, page: ft.Page, state: AppState, *, on_text_scale) -> None:
        self.page = page
        self.state = state
        self.vm = AdminViewModel(state)
        self.on_text_scale = on_text_scale
        self.section = "Uživatelé"
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
        self.nav = ft.Column(spacing=4)
        for name in SECTIONS:
            self.nav.controls.append(
                ft.TextButton(
                    name,
                    on_click=lambda _e, n=name: self._open_section(n),
                )
            )
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
                            width=180,
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
                            bgcolor=theme.COLORS["surface"],
                            padding=theme.SPACING["lg"],
                            border=ft.border.all(
                                theme.BLOCK_BORDER_WIDTH, theme.COLORS["block_border"]
                            ),
                            border_radius=8,
                        ),
                    ],
                    expand=True,
                    spacing=theme.SPACING["md"],
                ),
            ],
            expand=True,
            spacing=theme.SPACING["md"],
        )
        # SUP se ověřuje modalem v app.py před vstupem; tady už jen obsah.
        self._open_section("Uživatelé")

    def control(self) -> ft.Control:
        return self.root

    def _open_section(self, name: str) -> None:
        self.section = name
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
                ft.Text(
                    "Povolené kategorie",
                    size=theme.role_size(theme.TextRole.ACTION),
                    weight=ft.FontWeight.W_600,
                )
            )
            self.body.controls.append(
                ft.Text(", ".join(cats) or "—", size=theme.role_size(theme.TextRole.BODY))
            )
        elif name == "Databáze":
            cfg = self.state.config
            self.body.controls.append(
                ft.Text(
                    f"{cfg.host}:{cfg.port} / {cfg.database}" if cfg else "—",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )
        elif name == "Stanice":
            cfg = self.state.config
            self.body.controls.append(
                ft.Text(
                    f"Provozovna: {cfg.site_name}\nStanice: {cfg.instance_id}"
                    if cfg
                    else "—",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )
        elif name == "Čtečka":
            cfg = self.state.config
            self.body.controls.append(
                ft.Text(
                    f"Port: {cfg.reader_port or 'nenastaven'}\nBaud: {cfg.reader_baud_rate}"
                    if cfg
                    else "—",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )
        elif name == "Audit":
            events = self.state.identity_store.read_audit() if self.state.identity_store else []
            for event in events[-50:]:
                self.body.controls.append(
                    ft.Text(
                        f"{event.get('timestamp')} · {event.get('action')} · {event.get('target')}",
                        size=theme.role_size(theme.TextRole.META),
                    )
                )
        self.page.update()

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

        self.body.controls.extend(
            [
                empty_state(
                    "Ověření SUP",
                    "Citlivé administrativní akce vyžadují heslo administrátora SUP.",
                ),
                password,
                ft.FilledButton("Ověřit", on_click=_unlock),
            ]
        )

    def _render_users(self) -> None:
        try:
            users = self.vm.list_db_users()
        except Exception as exc:
            self.body.controls.append(empty_state("Uživatelé", str(exc)))
            return
        self.body.controls.append(
            ft.FilledButton("+ Nový uživatel", on_click=self._new_user_dialog)
        )
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
            row = ft.Row(
                [
                    ft.Text(
                        f"{user.code} · {user.display_name}",
                        size=theme.role_size(theme.TextRole.BODY),
                        expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                    ft.Text(status, size=theme.role_size(theme.TextRole.META)),
                    ft.Text(perms, size=theme.role_size(theme.TextRole.META)),
                    ft.TextButton(
                        "Oprávnění",
                        visible=profile is not None and not user.is_admin,
                        on_click=lambda _e, u=user: self._edit_permissions(u),
                    ),
                    ft.TextButton(
                        "Zavést profil",
                        visible=profile is None and not user.is_admin,
                        on_click=lambda _e, u=user: self._ensure(u),
                    ),
                ]
            )
            self.body.controls.append(row)

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
                width=480,
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
        self.body.controls.append(
            ft.Text(
                "Uživatelská oprávnění",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            )
        )
        self.body.controls.append(
            ft.Text(
                "Vyberte uživatele a upravte česká oprávnění. "
                "SUP zůstává oddělený přes heslo administrátora.",
                size=theme.role_size(theme.TextRole.BODY),
                color=theme.COLORS["text_secondary"],
            )
        )
        try:
            users = self.vm.list_db_users()
        except Exception as exc:
            self.body.controls.append(empty_state("Oprávnění", str(exc)))
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
            self.body.controls.append(
                ft.ListTile(
                    title=ft.Text(
                        f"{user.code} · {user.display_name}",
                        size=theme.role_size(theme.TextRole.BODY),
                    ),
                    subtitle=ft.Text(
                        f"{count} oprávnění" if profile else "bez JLL profilu",
                        size=theme.role_size(theme.TextRole.META),
                    ),
                    trailing=ft.TextButton(
                        "Upravit",
                        on_click=lambda _e, u=user: self._edit_permissions(u),
                    ),
                )
            )
        self.body.controls.append(ft.Divider())
        self.body.controls.append(
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
                self.body.controls.append(
                    ft.Text(
                        current_group,
                        size=theme.role_size(theme.TextRole.META),
                        weight=ft.FontWeight.W_700,
                    )
                )
            self.body.controls.append(
                ft.Text(
                    f"{item.title_cs} — {item.description_cs}",
                    size=theme.role_size(theme.TextRole.BODY),
                )
            )

    def _render_appearance(self) -> None:
        self.body.controls.append(
            ft.Text(
                "Velikost textu",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            )
        )
        for scale in theme.TextScale:
            self.body.controls.append(
                ft.Radio(
                    value=scale.name,
                    label=scale.name.replace("_", " ").title(),
                )
            )
        group = ft.RadioGroup(
            content=ft.Column(
                [
                    ft.Radio(value=theme.TextScale.NORMAL.name, label="Normální"),
                    ft.Radio(value=theme.TextScale.LARGE.name, label="Velký"),
                    ft.Radio(value=theme.TextScale.EXTRA_LARGE.name, label="Extra velký"),
                ]
            ),
            value=self.state.text_scale.name,
            on_change=lambda e: self.on_text_scale(theme.TextScale[e.control.value]),
        )
        self.body.controls = [
            ft.Text(
                "Velikost textu",
                size=theme.role_size(theme.TextRole.ACTION),
                weight=ft.FontWeight.W_600,
            ),
            group,
        ]
