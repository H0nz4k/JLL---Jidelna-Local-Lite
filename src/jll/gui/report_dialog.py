"""Denní sestavy objednané stravy.

Business SQL zůstává v `OrderReadService`, agregace v `jll.reports`; dialog
jen zobrazuje výsledek. Načítání běží na worker threadu, takže náhled
neblokuje GUI, a datum je vždy zřetelně vidět.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QThreadPool, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..policy import Permission, SessionPolicy
from ..read_models import DailyReport
from ..read_service import OrderReadService
from ..reports import group_by_category, norm_matrices, sort_named_rows
from . import theme
from .theme import TextRole
from .workers import FunctionWorker

NO_ORDERS_TEXT = "Pro tento den nejsou žádné objednávky."
NO_COOKING_DAY_TEXT = "Další varný den nebyl v kalendáři nalezen."


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeToContents
    )
    return table


def _fill(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setRowCount(len(rows))
    for row_number, row in enumerate(rows):
        for column, value in enumerate(row):
            table.setItem(row_number, column, QTableWidgetItem(value))


class DailyReportDialog(QDialog):
    """Sestavy pro zvolený den: jmenný seznam a doložené souhrny."""

    def __init__(
        self,
        service: OrderReadService,
        target: date,
        policy: SessionPolicy,
        *,
        allowed_categories: frozenset[str] = frozenset(),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.policy = policy
        self.category_order = sorted(allowed_categories)
        self.report: DailyReport | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._generation = 0

        self.setWindowTitle("Sestavy – objednaná strava")
        self.resize(1000, 660)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING["md"])

        day_row = QHBoxLayout()
        day_row.setSpacing(theme.SPACING["sm"])
        self.today_button = QPushButton("Dnes")
        self.today_button.clicked.connect(lambda: self._select_offset(0))
        day_row.addWidget(self.today_button)
        self.tomorrow_button = QPushButton("Zítra")
        self.tomorrow_button.clicked.connect(lambda: self._select_offset(1))
        day_row.addWidget(self.tomorrow_button)
        self.next_cooking_button = QPushButton("Následující varný den")
        self.next_cooking_button.clicked.connect(self._select_next_cooking_day)
        day_row.addWidget(self.next_cooking_button)
        day_row.addWidget(QLabel("Vybrat datum:"))
        self.date_edit = QDateEdit(QDate(target.year, target.month, target.day))
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.dateChanged.connect(lambda _value: self.reload())
        day_row.addWidget(self.date_edit)
        self.refresh_button = QPushButton("Načíst znovu")
        self.refresh_button.clicked.connect(self.reload)
        day_row.addWidget(self.refresh_button)
        day_row.addStretch()
        for button in (
            self.today_button,
            self.tomorrow_button,
            self.next_cooking_button,
            self.refresh_button,
        ):
            theme.apply_role(button, TextRole.ACTION)
        layout.addLayout(day_row)

        self.day_label = QLabel("—")
        theme.apply_role(self.day_label, TextRole.PRIMARY)
        layout.addWidget(self.day_label)
        self.summary_label = QLabel("—")
        self.summary_label.setWordWrap(True)
        theme.apply_role(self.summary_label, TextRole.BODY)
        layout.addWidget(self.summary_label)

        grouping_row = QHBoxLayout()
        grouping_row.addWidget(QLabel("Jmenný seznam:"))
        self.ungrouped_radio = QRadioButton("společně")
        self.grouped_radio = QRadioButton("oddělit podle kategorií")
        self.ungrouped_radio.setChecked(True)
        self.grouping = QButtonGroup(self)
        self.grouping.addButton(self.ungrouped_radio, 0)
        self.grouping.addButton(self.grouped_radio, 1)
        self.ungrouped_radio.toggled.connect(self._render_named_list)
        grouping_row.addWidget(self.ungrouped_radio)
        grouping_row.addWidget(self.grouped_radio)
        grouping_row.addStretch()
        self.print_button = QPushButton("Vytvořit PDF")
        theme.apply_role(self.print_button, TextRole.ACTION)
        self.print_button.clicked.connect(self._create_pdf)
        self.print_button.setVisible(
            Permission.REPORTS_PRINT in policy.permissions
        )
        grouping_row.addWidget(self.print_button)
        layout.addLayout(grouping_row)

        tabs = QTabWidget()
        self.named_table = _table(
            [
                "Jméno",
                "Kategorie",
                "Typ stravy",
                "Menu",
                "Norma",
                "Objednané jídlo",
            ]
        )
        tabs.addTab(self.named_table, "Jmenný seznam")
        self.menu_table = _table(
            ["Typ stravy", "Menu", "Počet porcí", "Název jídla"]
        )
        tabs.addTab(self.menu_table, "Jídelníček a porce")
        self.category_table = _table(
            ["Kategorie", "Název", "Norma", "Objednávek"]
        )
        tabs.addTab(self.category_table, "Kategorie")
        self.norm_table = _table(
            ["Typ stravy", "Norma", "Menu", "Počet porcí"]
        )
        tabs.addTab(self.norm_table, "Normy A–D")
        layout.addWidget(tabs, 1)

        self.status_label = QLabel("Připraveno.")
        self.status_label.setWordWrap(True)
        theme.apply_role(self.status_label, TextRole.META)
        layout.addWidget(self.status_label)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

        self.reload()

    @property
    def target_date(self) -> date:
        return self.date_edit.date().toPython()

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.today_button,
            self.tomorrow_button,
            self.next_cooking_button,
            self.refresh_button,
        ):
            button.setEnabled(not busy)

    def _select_offset(self, days: int) -> None:
        """Dnes a Zítra se počítají ze serverového business data."""

        self._set_busy(True)
        self.status_label.setText("Zjišťuji aktuální datum provozu…")
        service = self.service
        self._generation += 1
        request_id = self._generation

        worker = FunctionWorker(
            request_id,
            lambda: service.server_today() + timedelta(days=days),
        )
        worker.signals.succeeded.connect(self._date_resolved)
        worker.signals.failed.connect(self._failed)
        self.thread_pool.start(worker)

    def _select_next_cooking_day(self) -> None:
        self._set_busy(True)
        self.status_label.setText("Hledám následující varný den…")
        service = self.service
        self._generation += 1
        request_id = self._generation
        reference = self.target_date

        worker = FunctionWorker(
            request_id,
            lambda: service.next_cooking_day(reference),
        )
        worker.signals.succeeded.connect(self._date_resolved)
        worker.signals.failed.connect(self._failed)
        self.thread_pool.start(worker)

    def _date_resolved(
        self,
        request_id: int,
        result: object,
        _duration_ms: float,
    ) -> None:
        if request_id != self._generation:
            return
        self._set_busy(False)
        if not isinstance(result, date):
            self.status_label.setText(NO_COOKING_DAY_TEXT)
            return
        if result == self.target_date:
            self.reload()
            return
        # Změna data spustí reload signálem dateChanged, jinak by sestava
        # pro stejný den zbytečně načítala dvakrát.
        self.date_edit.setDate(QDate(result.year, result.month, result.day))

    def reload(self) -> None:
        self._generation += 1
        request_id = self._generation
        target = self.target_date
        service = self.service
        self._set_busy(True)
        self.status_label.setText("Načítám sestavu z LAB databáze…")
        self.day_label.setText(f"Den: {target.strftime('%d.%m.%Y')}")
        worker = FunctionWorker(
            request_id,
            lambda: service.load_daily_report(target),
        )
        worker.signals.succeeded.connect(self._loaded)
        worker.signals.failed.connect(self._failed)
        self.thread_pool.start(worker)

    def _loaded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._generation or not isinstance(
            result, DailyReport
        ):
            return
        self._set_busy(False)
        self.render(result)
        self.status_label.setText(
            f"Načteno z LAB databáze za {duration_ms:.0f} ms."
        )
        self.status_label.setProperty("tone", None)
        theme.repolish(self.status_label)

    def _failed(
        self,
        request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        if request_id != self._generation:
            return
        self._set_busy(False)
        self.status_label.setText(f"Sestavu nelze načíst: {error}")
        self.status_label.setProperty("tone", "danger")
        theme.repolish(self.status_label)

    def render(self, report: DailyReport) -> None:
        self.report = report
        subject = report.subject_name or "Stravovací provoz"
        self.day_label.setText(
            f"{subject} · {report.target_date.strftime('%d.%m.%Y')}"
        )
        if report.diners:
            self.summary_label.setText(
                f"Celkem porcí: {report.total_portions} · "
                f"objednávek: {report.total_orders} · "
                f"kategorií ve scope: {len(report.categories)}"
            )
        else:
            self.summary_label.setText(NO_ORDERS_TEXT)

        _fill(
            self.menu_table,
            [
                (
                    row.meal_type,
                    str(row.menu),
                    str(row.portions),
                    row.meal_name or "[název v jídelníčku nenalezen]",
                )
                for row in report.menus
            ],
        )
        _fill(
            self.category_table,
            [
                (
                    row.category,
                    row.category_name or "[bez názvu]",
                    row.norm or "[bez normy]",
                    str(row.orders),
                )
                for row in report.categories
            ],
        )
        norm_rows: list[tuple[str, ...]] = []
        for matrix in norm_matrices(report.norms):
            for norm in matrix.norms:
                for menu in matrix.menus:
                    norm_rows.append(
                        (
                            matrix.meal_type,
                            norm,
                            str(menu),
                            str(matrix.portions(norm, menu)),
                        )
                    )
        _fill(self.norm_table, norm_rows)
        self._render_named_list()

    def _render_named_list(self) -> None:
        if self.report is None:
            return
        rows: list[tuple[str, ...]] = []
        if self.grouped_radio.isChecked():
            for block in group_by_category(
                self.report.diners,
                self.category_order,
            ):
                rows.append(
                    (
                        f"— {block.label} ({len(block.rows)}) —",
                        "",
                        "",
                        "",
                        "",
                        "",
                    )
                )
                rows.extend(self._named_row(row) for row in block.rows)
        else:
            rows.extend(
                self._named_row(row)
                for row in sort_named_rows(self.report.diners)
            )
        _fill(self.named_table, rows)

    @staticmethod
    def _named_row(row) -> tuple[str, ...]:
        return (
            row.name,
            row.category_label,
            row.meal_type,
            str(row.menu),
            row.norm_label,
            row.meal_label,
        )

    def _create_pdf(self) -> None:
        """PDF export; chybějící lokální závislost se hlásí lidsky."""

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if self.report is None:
            return
        try:
            self.policy.require(Permission.REPORTS_PRINT)
        except Exception as exc:
            QMessageBox.warning(self, "Tisk není dostupný", str(exc))
            return
        from ..reports_pdf import PdfDependencyMissing, create_report_pdf

        suggestion = (
            f"sestava_{self.report.target_date.isoformat()}.pdf"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Uložit sestavu do PDF",
            suggestion,
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            created = create_report_pdf(
                self.report,
                path,
                grouped=self.grouped_radio.isChecked(),
                category_order=self.category_order,
            )
        except PdfDependencyMissing as exc:
            QMessageBox.warning(self, "PDF není k dispozici", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "PDF nelze vytvořit", str(exc))
            return
        self.status_label.setText(f"PDF vytvořeno: {created}")

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
