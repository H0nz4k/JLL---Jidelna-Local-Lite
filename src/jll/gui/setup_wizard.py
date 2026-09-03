from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

import keyring
import psycopg
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..config import LabConfig, save_lab_config
from ..identity import IDENTIFIER_PATTERN
from ..identity_store import IdentityStore
from ..policy import Permission
from .workers import FunctionWorker


@dataclass(frozen=True, slots=True)
class DatabaseProbe:
    system_identifier: str
    categories: tuple[str, ...]


class SetupWizard(QWizard):
    PAGE_DATABASE = 0
    PAGE_INSTANCE = 1
    PAGE_CATEGORIES = 2
    PAGE_ADMIN = 3
    PAGE_USERS = 4
    PAGE_PERMISSIONS = 5
    PAGE_SUMMARY = 6

    def __init__(
        self,
        config_path: Path,
        identity_path: Path,
        initial_config: LabConfig | None = None,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.identity_path = identity_path
        self.initial_config = initial_config
        self.thread_pool = QThreadPool.globalInstance()
        self.database_probe: DatabaseProbe | None = None
        self._pending_database_values: tuple[str, str, str, str, str] | None = None
        self.setWindowTitle("JidelnaLocalLite – první nastavení")
        self.setWizardStyle(QWizard.ModernStyle)
        self.resize(650, 520)
        self._database_page()
        self._instance_page()
        self._categories_page()
        self._admin_page()
        self._users_page()
        self._permissions_page()
        self._summary_page()
        self.currentIdChanged.connect(self._page_changed)

    @staticmethod
    def _page(title: str, description: str) -> tuple[QWizardPage, QVBoxLayout]:
        page = QWizardPage()
        page.setTitle(title)
        page.setSubTitle(description)
        return page, QVBoxLayout(page)

    def _database_page(self) -> None:
        page, layout = self._page(
            "1. Databáze",
            "Pouze lokální LAB databáze. Heslo nebude uloženo do JSON.",
        )
        form = QFormLayout()
        initial = self.initial_config
        self.db_host = QLineEdit(initial.host if initial else "127.0.0.1")
        self.db_port = QLineEdit(str(initial.port if initial else 5433))
        self.db_name = QLineEdit(initial.database if initial else "jll_demo_lab")
        self.db_user = QLineEdit(initial.user if initial else "postgres")
        self.db_password = QLineEdit()
        self.db_password.setEchoMode(QLineEdit.Password)
        self.db_password.setPlaceholderText(
            "Prázdné = environment/keyring/PG auth"
        )
        form.addRow("Host:", self.db_host)
        form.addRow("Port:", self.db_port)
        form.addRow("Databáze:", self.db_name)
        form.addRow("DB uživatel:", self.db_user)
        form.addRow("DB heslo:", self.db_password)
        layout.addLayout(form)
        self.test_database_button = QPushButton("Otestovat spojení")
        self.test_database_button.clicked.connect(self._test_database)
        layout.addWidget(self.test_database_button)
        self.database_status = QLabel("Spojení zatím nebylo ověřeno.")
        self.database_status.setWordWrap(True)
        layout.addWidget(self.database_status)
        layout.addStretch()
        for field in (
            self.db_host,
            self.db_port,
            self.db_name,
            self.db_user,
            self.db_password,
        ):
            field.textChanged.connect(self._invalidate_database_probe)
        self.addPage(page)

    def _instance_page(self) -> None:
        page, layout = self._page(
            "2. Provozovna / instance",
            "Stabilní identita této instalace pro audit.",
        )
        form = QFormLayout()
        initial = self.initial_config
        self.site_name = QLineEdit(initial.site_name if initial else "DEMO LAB")
        self.site_id = QLineEdit(initial.site_id if initial else "DEMO")
        self.instance_id = QLineEdit(
            initial.instance_id if initial else "DEMO-LAB01"
        )
        form.addRow("Název provozovny:", self.site_name)
        form.addRow("Site ID:", self.site_id)
        form.addRow("Instance ID:", self.instance_id)
        layout.addLayout(form)
        layout.addStretch()
        self.addPage(page)

    def _categories_page(self) -> None:
        page, layout = self._page(
            "3. Povolené kategorie",
            "Vyberte instalační scope. Prázdný scope je zakázán.",
        )
        self.categories = QListWidget()
        layout.addWidget(self.categories)
        self.addPage(page)

    def _admin_page(self) -> None:
        page, layout = self._page(
            "4. První administrátor",
            "PIN je uložen pouze jako salted Argon2id hash.",
        )
        form = QFormLayout()
        self.admin_name = QLineEdit()
        self.admin_id = QLineEdit()
        self.admin_short_code = QLineEdit()
        self.admin_pin = QLineEdit()
        self.admin_pin_confirm = QLineEdit()
        for field in (self.admin_pin, self.admin_pin_confirm):
            field.setEchoMode(QLineEdit.Password)
        form.addRow("Jméno:", self.admin_name)
        form.addRow("User ID:", self.admin_id)
        form.addRow("Krátký kód:", self.admin_short_code)
        form.addRow("PIN:", self.admin_pin)
        form.addRow("PIN znovu:", self.admin_pin_confirm)
        layout.addLayout(form)
        layout.addStretch()
        self.addPage(page)

    def _users_page(self) -> None:
        page, layout = self._page(
            "5. Uživatelé",
            "Volitelně vytvořte prvního běžného uživatele.",
        )
        self.create_regular_user = QCheckBox("Vytvořit běžného uživatele")
        layout.addWidget(self.create_regular_user)
        form = QFormLayout()
        self.user_name = QLineEdit()
        self.user_id = QLineEdit()
        self.user_short_code = QLineEdit()
        self.user_pin = QLineEdit()
        self.user_pin.setEchoMode(QLineEdit.Password)
        form.addRow("Jméno:", self.user_name)
        form.addRow("User ID:", self.user_id)
        form.addRow("Krátký kód:", self.user_short_code)
        form.addRow("PIN:", self.user_pin)
        layout.addLayout(form)
        self.create_regular_user.toggled.connect(
            lambda enabled: [
                widget.setEnabled(enabled)
                for widget in (
                    self.user_name,
                    self.user_id,
                    self.user_short_code,
                    self.user_pin,
                )
            ]
        )
        self.create_regular_user.setChecked(False)
        for widget in (
            self.user_name,
            self.user_id,
            self.user_short_code,
            self.user_pin,
        ):
            widget.setEnabled(False)
        layout.addStretch()
        self.addPage(page)

    def _permissions_page(self) -> None:
        page, layout = self._page(
            "6. Oprávnění",
            "Administrátor získá admin permissions. Zde nastavte běžného uživatele.",
        )
        self.permission_list = QListWidget()
        default_permissions = {
            Permission.DINERS_VIEW,
            Permission.CHIPS_VIEW,
            Permission.ORDERS_VIEW,
            Permission.ORDERS_CHANGE,
        }
        for permission in Permission:
            if permission.value.startswith("admin."):
                continue
            item = QListWidgetItem(permission.value)
            item.setData(Qt.UserRole, permission)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if permission in default_permissions else Qt.Unchecked
            )
            self.permission_list.addItem(item)
        layout.addWidget(self.permission_list)
        self.addPage(page)

    def _summary_page(self) -> None:
        page, layout = self._page(
            "7. Souhrn",
            "Potvrzením se setup uloží atomicky. Produkční DB není povolena.",
        )
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addStretch()
        self.addPage(page)

    def _invalidate_database_probe(self) -> None:
        self.database_probe = None
        self.database_status.setText("Spojení zatím nebylo ověřeno.")

    def _test_database(self) -> None:
        self.test_database_button.setEnabled(False)
        self.database_status.setText("Ověřuji lokální LAB databázi…")
        values = (
            self.db_host.text().strip(),
            self.db_port.text().strip(),
            self.db_name.text().strip(),
            self.db_user.text().strip(),
            self.db_password.text(),
        )
        self._pending_database_values = values
        worker = FunctionWorker(1, lambda: self._probe_database(values))
        worker.signals.succeeded.connect(self._database_verified)
        worker.signals.failed.connect(self._database_failed)
        self.thread_pool.start(worker)

    @staticmethod
    def _probe_database(
        values: tuple[str, str, str, str, str],
    ) -> DatabaseProbe:
        raw_host, raw_port, database, user, password = values
        host = raw_host.lower().strip("[]")
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Setup povoluje pouze loopback host.")
        if not database.startswith("jll_"):
            raise ValueError("LAB databáze musí začínat jll_.")
        parameters: dict[str, object] = {
            "host": host,
            "port": int(raw_port),
            "dbname": database,
            "user": user,
            "connect_timeout": 5,
            "autocommit": True,
        }
        if password:
            parameters["password"] = password
        with psycopg.connect(**parameters) as connection:
            identity = connection.execute(
                """
                SELECT current_database(), host(inet_server_addr()),
                       (SELECT system_identifier::text FROM pg_control_system())
                """
            ).fetchone()
            if identity is None:
                raise ValueError("Identitu databáze nelze načíst.")
            if (
                identity[0] != database
                or not ipaddress.ip_address(identity[1]).is_loopback
            ):
                raise ValueError("Připojená databáze není lokální LAB.")
            rows = connection.execute(
                """
                SELECT DISTINCT btrim(kategorie)
                FROM public.stravnik
                WHERE stav = 'A' AND COALESCE(deleted, false) = false
                  AND kategorie IS NOT NULL
                ORDER BY btrim(kategorie)
                """
            ).fetchall()
        categories = tuple(str(row[0]) for row in rows if str(row[0]).strip())
        if not categories:
            raise ValueError("Databáze neobsahuje volitelné kategorie.")
        return DatabaseProbe(str(identity[2]), categories)

    def _database_verified(
        self,
        _request_id: int,
        result: object,
        _duration_ms: float,
    ) -> None:
        self.test_database_button.setEnabled(True)
        if not isinstance(result, DatabaseProbe):
            return
        current_values = (
            self.db_host.text().strip(),
            self.db_port.text().strip(),
            self.db_name.text().strip(),
            self.db_user.text().strip(),
            self.db_password.text(),
        )
        if current_values != self._pending_database_values:
            self.database_status.setText("Údaje se změnily; otestujte spojení znovu.")
            return
        self.database_probe = result
        self.database_status.setText(
            f"LAB databáze ověřena. System ID: {result.system_identifier[:8]}…"
        )
        self.categories.clear()
        selected = self.initial_config.allowed_categories if self.initial_config else set()
        for category in result.categories:
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if category in selected else Qt.Unchecked)
            self.categories.addItem(item)

    def _database_failed(
        self,
        _request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        self.test_database_button.setEnabled(True)
        self.database_probe = None
        self.database_status.setText("Ověření selhalo.")
        QMessageBox.warning(self, "Databázi nelze ověřit", str(error))

    def selected_categories(self) -> frozenset[str]:
        return frozenset(
            self.categories.item(index).text()
            for index in range(self.categories.count())
            if self.categories.item(index).checkState() == Qt.Checked
        )

    def selected_permissions(self) -> frozenset[Permission]:
        return frozenset(
            self.permission_list.item(index).data(Qt.UserRole)
            for index in range(self.permission_list.count())
            if self.permission_list.item(index).checkState() == Qt.Checked
        )

    def validateCurrentPage(self) -> bool:
        page_id = self.currentId()
        try:
            if page_id == self.PAGE_DATABASE and self.database_probe is None:
                raise ValueError("Nejprve úspěšně otestujte databázi.")
            if page_id == self.PAGE_INSTANCE:
                if not self.site_name.text().strip():
                    raise ValueError("Název provozovny nesmí být prázdný.")
                for value in (self.site_id.text(), self.instance_id.text()):
                    if not IDENTIFIER_PATTERN.fullmatch(value.strip()):
                        raise ValueError("Site ID a instance ID nemají platný formát.")
            elif page_id == self.PAGE_CATEGORIES and not self.selected_categories():
                raise ValueError("Vyberte alespoň jednu povolenou kategorii.")
            elif page_id == self.PAGE_ADMIN:
                if self.admin_pin.text() != self.admin_pin_confirm.text():
                    raise ValueError("PIN administrátora se neshoduje.")
                self._validate_user_fields(
                    self.admin_id.text(),
                    self.admin_name.text(),
                    self.admin_short_code.text(),
                    self.admin_pin.text(),
                )
            elif page_id == self.PAGE_USERS and self.create_regular_user.isChecked():
                self._validate_user_fields(
                    self.user_id.text(),
                    self.user_name.text(),
                    self.user_short_code.text(),
                    self.user_pin.text(),
                )
            elif page_id == self.PAGE_SUMMARY:
                self._complete_setup()
        except Exception as exc:
            QMessageBox.warning(self, "Nastavení nelze dokončit", str(exc))
            return False
        return super().validateCurrentPage()

    @staticmethod
    def _validate_user_fields(
        user_id: str,
        name: str,
        short_code: str,
        pin: str,
    ) -> None:
        if not user_id.strip() or not name.strip() or not short_code.strip():
            raise ValueError("Vyplňte identitu uživatele.")
        if len(pin) < 4:
            raise ValueError("PIN musí mít alespoň 4 znaky.")

    def _build_config(self) -> LabConfig:
        if self.database_probe is None:
            raise ValueError("Databáze není ověřena.")
        return LabConfig(
            site_name=self.site_name.text().strip(),
            site_id=self.site_id.text().strip().upper(),
            instance_id=self.instance_id.text().strip().upper(),
            allowed_categories=self.selected_categories()
            or (
                self.initial_config.allowed_categories
                if self.initial_config
                else frozenset()
            ),
            host=self.db_host.text().strip(),
            port=int(self.db_port.text()),
            database=self.db_name.text().strip(),
            user=self.db_user.text().strip(),
            environment="lab",
            expected_system_identifier=self.database_probe.system_identifier,
            business_timezone="Europe/Prague",
            strict_config_lock=True,
            search_limit=30,
        )

    def _page_changed(self, page_id: int) -> None:
        if page_id != self.PAGE_SUMMARY:
            return
        regular = (
            self.user_name.text().strip()
            if self.create_regular_user.isChecked()
            else "nevytváří se"
        )
        self.summary.setText(
            f"Databáze: {self.db_host.text()}:{self.db_port.text()}/"
            f"{self.db_name.text()}\n"
            f"Provozovna: {self.site_name.text()} ({self.instance_id.text()})\n"
            f"Kategorie: {', '.join(sorted(self.selected_categories()))}\n"
            f"Admin: {self.admin_name.text()} ({self.admin_short_code.text()})\n"
            f"Běžný uživatel: {regular}"
        )

    def _complete_setup(self) -> None:
        config = self._build_config()
        password = self.db_password.text()
        if password:
            keyring.set_password(
                "JidelnaLocalLite",
                f"{config.instance_id}:{config.user}",
                password,
            )
        admin_permissions = frozenset(Permission)
        users = [
            (
                self.admin_id.text().strip(),
                self.admin_name.text().strip(),
                self.admin_short_code.text().strip().upper(),
                self.admin_pin.text(),
                admin_permissions,
            )
        ]
        if self.create_regular_user.isChecked():
            users.append(
                (
                    self.user_id.text().strip(),
                    self.user_name.text().strip(),
                    self.user_short_code.text().strip().upper(),
                    self.user_pin.text(),
                    self.selected_permissions(),
                )
            )
        IdentityStore(self.identity_path).initialize(
            users,
            actor=f"{config.instance_id}:SETUP",
        )
        save_lab_config(config, self.config_path)
