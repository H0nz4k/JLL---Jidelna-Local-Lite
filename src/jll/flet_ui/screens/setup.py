"""Flet first-run setup (bez PIN)."""

from __future__ import annotations

import flet as ft

from .. import theme
from ..components.dialogs import message_dialog
from ..state import AppState
from ..viewmodels.setup import SetupViewModel
from ...setup_probe import CategoryOption

SETUP_WINDOW_WIDTH = 760
SETUP_WINDOW_HEIGHT = 720
SETUP_CONTENT_WIDTH = 520


def _field(**kwargs) -> ft.TextField:
    kwargs.setdefault("text_size", theme.field_text_size())
    kwargs.setdefault("label_style", theme.field_label_style())
    kwargs.setdefault("width", 420)
    return ft.TextField(**kwargs)


class SetupScreen:
    def __init__(self, page: ft.Page, state: AppState, *, on_finished) -> None:
        self.page = page
        self.state = state
        self.on_finished = on_finished
        self.vm = SetupViewModel(
            state,
            environment_hint=state.environment_hint,
            allow_environment_choice=state.allow_environment_choice,
        )
        self._db_ok = self.vm.draft.probe is not None
        self._status_ok_text = ""
        self._next_btn: ft.FilledButton | None = None
        self._status_text: ft.Text | None = None
        self._steps_row = ft.Row(spacing=theme.SPACING["xs"], wrap=True)
        self._step_title = theme.text("", theme.TextRole.ACTION)
        # expand=True + scroll: body má omezenou výšku (zbývá pod hlavičkou),
        # jinak Column naroste přes okno a scroll vůbec nevznikne.
        self.body = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=theme.SPACING["sm"],
            width=SETUP_CONTENT_WIDTH,
        )
        self._nav = ft.Row(spacing=theme.SPACING["sm"], width=SETUP_CONTENT_WIDTH)
        self.root = ft.Container(
            content=ft.Column(
                [
                    theme.text("První nastavení", theme.TextRole.PRIMARY),
                    self._steps_row,
                    self._step_title,
                    self.body,
                    self._nav,
                ],
                expand=True,
                spacing=theme.SPACING["md"],
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            expand=True,
            padding=theme.SPACING["lg"],
            bgcolor=theme.COLORS["background"],
            alignment=ft.alignment.top_left,
        )
        self._apply_compact_window()
        self.page.on_keyboard_event = self._on_keyboard
        self._render()

    def control(self) -> ft.Control:
        return self.root

    def _apply_compact_window(self) -> None:
        try:
            self.page.window.maximized = False
            self.page.window.width = SETUP_WINDOW_WIDTH
            self.page.window.height = SETUP_WINDOW_HEIGHT
            self.page.window.min_width = 680
            self.page.window.min_height = 560
        except Exception:
            pass

    def _on_keyboard(self, e: ft.KeyboardEvent) -> None:
        if (e.key or "").lower() not in {"enter", "numpad enter"}:
            return
        if e.shift or e.ctrl or e.alt or e.meta:
            return
        self._primary_action()

    def _primary_action(self) -> None:
        step = self.vm.draft.step
        if step < len(self.vm.STEPS) - 1:
            if self._next_btn is not None and self._next_btn.disabled:
                return
            self._next()
        else:
            self._finish()

    def _render_steps_progress(self) -> None:
        self._steps_row.controls.clear()
        current = self.vm.draft.step
        for index, label in enumerate(self.vm.STEPS):
            if index > 0:
                self._steps_row.controls.append(
                    theme.text(" · ", theme.TextRole.META, color=theme.COLORS["text_secondary"])
                )
            if index < current:
                color = theme.COLORS["success"]
            elif index == current:
                color = theme.COLORS["text_primary"]
            else:
                color = theme.COLORS["text_secondary"]
            self._steps_row.controls.append(
                theme.text(label, theme.TextRole.META, color=color)
            )

    def _render(self) -> None:
        self.body.controls.clear()
        self.body.scroll = ft.ScrollMode.AUTO
        self._next_btn = None
        self._status_text = None
        self._render_steps_progress()
        step = self.vm.draft.step
        self._step_title.value = self.vm.STEPS[step]

        if self.vm.allow_environment_choice:
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
        else:
            if step == 0:
                self._step_db()
            elif step == 1:
                self._step_station()
            elif step == 2:
                self._step_categories()
            elif step == 3:
                self._step_sup()
            else:
                self._step_summary()

        nav: list[ft.Control] = []
        if step > 0:
            nav.append(
                ft.OutlinedButton(
                    "Zpět",
                    style=theme.button_style(),
                    on_click=lambda _e: self._back(),
                )
            )
        if step < len(self.vm.STEPS) - 1:
            can_next = True
            btn_style = theme.button_style()
            if self._is_db_step(step):
                can_next = self._db_ok and self.vm.draft.probe is not None
                if can_next:
                    btn_style = ft.ButtonStyle(
                        bgcolor=theme.COLORS["success"],
                        color="#FFFFFF",
                    )
            self._next_btn = ft.FilledButton(
                "Další",
                style=btn_style,
                disabled=not can_next,
                on_click=lambda _e: self._next(),
            )
            nav.append(self._next_btn)
        else:
            nav.append(
                ft.FilledButton(
                    "Dokončit",
                    style=ft.ButtonStyle(
                        bgcolor=theme.COLORS["success"],
                        color="#FFFFFF",
                    ),
                    on_click=lambda _e: self._finish(),
                )
            )
        # Navigace mimo scroll — Zpět/Další vždy viditelné.
        self._nav.controls = nav
        self.page.update()

    def _is_db_step(self, step: int) -> bool:
        return step == (0 if not self.vm.allow_environment_choice else 1)

    def _step_mode(self) -> None:
        d = self.vm.draft

        def _set_lab(_e=None) -> None:
            d.environment = "lab"
            d.host = "127.0.0.1"
            d.port = "5433"
            if not d.database.startswith("jll_"):
                d.database = "jll_demo_lab"
            d.user = "postgres"
            d.probe = None
            self._db_ok = False
            self._render()

        def _set_prod(_e=None) -> None:
            d.environment = "production"
            d.host = "127.0.0.1"
            d.port = "5432"
            d.database = "jidelna"
            d.user = "postgres"
            d.probe = None
            self._db_ok = False
            self._render()

        self.body.controls.extend(
            [
                theme.text(
                    "Zvolte režim instalace. Production cílí na zákaznickou DB "
                    "se System ID pinningem.",
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
        d.user = "postgres"
        if not self.vm.allow_environment_choice and self.vm.is_production:
            self.body.controls.append(
                theme.text(
                    "Připojení k provozní databázi (System ID pinning).",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                )
            )
        elif not self.vm.allow_environment_choice:
            self.body.controls.append(
                theme.text(
                    "LAB režim — lokální databáze jll_*.",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                )
            )

        host = _field(label="Host", value=d.host or "127.0.0.1")
        port = _field(label="Port", value=d.port or ("5432" if self.vm.is_production else "5433"))
        database = _field(
            label="Databáze",
            value=d.database or ("jidelna" if self.vm.is_production else "jll_demo_lab"),
        )
        password = _field(
            label="DB heslo",
            value=d.password,
            password=True,
            can_reveal_password=True,
        )

        def _invalidate(_e=None) -> None:
            if d.probe is not None or self._db_ok:
                d.probe = None
                self._db_ok = False
                self._status_ok_text = ""
                if self._status_text is not None:
                    self._status_text.value = "Spojení zatím nebylo ověřeno."
                    self._status_text.color = theme.COLORS["text_secondary"]
                if self._next_btn is not None:
                    self._next_btn.disabled = True
                    self._next_btn.style = theme.button_style()
                self.page.update()

        for control in (host, port, database, password):
            control.on_change = _invalidate

        initial_status = (
            self._status_ok_text
            if self._db_ok and d.probe is not None
            else "Spojení zatím nebylo ověřeno."
        )
        status = theme.text(
            initial_status,
            theme.TextRole.BODY,
            color=(
                theme.COLORS["success"]
                if self._db_ok and d.probe is not None
                else theme.COLORS["text_secondary"]
            ),
        )
        self._status_text = status

        def _save_fields() -> None:
            d.host = (host.value or "").strip() or "127.0.0.1"
            d.port = (port.value or "").strip() or ("5432" if self.vm.is_production else "5433")
            d.database = (database.value or "").strip() or (
                "jidelna" if self.vm.is_production else "jll_demo_lab"
            )
            d.user = "postgres"
            d.password = password.value or ""

        def _test(_e=None) -> None:
            _save_fields()
            try:
                probe = self.vm.test_database()
                self._db_ok = True
                self._status_ok_text = (
                    f"OK · provozovna: {probe.subject_name or 'ručně'} · "
                    f"{len(probe.stations)} stanic · {len(probe.categories)} kategorií"
                )
                status.value = self._status_ok_text
                status.color = theme.COLORS["success"]
                if self._next_btn is not None:
                    self._next_btn.disabled = False
                    self._next_btn.style = ft.ButtonStyle(
                        bgcolor=theme.COLORS["success"],
                        color="#FFFFFF",
                    )
            except Exception as exc:
                self._db_ok = False
                d.probe = None
                self._status_ok_text = ""
                status.value = str(exc)
                status.color = theme.COLORS["danger"]
                if self._next_btn is not None:
                    self._next_btn.disabled = True
                    self._next_btn.style = theme.button_style()
            self.page.update()

        password.on_submit = lambda _e: _test()
        self.body.controls.extend(
            [
                host,
                port,
                database,
                password,
                ft.OutlinedButton(
                    "Otestovat spojení",
                    style=theme.button_style(),
                    on_click=_test,
                ),
                status,
            ]
        )
        self._persist = _save_fields

    def _step_station(self) -> None:
        d = self.vm.draft
        if d.probe is None:
            self.body.controls.append(
                theme.text("Nejprve ověřte databázi.", theme.TextRole.BODY)
            )
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
            width=420,
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
            self.body.controls.append(
                theme.text("Nejprve ověřte databázi.", theme.TextRole.BODY)
            )
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
        for item in options:
            cb = ft.Checkbox(
                label=item.label,
                label_style=theme.role_style(theme.TextRole.BODY),
                value=item.code in d.categories,
                on_change=lambda e, c=item.code: _toggle_one(c, bool(e.control.value)),
            )
            checkboxes.append(cb)

        # ListView má vlastní viewport + scrollbar; body.scroll vypnout,
        # ať nevznikne vnitřní/vnější konflikt při desítkách kategorií.
        self.body.scroll = None
        category_list = ft.ListView(
            controls=checkboxes,
            expand=True,
            spacing=theme.SPACING["xs"],
            padding=ft.padding.only(right=8),
            auto_scroll=False,
        )
        self.body.controls.extend(
            [
                theme.text(
                    f"Vyberte kategorie povolené na této stanici ({len(options)}).",
                    theme.TextRole.BODY,
                    color=theme.COLORS["text_secondary"],
                ),
                all_box,
                category_list,
            ]
        )
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

        p2.on_submit = lambda _e: self._primary_action()
        self.body.controls.extend([p1, p2])
        self._persist = _save

    def _step_summary(self) -> None:
        d = self.vm.draft
        self.body.controls.append(
            theme.text(
                f"Režim: {d.environment}\n"
                f"Databáze: {d.host}:{d.port}/{d.database}\n"
                f"DB uživatel: postgres\n"
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
        step = self.vm.draft.step
        if self._is_db_step(step) and (not self._db_ok or self.vm.draft.probe is None):
            message_dialog(
                self.page,
                title="Setup",
                body="Nejdříve úspěšně otestujte spojení s databází.",
            )
            return
        try:
            if self.vm.allow_environment_choice:
                if step == 4:
                    self.vm.validate_sup()
                if step == 2 and self.vm.draft.station is None:
                    raise ValueError("Vyberte stanici.")
                if step == 3 and not self.vm.draft.categories:
                    raise ValueError("Vyberte alespoň jednu kategorii.")
            else:
                if step == 1 and self.vm.draft.station is None:
                    raise ValueError("Vyberte stanici.")
                if step == 2 and not self.vm.draft.categories:
                    raise ValueError("Vyberte alespoň jednu kategorii.")
                if step == 3:
                    self.vm.validate_sup()
        except Exception as exc:
            message_dialog(self.page, title="Setup", body=str(exc))
            return
        self.vm.draft.step = min(len(self.vm.STEPS) - 1, step + 1)
        self._render()

    def _finish(self) -> None:
        if hasattr(self, "_persist"):
            self._persist()
        try:
            self.vm.finish()
            self.on_finished()
        except Exception as exc:
            message_dialog(self.page, title="Setup", body=str(exc))
