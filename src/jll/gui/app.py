from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from ..admin_service import AdminService
from ..application import OrderApplicationService
from ..chip_reader import SerialLineChipReader, UnavailableChipReader
from ..config import load_lab_config
from ..identity_store import IdentityStore
from ..orders.service import OrderService
from ..read_service import OrderReadService
from ..session import AuthService, SessionManager
from . import theme
from .login_dialog import LoginDialog
from .main_window import MainWindow
from .setup_wizard import SetupWizard
from .theme import TextRole

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "lab.json"
DEFAULT_IDENTITY = PROJECT_ROOT / "config" / "users.lab.json"
DEFAULT_LOG = PROJECT_ROOT / "logs" / "jll-lab.log"


def configure_logging(path: Path = DEFAULT_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


class BlockedWindow(QMainWindow):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.setWindowTitle("JidelnaLocalLite – LAB BLOKOVÁNO")
        self.resize(720, 260)
        root = QWidget()
        layout = QVBoxLayout(root)
        banner = QLabel("LAB – LOKÁLNÍ TESTOVACÍ DATABÁZE")
        banner.setProperty("tone", "labBanner")
        theme.apply_role(banner, TextRole.ACTION)
        layout.addWidget(banner)
        blocked = QLabel("APLIKACE JE BLOKOVÁNA")
        blocked.setProperty("tone", "danger")
        theme.apply_role(blocked, TextRole.PRIMARY)
        layout.addWidget(blocked)
        detail = QLabel(message)
        detail.setWordWrap(True)
        theme.apply_role(detail, TextRole.BODY)
        layout.addWidget(detail)
        layout.addStretch()
        self.setCentralWidget(root)


def build_window(
    config_path: Path,
    identity_path: Path,
    authenticated_user_id: str,
) -> MainWindow:
    config = load_lab_config(config_path)
    store = IdentityStore(identity_path)
    user = store.get_user(authenticated_user_id)
    if user is None or not user.active:
        raise RuntimeError("Přihlášený uživatel již není aktivní.")
    session = SessionManager(config, store)
    session.start(user)
    auth = AuthService(store)
    admin_service = AdminService(session, auth, store)
    pool = config.create_pool()
    try:
        read_service = OrderReadService(
            pool.connection,
            config.order_settings,
            session.current_policy,
            search_limit=config.search_limit,
        )
        order_service = OrderService(
            pool.connection,
            config.order_settings,
            session.scope_for_order,
        )
        application_service = OrderApplicationService(
            order_service,
            read_service,
            session.current_policy,
            session.current_actor,
        )
        chip_reader = (
            SerialLineChipReader(
                config.reader_port,
                baud_rate=config.reader_baud_rate,
                line_end=config.reader_line_end.encode("ascii"),
            )
            if config.reader_port
            else UnavailableChipReader(
                "Fyzická čtečka není nakonfigurována ani hardwarově ověřena."
            )
        )
        window = MainWindow(
            config,
            read_service,
            application_service,
            session,
            admin_service,
            chip_reader,
        )
        window.connection_pool = pool
        return window
    except Exception:
        pool.close()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JLL PySide6 LAB GUI")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--identity-store", type=Path, default=DEFAULT_IDENTITY)
    args = parser.parse_args(argv)
    configure_logging()
    logging.getLogger(__name__).info("JLL LAB GUI start")
    app = QApplication(sys.argv[:1])
    theme.apply_theme(app)
    config_path = args.config.resolve()
    identity_path = args.identity_store.resolve()
    try:
        try:
            config = load_lab_config(config_path)
        except Exception:
            config = None
        store = IdentityStore(identity_path)
        if config is None and store.exists:
            raise RuntimeError(
                "Konfigurace je neplatná, ale identity již existují. "
                "Automatický setup je z bezpečnostních důvodů blokován."
            )
        if config is None or not store.exists:
            wizard = SetupWizard(config_path, identity_path, config)
            if wizard.exec() != QDialog.Accepted:
                return 0
            config = load_lab_config(config_path)
            store = IdentityStore(identity_path)
        auth = AuthService(store)
        login = LoginDialog(config, auth)
        if login.exec() != QDialog.Accepted or login.selected_user is None:
            return 0
        window: QMainWindow = build_window(
            config_path,
            identity_path,
            login.selected_user.user_id,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "LAB config startup blocked error=%s", type(exc).__name__
        )
        window = BlockedWindow(
            "LAB konfiguraci nelze bezpečně načíst. "
            "Opravte config/lab.json a aplikaci spusťte znovu."
        )
    window.show()
    if isinstance(window, MainWindow):
        app.aboutToQuit.connect(window.connection_pool.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
