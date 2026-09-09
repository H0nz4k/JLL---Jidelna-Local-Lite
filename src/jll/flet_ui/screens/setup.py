"""Flet first-run setup (bez PIN)."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..components.dialogs import message_dialog
from ..state import AppState
from ..viewmodels.setup import SetupViewModel
from ...setup_probe import CategoryOption


def _field(**kwargs) -> ft.TextField:
    kwargs.setdefault("text_size", theme.field_text_size())
    kwargs.setdefault("label_style", theme.field_label_style())
    return ft.TextField(**kwargs)


class SetupScreen:
    def __init__(self, page: ft.Page, state: AppState, *, on_finished) -> None:
        self.page = page
        self.state = state
        self.on_finished = on_finished
        self.vm = SetupViewModel(state)
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=theme.SPACING["md"])
        self.root = ft.Container(
            content=ft.Column(
                [
                    theme.text("První nastavení", theme.TextRole.PRIMARY),
                    theme.text(
                        " · ".join(self.vm.STEPS),
                        theme.TextRole.META,
                        color=theme.COLORS["text_secondary"],
                    ),
                    self.body,
                ],
                expand=True,
                spacing=theme.SPACING["lg"],
            ),
            expand=True,
            padding=theme.SPACING["xl"],
            bgcolor=theme.COLORS["background"],
        )
        self._render()

    def control(self) -> ft.Control:
        return self.root

    def _render(self) -> None:
        self.body.controls.clear()
        step = self.vm.draft.step
        title = self.vm.STEPS[step]
        self.body.controls.append(theme.text(title, theme.TextRole.ACTION))
        if step == 0:
            self._step_mode()
        elif step == 1:
            self._step_db()
        elif step == 2:
            self._step_station()
        elif step == 3:
            self._step_categories()
        elif step == 4:
            self._step_sup()
        else:
            self._step_summary()
        nav = []
        if step > 0:
            nav.append(
                ft.OutlinedButton(
                    "Zpět", style=theme.button_style(), on_click=lambda _e: self._back()
                )
            )
        if step < len(self.vm.STEPS) - 1:
            nav.append(
                ft.FilledButton(
                    "Další", style=theme.button_style(), on_click=lambda _e: self._next()
                )
            )
        else:
            nav.append(
                ft.FilledButton(
                    "Dokončit",
                    style=theme.button_style(),
                    on_click=lambda _e: self._finish(),
                )
            )
        self.body.controls.append(ft.Row(nav, spacing=theme.SPACING["sm"]))
        self.page.update()

    def _step_mode(self) -> None:
        d = self.vm.draft

        def _set_lab(_e=None) -> None:
            d.environment = "lab"
            d.host = "127.0.0.1"
            if not d.database.startswith("jll_"):
                d.database = "jll_demo_lab"
            self._render()

        def _set_prod(_e=None) -> None:
            d.environment = "production"
            if d.host in {"127.0.0.1", "localhost", "::1"}:
                d.host = ""
            self._render()

        self.body.controls.extend(
            [
                theme.text(
                    "Zvolte režim instalace. Production cílí na zákaznickou DB "
                    "se System ID pinningem (bez loopback / jll_ požadavku).",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                ),
                ft.RadioGroup(
                    value=d.environment,
                    content=ft.Column(
                        [
                            ft.Radio(value="lab", label="LAB (loopback + jll_*)"),
                            ft.Radio(
                                value="production",
                                label="PRODUCTION (hostname/IP + keyring)",
                            ),
                        ]
                    ),
                    on_change=lambda e: (
                        _set_prod()
                        if (e.control.value or "") == "production"
                        else _set_lab()
                    ),
                ),
            ]
        )

    def _step_db(self) -> None:
        d = self.vm.draft
        host = _field(label="Host", value=d.host)
        port = _field(label="Port", value=d.port)
        database = _field(label="Databáze", value=d.database)
        user = _field(label="DB uživatel", value=d.user)
        password = _field(
            label="DB heslo", value=d.password, password=True, can_reveal_password=True
        )
        status = theme.text(
            "Spojení zatím nebylo ověřeno."
            if d.probe is None
            else f"OK · {len(d.probe.stations)} stanic",
            theme.TextRole.BODY,
        )

        def _save_fields() -> None:
            d.host, d.port, d.database, d.user, d.password = (
                host.value or "",
                port.value or "",
                database.value or "",
                user.value or "",
                password.value or "",
            )

        def _test(_e):
            _save_fields()
            try:
                probe = self.vm.test_database()
                status.value = (
                    f"OK · provozovna: {probe.subject_name or 'ručně'} · "
                    f"{len(probe.stations)} stanic · {len(probe.categories)} kategorií"
                )
            except Exception as exc:
                status.value = str(exc)
            self.page.update()

        self.body.controls.extend(
            [
                host,
                port,
                database,
                user,
                password,
                ft.OutlinedButton(
                    "Otestovat spojení", style=theme.button_style(), on_click=_test
                ),
                status,
            ]
        )
        self._persist = _save_fields

    def _step_station(self) -> None:
        d = self.vm.draft
        if d.probe is None:
            self.body.controls.append(theme.text("Nejprve ověřte databázi.", theme.TextRole.BODY))
            return
        site = _field(
            label="Provozovna",
            value=d.site_name,
            on_change=lambda e: setattr(d, "site_name", e.control.value or ""),
        )
        options = [
            ft.dropdown.Option(key=st.name, text=st.name)
            for st in d.probe.stations
            if st.usable_as_instance_id
        ]
        station = ft.Dropdown(
            label="Stanice",
            options=options,
            value=d.station.name if d.station else None,
            text_size=theme.field_text_size(),
            label_style=theme.field_label_style(),
            on_change=lambda e: self._pick_station(e.control.value),
        )
        self.body.controls.extend([site, station])
        self._persist = lambda: None

    def _pick_station(self, name: str | None) -> None:
        if not name or self.vm.draft.probe is None:
            return
        for st in self.vm.draft.probe.stations:
            if st.name == name:
                self.vm.draft.station = st
                break

    def _step_categories(self) -> None:
        d = self.vm.draft
        if d.probe is None:
            self.body.controls.append(theme.text("Nejprve ověřte databázi.", theme.TextRole.BODY))
            return
        options = d.probe.category_options or tuple(
            CategoryOption(code=c) for c in d.probe.categories
        )
        checkboxes: list[ft.Checkbox] = []

        def _sync_all_box() -> None:
            all_box.value = bool(options) and len(d.categories) == len(options)
            all_box.update()

        def _toggle_all(e: ft.ControlEvent) -> None:
            selected = bool(e.control.value)
            d.categories = [item.code for item in options] if selected else []
            for cb, item in zip(checkboxes, options, strict=True):
                cb.value = selected
            self.page.update()

        def _toggle_one(code: str, selected: bool) -> None:
            self._toggle_cat(code, selected)
            _sync_all_box()

        all_box = ft.Checkbox(
            label="Vybrat vše",
            label_style=theme.role_style(theme.TextRole.BODY),
            value=bool(options) and len(d.categories) == len(options),
            on_change=_toggle_all,
        )
        self.body.controls.append(all_box)
        for item in options:
            cb = ft.Checkbox(
                label=item.label,
                label_style=theme.role_style(theme.TextRole.BODY),
                value=item.code in d.categories,
                on_change=lambda e, c=item.code: _toggle_one(c, bool(e.control.value)),
            )
            checkboxes.append(cb)
            self.body.controls.append(cb)
        self._persist = lambda: None

    def _toggle_cat(self, cat: str, selected: bool) -> None:
        cats = self.vm.draft.categories
        if selected and cat not in cats:
            cats.append(cat)
        if not selected and cat in cats:
            cats.remove(cat)

    def _step_sup(self) -> None:
        d = self.vm.draft
        p1 = _field(
            label="Heslo administrátora SUP",
            password=True,
            can_reveal_password=True,
            value=d.sup_password,
        )
        p2 = _field(
            label="Heslo znovu",
            password=True,
            can_reveal_password=True,
            value=d.sup_password_confirm,
        )

        def _save():
            d.sup_password = p1.value or ""
            d.sup_password_confirm = p2.value or ""

        self.body.controls.extend([p1, p2])
        self._persist = _save

    def _step_summary(self) -> None:
        d = self.vm.draft
        self.body.controls.append(
            theme.text(
                f"Režim: {d.environment}\n"
                f"Databáze: {d.host}:{d.port}/{d.database}\n"
                f"Provozovna: {d.site_name}\n"
                f"Stanice: {d.station.name if d.station else '—'}\n"
                f"Kategorie: {', '.join(d.categories)}\n"
                f"Default operátor: VED\n"
                f"SUP heslo: nastaveno",
                theme.TextRole.BODY,
            )
        )
        self._persist = lambda: None

    def _back(self) -> None:
        if hasattr(self, "_persist"):
            self._persist()
        self.vm.draft.step = max(0, self.vm.draft.step - 1)
        self._render()

    def _next(self) -> None:
        if hasattr(self, "_persist"):
            self._persist()
        try:
            # step 1 = Databáze
            if self.vm.draft.step == 1 and self.vm.draft.probe is None:
                self.vm.test_database()
            # step 4 = SUP heslo
            if self.vm.draft.step == 4:
                self.vm.validate_sup()
        except Exception as exc:
            message_dialog(self.page, title="Setup", body=str(exc))
            return
        self.vm.draft.step = min(len(self.vm.STEPS) - 1, self.vm.draft.step + 1)
        self._render()

    def _finish(self) -> None:
        if hasattr(self, "_persist"):
            self._persist()
        try:
            self.vm.finish()
            self.on_finished()
        except Exception as exc:
            message_dialog(self.page, title="Setup", body=str(exc))
