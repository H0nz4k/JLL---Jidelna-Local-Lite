from __future__ import annotations

import json
import threading

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..admin_service import AdminService
from ..chip_reader import ChipReader, masked_chip_summary
from ..config import LabConfig
from ..identity_store import UserRecord
from ..policy import Permission
from . import theme
from .theme import TextRole
from .workers import FunctionWorker


class NewUserDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nový JLL uživatel")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.display_name = QLineEdit()
        self.user_id = QLineEdit()
        self.short_code = QLineEdit()
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        form.addRow("Jméno:", self.display_name)
        form.addRow("User ID:", self.user_id)
        form.addRow("Krátký kód:", self.short_code)
        form.addRow("PIN:", self.pin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AdminDialog(QDialog):
    policy_changed = Signal()

    def __init__(
        self,
        config: LabConfig,
        service: AdminService,
        reader: ChipReader | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.service = service
        self.reader = reader
        self.thread_pool = QThreadPool.globalInstance()
        self._reader_cancel = threading.Event()
        self.setWindowTitle("JidelnaLocalLite – Administrace")
        self.resize(760, 540)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "LAB administrace · změny uživatelů a oprávnění se auditují lokálně"
        )
        warning.setProperty("tone", "danger")
        theme.apply_role(warning, TextRole.ACTION)
        layout.addWidget(warning)
        tabs = QTabWidget()
        tabs.addTab(self._instance_tab(), "Provozovna")
        tabs.addTab(self._database_tab(), "Databáze")
        tabs.addTab(self._categories_tab(), "Kategorie")
        tabs.addTab(self._users_tab(), "Uživatelé a oprávnění")
        tabs.addTab(self._reader_tab(), "Čtečka")
        tabs.addTab(self._audit_tab(), "Audit")
        layout.addWidget(tabs)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _readonly_form(self, rows: list[tuple[str, str]]) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        for label, value in rows:
            field = QLineEdit(value)
            field.setReadOnly(True)
            form.addRow(label, field)
        return widget

    def _instance_tab(self) -> QWidget:
        return self._readonly_form(
            [
                ("Provozovna:", self.config.site_name),
                ("Site ID:", self.config.site_id),
                ("Instance ID:", self.config.instance_id),
                ("Stav:", "Změny vyžadují samostatný ověřený workflow"),
            ]
        )

    def _database_tab(self) -> QWidget:
        return self._readonly_form(
            [
                ("Host:", self.config.host),
                ("Port:", str(self.config.port)),
                ("Databáze:", self.config.database),
                ("DB účet:", self.config.user),
                ("Heslo:", "uloženo mimo konfiguraci / nezobrazuje se"),
                ("Stav:", "Změna DB v této fázi není povolena"),
            ]
        )

    def _categories_tab(self) -> QWidget:
        return self._readonly_form(
            [
                (
                    "Povolené kategorie:",
                    ", ".join(sorted(self.config.allowed_categories)),
                ),
                (
                    "Stav:",
                    "Rozšíření scope vyžaduje znovu ověřit DB a instalační policy",
                ),
            ]
        )

    def _users_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        body = QHBoxLayout()
        self.users = QListWidget()
        self.users.currentItemChanged.connect(self._user_selected)
        body.addWidget(self.users, 1)
        right = QVBoxLayout()
        self.active = QCheckBox("Aktivní uživatel")
        right.addWidget(self.active)
        right.addWidget(QLabel("Konkrétní oprávnění:"))
        self.permissions = QListWidget()
        for permission in Permission:
            item = QListWidgetItem(permission.value)
            item.setData(Qt.UserRole, permission)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.permissions.addItem(item)
        right.addWidget(self.permissions, 1)
        self.save_access = QPushButton("Uložit přístup")
        self.save_access.clicked.connect(self._save_user_access)
        right.addWidget(self.save_access)
        body.addLayout(right, 2)
        layout.addLayout(body)
        add_user = QPushButton("+ Nový JLL uživatel")
        add_user.clicked.connect(self._add_user)
        layout.addWidget(add_user)
        self._reload_users()
        return widget

    def _audit_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        audit = QTextEdit()
        audit.setReadOnly(True)
        try:
            events = self.service.audit_events()
            audit.setPlainText(
                "\n".join(
                    json.dumps(event, ensure_ascii=False, sort_keys=True)
                    for event in events
                )
            )
        except Exception as exc:
            audit.setPlainText(f"Audit není dostupný: {exc}")
        layout.addWidget(audit)
        return widget

    def _reader_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        if self.reader is None:
            layout.addRow("Stav:", QLabel("Čtečka není nakonfigurována."))
            return widget
        status = self.reader.status()
        info = self.reader.device_info()
        self.reader_status = QLabel(f"{status.state.value}: {status.message}")
        self.reader_device = QLabel(
            " / ".join(
                part
                for part in (
                    info.adapter,
                    info.port,
                    info.manufacturer,
                    info.product,
                )
                if part
            )
        )
        self.reader_last = QLabel(masked_chip_summary(None))
        self.reader_test_button = QPushButton("Test načtení čipu")
        self.reader_test_button.clicked.connect(self._test_reader)
        layout.addRow("Stav:", self.reader_status)
        layout.addRow("Zařízení:", self.reader_device)
        layout.addRow("Poslední načtení:", self.reader_last)
        layout.addRow("", self.reader_test_button)
        return widget

    def _test_reader(self) -> None:
        if self.reader is None:
            return
        try:
            self.service.require_reader_diagnostics()
        except Exception as exc:
            QMessageBox.warning(self, "Diagnostika není dostupná", str(exc))
            return
        self._reader_cancel.clear()
        self.reader_test_button.setEnabled(False)
        self.reader_status.setText("Čekám na čip (max. 10 s)…")

        def operation():
            assert self.reader is not None
            self.reader.start()
            return self.reader.read_once(
                timeout_seconds=10,
                cancel_event=self._reader_cancel,
            )

        worker = FunctionWorker(1, operation)
        worker.signals.succeeded.connect(self._reader_succeeded)
        worker.signals.failed.connect(self._reader_failed)
        self.thread_pool.start(worker)

    def _reader_succeeded(
        self,
        _request_id: int,
        result: object,
        _duration_ms: float,
    ) -> None:
        self.reader_test_button.setEnabled(True)
        code = getattr(result, "code", None)
        self.reader_last.setText(masked_chip_summary(code))
        self.reader_status.setText("Načtení proběhlo.")

    def _reader_failed(
        self,
        _request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        self.reader_test_button.setEnabled(True)
        self.reader_status.setText(f"Test selhal: {error}")

    def closeEvent(self, event) -> None:
        self._reader_cancel.set()
        if self.reader is not None:
            self.reader.stop()
        super().closeEvent(event)

    def _reload_users(self) -> None:
        selected_id = (
            self.users.currentItem().data(Qt.UserRole)
            if self.users.currentItem()
            else None
        )
        self.users.clear()
        for user in self.service.list_users():
            item = QListWidgetItem(
                f"{user.display_name} ({user.short_code})"
                + ("" if user.active else " – neaktivní")
            )
            item.setData(Qt.UserRole, user)
            self.users.addItem(item)
            if user.user_id == selected_id:
                self.users.setCurrentItem(item)
        if self.users.count() and self.users.currentRow() < 0:
            self.users.setCurrentRow(0)

    def _user_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        user = current.data(Qt.UserRole)
        if not isinstance(user, UserRecord):
            return
        self.active.setChecked(user.active)
        for index in range(self.permissions.count()):
            item = self.permissions.item(index)
            item.setCheckState(
                Qt.Checked
                if item.data(Qt.UserRole) in user.permissions
                else Qt.Unchecked
            )

    def _selected_permissions(self) -> frozenset[Permission]:
        return frozenset(
            self.permissions.item(index).data(Qt.UserRole)
            for index in range(self.permissions.count())
            if self.permissions.item(index).checkState() == Qt.Checked
        )

    def _save_user_access(self) -> None:
        current = self.users.currentItem()
        if current is None:
            return
        user = current.data(Qt.UserRole)
        try:
            self.service.update_access(
                user.user_id,
                self._selected_permissions(),
                self.active.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Změnu nelze uložit", str(exc))
            return
        self.policy_changed.emit()
        self._reload_users()

    def _add_user(self) -> None:
        dialog = NewUserDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        default_permissions = frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.CHIPS_VIEW,
                Permission.ORDERS_VIEW,
            }
        )
        try:
            self.service.add_user(
                user_id=dialog.user_id.text().strip(),
                display_name=dialog.display_name.text().strip(),
                short_code=dialog.short_code.text().strip(),
                pin=dialog.pin.text(),
                permissions=default_permissions,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Uživatele nelze vytvořit", str(exc))
            return
        self.policy_changed.emit()
        self._reload_users()
