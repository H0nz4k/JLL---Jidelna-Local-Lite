from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..config import LabConfig
from ..identity_store import UserRecord
from ..session import AuthService
from . import theme
from .theme import TextRole
from .workers import FunctionWorker


class LoginDialog(QDialog):
    def __init__(self, config: LabConfig, auth: AuthService) -> None:
        super().__init__()
        self.config = config
        self.auth = auth
        self.thread_pool = QThreadPool.globalInstance()
        self.selected_user: UserRecord | None = None
        self.setWindowTitle(f"JidelnaLocalLite – {config.site_name}")
        self.setModal(True)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        title = QLabel(config.site_name)
        theme.apply_role(title, TextRole.PRIMARY)
        layout.addWidget(title)
        subtitle = QLabel("Přihlášení do JidelnaLocalLite")
        theme.apply_role(subtitle, TextRole.BODY)
        layout.addWidget(subtitle)
        form = QFormLayout()
        self.user_combo = QComboBox()
        for user in auth.store.list_users(active_only=True):
            self.user_combo.addItem(
                f"{user.display_name} ({user.short_code})",
                user.user_id,
            )
        self.pin_edit = QLineEdit()
        self.pin_edit.setEchoMode(QLineEdit.Password)
        self.pin_edit.setPlaceholderText("PIN")
        self.pin_edit.returnPressed.connect(self._authenticate)
        form.addRow("Uživatel:", self.user_combo)
        form.addRow("PIN:", self.pin_edit)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setProperty("tone", "danger")
        theme.apply_role(self.error_label, TextRole.META)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.login_button = QPushButton("Přihlásit")
        theme.apply_role(self.login_button, TextRole.ACTION)
        self.login_button.setProperty("variant", "primary")
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self._authenticate)
        layout.addWidget(self.login_button, alignment=Qt.AlignRight)

    def _authenticate(self) -> None:
        user_id = self.user_combo.currentData()
        pin = self.pin_edit.text()
        if not user_id or not pin:
            self.error_label.setText("Vyberte uživatele a zadejte PIN.")
            return
        self.login_button.setEnabled(False)
        self.user_combo.setEnabled(False)
        self.pin_edit.setEnabled(False)
        self.error_label.setText("Ověřuji…")
        worker = FunctionWorker(
            1,
            lambda: self.auth.authenticate(str(user_id), pin),
        )
        worker.signals.succeeded.connect(self._authenticated)
        worker.signals.failed.connect(self._authentication_failed)
        self.thread_pool.start(worker)

    def _authenticated(
        self,
        _request_id: int,
        result: object,
        _duration_ms: float,
    ) -> None:
        if not isinstance(result, UserRecord):
            self._authentication_failed(1, Exception(), 0)
            return
        self.selected_user = result
        self.accept()

    def _authentication_failed(
        self,
        _request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        self.login_button.setEnabled(True)
        self.user_combo.setEnabled(True)
        self.pin_edit.setEnabled(True)
        self.pin_edit.clear()
        self.pin_edit.setFocus()
        self.error_label.setText(str(error) or "Přihlášení selhalo.")
