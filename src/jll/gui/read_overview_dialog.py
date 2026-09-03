from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QThreadPool, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..read_models import DinerReportRow, OrderReportRow, PickupStatusRow
from ..read_service import OrderReadService
from . import theme
from .theme import TextRole
from .workers import FunctionWorker


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class _ReadDialog(QDialog):
    def __init__(
        self,
        title: str,
        service: OrderReadService,
        target: date,
        parent: QWidget | None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thread_pool = QThreadPool.globalInstance()
        self._generation = 0
        self.setWindowTitle(title)
        self.resize(820, 560)
        self.layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Datum:"))
        self.date_edit = QDateEdit(QDate(target.year, target.month, target.day))
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setCalendarPopup(True)
        controls.addWidget(self.date_edit)
        self.refresh_button = QPushButton("Načíst z LAB DB")
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        self.layout.addLayout(controls)
        self.status = QLabel("Připraveno.")
        self.layout.addWidget(self.status)

    def _run(self, operation) -> None:
        self._generation += 1
        request_id = self._generation
        self.refresh_button.setEnabled(False)
        self.status.setText("Načítám…")
        worker = FunctionWorker(request_id, operation)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        self.thread_pool.start(worker)

    def _succeeded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._generation:
            return
        self.refresh_button.setEnabled(True)
        self.status.setText(f"Načteno z LAB DB za {duration_ms:.0f} ms.")
        self.render(result)

    def _failed(
        self,
        request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        if request_id != self._generation:
            return
        self.refresh_button.setEnabled(True)
        self.status.setText(f"Načtení selhalo: {error}")

    def render(self, result: object) -> None:
        raise NotImplementedError


class PickupStatusPanel(QWidget):
    """Panely stavu výdeje s dominantní hodnotou ZBÝVÁ.

    `ZBÝVÁ` je hlavní provozní metrika, proto má největší typografickou roli
    z FÁZE 3C. Panel je pouze pro čtení; samotný výdej JLL neimplementuje.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[PickupStatusRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(theme.SPACING["sm"])
        self.empty_label = QLabel("Pro tento den nejsou žádné objednávky.")
        theme.apply_role(self.empty_label, TextRole.BODY)
        self._layout.addWidget(self.empty_label)
        self._layout.addStretch()

    def render(self, rows: list[PickupStatusRow]) -> None:
        self.rows = rows
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.empty_label:
                widget.setParent(None)
                widget.deleteLater()
        self.empty_label.setVisible(not rows)
        self._layout.addWidget(self.empty_label)
        for row in rows:
            self._layout.addWidget(self._row_panel(row))
        self._layout.addStretch()

    @staticmethod
    def _row_panel(row: PickupStatusRow) -> QWidget:
        panel = QFrame()
        panel.setObjectName("pickupRow")
        panel.setProperty("complete", "true" if row.remaining <= 0 else "false")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(
            theme.SPACING["lg"],
            theme.SPACING["md"],
            theme.SPACING["lg"],
            theme.SPACING["md"],
        )
        layout.setSpacing(theme.SPACING["xl"])
        identity = QVBoxLayout()
        identity.setSpacing(0)
        title = QLabel(f"{row.meal_type} · menu {row.menu}")
        theme.apply_role(title, TextRole.ACTION)
        identity.addWidget(title)
        counts = QLabel(
            f"Objednáno {row.ordered} · vydáno {row.picked_up}"
        )
        theme.apply_role(counts, TextRole.META)
        identity.addWidget(counts)
        layout.addLayout(identity)
        layout.addStretch()
        caption = QLabel("ZBÝVÁ")
        theme.apply_role(caption, TextRole.META)
        layout.addWidget(caption)
        remaining = QLabel(str(row.remaining))
        remaining.setObjectName("pickupRemaining")
        remaining.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        theme.apply_role(remaining, TextRole.PRIMARY)
        layout.addWidget(remaining)
        return panel


class PickupStatusDialog(_ReadDialog):
    def __init__(
        self,
        service: OrderReadService,
        target: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Stav výdeje – pouze pro čtení", service, target, parent)
        self.panel = PickupStatusPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.panel)
        self.layout.addWidget(scroll, 1)
        note = QLabel(
            "Read-only přehled ve scope provozovny. Výdej se v JLL neprovádí."
        )
        note.setWordWrap(True)
        theme.apply_role(note, TextRole.META)
        self.layout.addWidget(note)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        self.layout.addWidget(close)
        self.refresh_button.clicked.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        target = self.date_edit.date().toPython()
        self._run(lambda: self.service.load_pickup_status(target))

    def render(self, result: object) -> None:
        rows = [row for row in result if isinstance(row, PickupStatusRow)]
        self.panel.render(rows)


class ReportsDialog(_ReadDialog):
    def __init__(
        self,
        service: OrderReadService,
        target: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Sestavy – bezpečný náhled", service, target, parent)
        tabs = QTabWidget()
        self.orders = _table(["Typ stravy", "Menu", "Počet", "Jídlo"])
        self.diners = _table(["Jméno", "Kategorie", "Třída", "Evidenční číslo"])
        tabs.addTab(self.orders, "Přihlášky")
        tabs.addTab(self.diners, "Seznam strávníků")
        self.layout.addWidget(tabs)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        self.layout.addWidget(close)
        self.refresh_button.clicked.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        target = self.date_edit.date().toPython()
        self._run(
            lambda: (
                self.service.load_order_report(target),
                self.service.load_diner_report(),
            )
        )

    def render(self, result: object) -> None:
        order_rows, diner_rows = result  # type: ignore[misc]
        self._render_orders(list(order_rows))
        self._render_diners(list(diner_rows))

    def _render_orders(self, rows: list[OrderReportRow]) -> None:
        self.orders.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            for column, value in enumerate(
                (row.meal_type, row.menu, row.portions, row.meal_name or "—")
            ):
                self.orders.setItem(
                    row_number,
                    column,
                    QTableWidgetItem(str(value)),
                )

    def _render_diners(self, rows: list[DinerReportRow]) -> None:
        self.diners.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            for column, value in enumerate(
                (row.name, row.category, row.class_name, row.evidcislo)
            ):
                self.diners.setItem(
                    row_number,
                    column,
                    QTableWidgetItem(str(value)),
                )
