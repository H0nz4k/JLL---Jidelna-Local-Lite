from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from ..chip_reader import (
    ChipReader,
    ReaderState,
    available_serial_ports,
    masked_chip_summary,
)
from ..config import LabConfig
from ..identity_store import UserRecord
from ..policy import Permission
from . import theme
from .chip_dialog import ChipReadDialog
from .theme import TextRole

#: Nabídka běžných rychlostí; výchozí 19 200 odpovídá doložené referenci.
BAUD_RATES: tuple[int, ...] = (9_600, 19_200, 38_400, 57_600, 115_200)

LINE_ENDS: tuple[tuple[str, str], ...] = (
    ("CR (\\r)", "\r"),
    ("LF (\\n)", "\n"),
    ("CRLF (\\r\\n)", "\r\n"),
)

READER_STATE_LABELS: dict[ReaderState, str] = {
    ReaderState.READY: "Připojena",
    ReaderState.READING: "Připojena – probíhá čtení",
    ReaderState.STOPPED: "Nepřipojena",
    ReaderState.DISCONNECTED: "Nepřipojena",
    ReaderState.ERROR: "Chyba",
}


def reader_state_label(state: ReaderState) -> str:
    return READER_STATE_LABELS.get(state, "Neznámý stav")


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
    reader_config_changed = Signal(object)

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
        """Administrace čtečky: stav, COM port, protokol a test.

        Port se nikdy nevybírá automaticky, protože model čtečky není
        autoritativně doložený. Uživatel jej volí ručně z OS enumerace.
        """

        widget = QWidget()
        layout = QVBoxLayout(widget)
        form_host = QWidget()
        layout_form = QFormLayout(form_host)

        self.reader_status = QLabel("—")
        theme.apply_role(self.reader_status, TextRole.ACTION)
        self.reader_device = QLabel("—")
        theme.apply_role(self.reader_device, TextRole.META)
        self.reader_last = QLabel(masked_chip_summary(None))
        theme.apply_role(self.reader_last, TextRole.META)

        self.reader_port = QComboBox()
        self.reader_port.setToolTip(
            "COM porty podle enumerace operačního systému."
        )
        self.reader_baud = QComboBox()
        for value in BAUD_RATES:
            self.reader_baud.addItem(str(value), value)
        if self.config.reader_baud_rate not in BAUD_RATES:
            self.reader_baud.addItem(
                str(self.config.reader_baud_rate),
                self.config.reader_baud_rate,
            )
        self.reader_baud.setCurrentIndex(
            self.reader_baud.findData(self.config.reader_baud_rate)
        )
        self.reader_line_end = QComboBox()
        for label, value in LINE_ENDS:
            self.reader_line_end.addItem(label, value)
        self.reader_line_end.setCurrentIndex(
            max(0, self.reader_line_end.findData(self.config.reader_line_end))
        )
        self.reader_line_end.setToolTip(
            "Ukončení zprávy čtečky. Výchozí CR odpovídá referenčnímu protokolu."
        )

        layout_form.addRow("Stav:", self.reader_status)
        layout_form.addRow("Zařízení:", self.reader_device)
        layout_form.addRow("Port:", self.reader_port)
        layout_form.addRow("Baudrate:", self.reader_baud)
        layout_form.addRow("Ukončení zprávy:", self.reader_line_end)
        layout_form.addRow("Poslední načtení:", self.reader_last)
        layout.addWidget(form_host)

        actions = QHBoxLayout()
        self.reader_refresh_button = QPushButton("Obnovit porty a stav")
        self.reader_refresh_button.clicked.connect(self._refresh_reader_view)
        actions.addWidget(self.reader_refresh_button)
        self.reader_save_button = QPushButton("Uložit nastavení čtečky")
        theme.apply_role(self.reader_save_button, TextRole.ACTION)
        self.reader_save_button.setProperty("variant", "primary")
        self.reader_save_button.clicked.connect(self._save_reader_settings)
        self.reader_save_button.setEnabled(self.service.reader_settings_writable)
        if not self.service.reader_settings_writable:
            self.reader_save_button.setToolTip(
                "Instalační konfigurace není dostupná, nastavení nelze uložit."
            )
        actions.addWidget(self.reader_save_button)
        self.reader_test_button = QPushButton("Test čtečky")
        self.reader_test_button.clicked.connect(self._test_reader)
        actions.addWidget(self.reader_test_button)
        actions.addStretch()
        layout.addLayout(actions)

        note = QLabel(
            "Nastavení čtečky se ukládá pouze do lokální instalační "
            "konfigurace. Nemění databázi a vyžaduje oprávnění "
            "admin.reader i opětovné zadání PINu."
        )
        note.setWordWrap(True)
        theme.apply_role(note, TextRole.META)
        layout.addWidget(note)
        layout.addStretch()
        self._refresh_reader_view()
        return widget

    def _refresh_reader_view(self) -> None:
        """Znovu načte COM porty a aktuální stav čtečky."""

        selected = self.reader_port.currentData()
        target = selected or self.config.reader_port
        self.reader_port.clear()
        self.reader_port.addItem("(nenastaveno)", None)
        known = set()
        for option in available_serial_ports():
            self.reader_port.addItem(option.label, option.device)
            known.add(option.device)
        if target and target not in known:
            self.reader_port.addItem(
                f"{target} — nyní nedostupný",
                target,
            )
        index = self.reader_port.findData(target) if target else 0
        self.reader_port.setCurrentIndex(max(0, index))

        if self.reader is None:
            self.reader_status.setText("Čtečka není nakonfigurována.")
            self.reader_device.setText("—")
            self.reader_test_button.setEnabled(False)
            return
        status = self.reader.status()
        self.reader_status.setText(
            f"{reader_state_label(status.state)} — {status.message}"
        )
        info = self.reader.device_info()
        self.reader_device.setText(
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
            or "—"
        )
        self.reader_test_button.setEnabled(True)

    def _save_reader_settings(self) -> None:
        try:
            updated = self.service.save_reader_settings(
                port=self.reader_port.currentData(),
                baud_rate=int(self.reader_baud.currentData()),
                line_end=str(self.reader_line_end.currentData()),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Nastavení nelze uložit", str(exc))
            return
        self.config = updated
        self.reader_config_changed.emit(updated)
        QMessageBox.information(
            self,
            "Nastavení čtečky uloženo",
            "Nové nastavení se použije pro další čtení.",
        )
        self._refresh_reader_view()

    def _test_reader(self) -> None:
        if self.reader is None:
            return
        try:
            self.service.require_reader_diagnostics()
        except Exception as exc:
            QMessageBox.warning(self, "Diagnostika není dostupná", str(exc))
            return
        dialog = ChipReadDialog(
            self.reader,
            timeout_seconds=10,
            title="Test čtečky",
            parent=self,
        )
        accepted = dialog.exec() == QDialog.Accepted
        if accepted and dialog.chip_read is not None:
            self.reader_last.setText(
                masked_chip_summary(dialog.chip_read.code)
            )
            self.reader_status.setText("Načtení proběhlo.")
        elif dialog.error_message:
            self.reader_status.setText(f"Test selhal: {dialog.error_message}")
        self._refresh_reader_view()

    def closeEvent(self, event) -> None:
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
