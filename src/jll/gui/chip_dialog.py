"""Modální čtení čipu s omezeným timeoutem a zrušením.

Dialog používá stávající `ChipReader` abstrakci, takže stejné workflow platí
pro fyzickou serial čtečku i pro `FakeChipReader` v testech. Žádná varianta
nezapisuje do databáze.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..chip_reader import (
    ChipRead,
    ChipReader,
    ChipReaderCancelled,
    ChipReaderTimeout,
)
from . import theme
from .theme import TextRole

READER_PROMPT = "Přiložte čip ke čtečce…"
TIMEOUT_MESSAGE = "Čip nebyl v časovém limitu přiložen."
CANCELLED_MESSAGE = "Čtení bylo zrušeno."
UNEXPECTED_MESSAGE = "Čtečku se nepodařilo bezpečně použít."


def reader_error_text(error: BaseException) -> str:
    """Lidská česká hláška; SQL ani traceback se do GUI nedostane."""

    if isinstance(error, ChipReaderTimeout):
        return TIMEOUT_MESSAGE
    if isinstance(error, ChipReaderCancelled):
        return CANCELLED_MESSAGE
    message = str(error).strip()
    return message or UNEXPECTED_MESSAGE


class ChipReadDialog(QDialog):
    """Jedno bezpečné načtení čipu.

    Timeout je vždy konečný a `Zrušit` nastaví cancel event, takže čekání
    nikdy neběží neomezeně.
    """

    read_succeeded = Signal(object)
    read_failed = Signal(str)

    def __init__(
        self,
        reader: ChipReader,
        *,
        timeout_seconds: float = 10.0,
        title: str = "Načtení čipu",
        prompt: str = READER_PROMPT,
        parent: QWidget | None = None,
    ) -> None:
        # Validace předchází QDialog, aby při chybě nezůstal poloviční widget.
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Timeout čtení musí být v rozsahu (0, 30].")
        super().__init__(parent)
        self.reader = reader
        self.timeout_seconds = timeout_seconds
        self.chip_read: ChipRead | None = None
        self.error_message: str | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._cancel = threading.Event()
        self._started = False
        self._finished = False

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING["lg"],
            theme.SPACING["lg"],
            theme.SPACING["lg"],
            theme.SPACING["lg"],
        )
        layout.setSpacing(theme.SPACING["md"])
        self.prompt_label = QLabel(prompt)
        self.prompt_label.setWordWrap(True)
        theme.apply_role(self.prompt_label, TextRole.PRIMARY)
        layout.addWidget(self.prompt_label)
        self.detail_label = QLabel(
            f"Čekání skončí nejpozději za {int(timeout_seconds)} s."
        )
        self.detail_label.setWordWrap(True)
        theme.apply_role(self.detail_label, TextRole.META)
        layout.addWidget(self.detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Zrušit")
        theme.apply_role(self.cancel_button, TextRole.ACTION)
        self.cancel_button.setProperty("variant", "secondary")
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def start_read(self) -> None:
        """Spustí jedno čtení na pozadí; opakované volání je bez efektu."""

        if self._started:
            return
        self._started = True
        self._cancel.clear()
        reader = self.reader
        cancel = self._cancel
        timeout = self.timeout_seconds

        def operation() -> ChipRead:
            reader.start()
            return reader.read_once(
                timeout_seconds=timeout,
                cancel_event=cancel,
            )

        # Import je lokální, aby GUI modul nezávisel na pořadí importů.
        from .workers import FunctionWorker

        worker = FunctionWorker(1, operation)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self.thread_pool.start(worker)

    def cancel(self) -> None:
        """Zrušení i zavření po chybě; první doložený důvod se nepřepisuje."""

        self._cancel.set()
        if not self._finished:
            self._finished = True
            self.error_message = CANCELLED_MESSAGE
        self.reject()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.start_read()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._cancel.set()
        super().closeEvent(event)

    def _succeeded(
        self,
        _request_id: int,
        result: object,
        _duration_ms: float,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        if not isinstance(result, ChipRead):
            self._fail(UNEXPECTED_MESSAGE)
            return
        self.chip_read = result
        self.read_succeeded.emit(result)
        self.accept()

    def _failed(
        self,
        _request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        if isinstance(error, BaseException):
            self._fail(reader_error_text(error))
            return
        self._fail(UNEXPECTED_MESSAGE)

    def _fail(self, message: str) -> None:
        self.error_message = message
        self.prompt_label.setText(message)
        self.prompt_label.setProperty("tone", "danger")
        theme.repolish(self.prompt_label)
        self.detail_label.setText("Zavřete dialog a zkuste to znovu.")
        self.cancel_button.setText("Zavřít")
        self.read_failed.emit(message)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)
