from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..read_models import DinerReportRow, OrderReportRow, PickupStatusRow
from ..read_service import OrderReadService
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


class PickupStatusDialog(_ReadDialog):
    def __init__(
        self,
        service: OrderReadService,
        target: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Stav výdeje – pouze pro čtení", service, target, parent)
        self.table = _table(
            ["Typ stravy", "Menu", "Objednáno", "Vydáno", "Zbývá"]
        )
        self.layout.addWidget(self.table)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        self.layout.addWidget(close)
        self.refresh_button.clicked.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        target = self.date_edit.date().toPython()
        self._run(lambda: self.service.load_pickup_status(target))

    def render(self, result: object) -> None:
        rows = list(result)  # type: ignore[arg-type]
        self.table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            assert isinstance(row, PickupStatusRow)
            for column, value in enumerate(
                (
                    row.meal_type,
                    row.menu,
                    row.ordered,
                    row.picked_up,
                    row.remaining,
                )
            ):
                self.table.setItem(
                    row_number,
                    column,
                    QTableWidgetItem(str(value)),
                )


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
