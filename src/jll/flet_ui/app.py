"""Flet desktop application entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import flet as ft

from ..application import OrderApplicationService
from ..business_session import BusinessSession
from ..chip_reader import build_chip_reader
from ..config import load_lab_config
from ..identity_store import IdentityStore
from ..orders.service import OrderService
from ..policy import Permission
from ..read_service import OrderReadService
from ..sup_secret import SupSecretStore
from ..version import application_version
from . import theme
from .components.app_shell import app_shell
from .components.dialogs import message_dialog
from .routes import Route
from .screens.admin import AdminScreen
from .screens.diners import DinersScreen
from .screens.reports import ReportsScreen
from .screens.serving import ServingScreen
from .screens.setup import SetupScreen
from .state import AppState

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "lab.json"
DEFAULT_IDENTITY = PROJECT_ROOT / "config" / "users.lab.json"
DEFAULT_LOG = PROJECT_ROOT / "logs" / "jll-flet.log"


def configure_logging(path: Path = DEFAULT_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(item, RotatingFileHandler) for item in root.handlers):
        root.addHandler(handler)


class FletAppController:
    def __init__(self, page: ft.Page, state: AppState) -> None:
        self.page = page
        self.state = state
        page.title = "JidelnaLocalLite"
        page.window.width = theme.WINDOW_WIDTH
        page.window.height = theme.WINDOW_HEIGHT
        page.window.min_width = 1100
        page.window.min_height = 700
        page.bgcolor = theme.COLORS["background"]
        page.padding = 0
        page.theme_mode = ft.ThemeMode.LIGHT

    def start(self) -> None:
        if self.state.needs_setup or self.state.config is None or not self.state.identity_path.is_file():
            self._show_setup()
            return
        if self.state.config is not None:
            fallback = self.state.config_path.parent / "secrets"
            sup = SupSecretStore(self.state.config.instance_id, fallback_dir=fallback)
            if not sup.exists():
                self._show_setup()
                return
        try:
            self._wire_runtime()
            self.state.business.bootstrap_ved()
            self._show_main()
        except Exception as exc:
            message_dialog(self.page, title="Start", body=str(exc))
            self._show_setup()

    def _wire_runtime(self) -> None:
        config = load_lab_config(self.state.config_path)
        identity = IdentityStore(self.state.identity_path)
        pool = config.create_pool()
        fallback = self.state.config_path.parent / "secrets"
        business = BusinessSession(
            config=config,
            identity_store=identity,
            connection_factory=pool.connection,
            sup_store=SupSecretStore(config.instance_id, fallback_dir=fallback),
        )
        self.state.config = config
        self.state.identity_store = identity
        self.state.pool = pool
        self.state.business = business
        self.state.read_service = OrderReadService(
            pool.connection,
            config.order_settings,
            business.current_policy,
            search_limit=config.search_limit,
        )

        def scope_for_order(_command: object | None = None):
            business.current_policy().require(Permission.ORDERS_CHANGE)
            return business.current_policy().scope()

        order_service = OrderService(
            pool.connection,
            config.order_settings,
            scope_for_order,
        )
        self.state.application_service = OrderApplicationService(
            order_service,
            self.state.read_service,
            business.current_policy,
            business.current_actor,
        )
        self.state.chip_reader = build_chip_reader(
            config.reader_port,
            baud_rate=config.reader_baud_rate,
            line_end=config.reader_line_end,
        )
        try:
            self.state.diagnostics = self.state.read_service.verify_lab()
        except Exception:
            self.state.diagnostics = None

    def _show_setup(self) -> None:
        self.state.needs_setup = True
        screen = SetupScreen(self.page, self.state, on_finished=self._after_setup)
        self.page.controls.clear()
        self.page.add(screen.control())
        self.page.update()

    def _after_setup(self) -> None:
        self.state.needs_setup = False
        self._wire_runtime()
        self.state.business.bootstrap_ved()
        self._show_main()

    def _show_main(self) -> None:
        self.state.route = Route.DINERS
        self._render_shell()

    def _render_shell(self) -> None:
        workspace = self._workspace()
        shell = app_shell(
            self.page,
            self.state,
            workspace=workspace,
            on_route=self._set_route,
            on_user_switched=self._on_user_switched,
            on_diagnostics=self._diagnostics,
        )
        self.page.controls.clear()
        self.page.add(shell)
        self.page.update()

    def _workspace(self) -> ft.Control:
        if self.state.route is Route.DINERS:
            return DinersScreen(self.page, self.state).control()
        if self.state.route is Route.SERVING:
            return ServingScreen(self.page, self.state).control()
        if self.state.route is Route.REPORTS:
            return ReportsScreen(self.page, self.state).control()
        if self.state.route is Route.ADMIN:
            return AdminScreen(
                self.page,
                self.state,
                on_text_scale=self._set_scale,
            ).control()
        return ft.Text("Neznámá obrazovka")

    def _set_route(self, route: Route) -> None:
        self.state.route = route
        self._render_shell()

    def _on_user_switched(self) -> None:
        # Rebuild services against new policy/actor closures (same objects, methods refresh)
        self._render_shell()

    def _set_scale(self, scale: theme.TextScale) -> None:
        self.state.text_scale = scale
        self._render_shell()

    def _diagnostics(self) -> None:
        cfg = self.state.config
        diag = self.state.diagnostics
        lines = [
            f"Verze: {application_version()}",
            f"DB: {cfg.database if cfg else '—'}",
            f"Host: {cfg.host if cfg else '—'}",
            f"Provozovna: {cfg.site_name if cfg else '—'}",
            f"Stanice: {cfg.instance_id if cfg else '—'}",
        ]
        if diag is not None:
            lines.append(f"system_identifier: {diag.system_identifier}")
        message_dialog(self.page, title="Diagnostika", body="\n".join(lines))


def run_app(
    *,
    config_path: Path = DEFAULT_CONFIG,
    identity_path: Path = DEFAULT_IDENTITY,
) -> None:
    configure_logging()
    state = AppState(config_path=config_path, identity_path=identity_path)
    if config_path.is_file() and identity_path.is_file():
        try:
            state.config = load_lab_config(config_path)
            state.identity_store = IdentityStore(identity_path)
            state.needs_setup = False
        except Exception:
            state.needs_setup = True
    else:
        state.needs_setup = True

    def _main(page: ft.Page) -> None:
        FletAppController(page, state).start()

    ft.app(target=_main)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JidelnaLocalLite Flet UI")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--identity-store", type=Path, default=DEFAULT_IDENTITY)
    args = parser.parse_args(argv)
    run_app(config_path=args.config, identity_path=args.identity_store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
