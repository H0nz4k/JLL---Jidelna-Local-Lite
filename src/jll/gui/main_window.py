from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, QEvent, Qt, QThreadPool, QTimer
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..application import (
    MutationOutcome,
    OrderApplicationService,
    determine_action,
    present_error,
)
from ..admin_service import AdminService
from ..chip_reader import ChipReader
from ..config import LabConfig
from ..orders.errors import ErrorCode, OrderBusinessError
from ..orders.models import OrderAction
from ..policy import Permission, SessionPolicy
from ..read_models import (
    DinerDay,
    DinerDetail,
    DinerSummary,
    LabDiagnostics,
    MealDay,
    MenuOption,
)
from ..read_service import OrderReadService
from ..session import SessionManager
from ..version import application_version, audit_client_version
from ..write_gates import CHIP_WRITE_GATES, DINER_WRITE_GATES
from . import theme
from .admin_dialog import AdminDialog
from .menu_row import MenuRow, format_money
from .read_overview_dialog import PickupStatusDialog, ReportsDialog
from .theme import TextRole
from .workers import FunctionWorker


class SafeErrorDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        code: str,
        correlation_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        theme.apply_role(label, TextRole.BODY)
        layout.addWidget(label)
        toggle = QToolButton()
        toggle.setText("Technický detail")
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)
        layout.addWidget(toggle)
        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(f"Error code: {code}\nCorrelation ID: {correlation_id}")
        detail.setMaximumHeight(72)
        detail.hide()
        layout.addWidget(detail)
        toggle.toggled.connect(
            lambda checked: (
                toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow),
                detail.setVisible(checked),
            )
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


MONTH_NAMES = (
    "LEDEN",
    "ÚNOR",
    "BŘEZEN",
    "DUBEN",
    "KVĚTEN",
    "ČERVEN",
    "ČERVENEC",
    "SRPEN",
    "ZÁŘÍ",
    "ŘÍJEN",
    "LISTOPAD",
    "PROSINEC",
)

LUNCH_CODES = frozenset({"A", "B", "C", "D"})


class MainWindow(QMainWindow):
    SEARCH_DEBOUNCE_MS = 300
    NON_COOKING_MARK = "*"
    MIN_DAY_COLUMN_WIDTH = 17
    LEFT_PANEL_MIN_WIDTH = 300
    LEFT_PANEL_MAX_WIDTH = 450
    LEFT_PANEL_RATIO = 0.30

    def __init__(
        self,
        config: LabConfig,
        read_service: OrderReadService,
        application_service: OrderApplicationService,
        session_manager: SessionManager | None = None,
        admin_service: AdminService | None = None,
        chip_reader: ChipReader | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.read_service = read_service
        self.application_service = application_service
        self.session_manager = session_manager
        self.admin_service = admin_service
        self.chip_reader = chip_reader
        self.thread_pool = QThreadPool.globalInstance()
        self._search_generation = 0
        self._detail_generation = 0
        self._mutation_generation = 0
        self._current_diner: DinerSummary | None = None
        self._current_day: DinerDay | None = None
        self._diagnostics: LabDiagnostics | None = None
        self._lab_guard_verified = False
        self._last_error_code = "—"
        self._active_write_button: QPushButton | None = None
        self._active_write_button_text = ""
        self._active_write_button_variant: str | None = None
        self._mutation_context: tuple[int, date] | None = None
        self._state_labels: list[QLabel] = []
        self._active_meal_type: str | None = None
        self._month_layout_signature: tuple[int, int] | None = None
        self._menu_rows: dict[tuple[str, int], MenuRow] = {}
        self._sizing_month_columns = False
        self._sizing_result_columns = False
        self._left_panel_width: int | None = None
        self._detail_split_by_user = False

        self.setWindowTitle("JidelnaLocalLite – LAB")
        self.resize(1366, 728)
        self.setMinimumSize(1024, 600)
        self._build_ui()
        self._apply_style()
        self._setup_shortcuts()

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(self.SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self._start_search)
        self.search_edit.textChanged.connect(self._queue_search)
        self.results.itemSelectionChanged.connect(self._result_selected)
        self.results.itemActivated.connect(lambda _item: self._result_selected())
        self.date_edit.dateChanged.connect(self._date_changed)
        self.month_table.cellClicked.connect(self._month_cell_clicked)
        self._refresh_policy()
        self._set_blocked(True, "Ověřuji lokální LAB databázi…")
        QTimer.singleShot(0, self._start_lab_verification)

    @staticmethod
    def _label(
        text: str,
        role: TextRole,
        tone: str | None = None,
    ) -> QLabel:
        label = QLabel(text)
        theme.apply_role(label, role)
        if tone is not None:
            label.setProperty("tone", tone)
        return label

    @staticmethod
    def _button(text: str, variant: str = "secondary") -> QPushButton:
        button = QPushButton(text)
        theme.apply_role(button, TextRole.ACTION)
        button.setProperty("variant", variant)
        return button

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        gap = theme.SPACING
        outer.setContentsMargins(gap["lg"], gap["md"], gap["lg"], gap["md"])
        outer.setSpacing(gap["md"])

        header = QHBoxLayout()
        header.setSpacing(gap["xl"])
        header.addWidget(self._label("JidelnaLocalLite", TextRole.ACTION, "accent"))
        header.addWidget(
            self._label(f"Provozovna: {self.config.site_name}", TextRole.META)
        )
        user_name = (
            self.session_manager.current_user().display_name
            if self.session_manager is not None
            else self.application_service.policy.user_identity
        )
        self.user_label = self._label(f"Uživatel: {user_name}", TextRole.META)
        header.addWidget(self.user_label)
        header.addStretch()
        self.guard_label = self._label("LAB guard: ověřování…", TextRole.META)
        header.addWidget(self.guard_label)
        self.lab_banner = self._label(
            f"LAB · {self.config.database}",
            TextRole.ACTION,
            "labBanner",
        )
        header.addWidget(self.lab_banner)
        outer.addLayout(header)

        navigation = QHBoxLayout()
        navigation.setSpacing(gap["md"])
        navigation.addWidget(self._label("STRÁVNÍCI", TextRole.ACTION, "accent"))
        self.new_diner_button = self._button("+ Nový strávník")
        self.new_diner_button.setEnabled(False)
        self.new_diner_button.setToolTip(DINER_WRITE_GATES["create"].tooltip)
        navigation.addWidget(self.new_diner_button)
        self.edit_diner_button = self._button("Editovat strávníka")
        self.edit_diner_button.setEnabled(False)
        self.edit_diner_button.setToolTip(
            DINER_WRITE_GATES["edit_personal"].tooltip
        )
        navigation.addWidget(self.edit_diner_button)
        self.pickup_button = self._button("Stav výdeje")
        self.pickup_button.clicked.connect(self._open_pickup_status)
        navigation.addWidget(self.pickup_button)
        self.reports_button = self._button("Sestavy")
        self.reports_button.clicked.connect(self._open_reports)
        navigation.addWidget(self.reports_button)
        self.admin_button = self._button("Administrace")
        self.admin_button.clicked.connect(self._open_admin)
        self.admin_button.setVisible(self.admin_service is not None)
        navigation.addWidget(self.admin_button)
        navigation.addStretch()
        outer.addLayout(navigation)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        diner_list = QWidget()
        diner_list_layout = QVBoxLayout(diner_list)
        diner_list_layout.setContentsMargins(0, 0, gap["md"], 0)
        diner_list_layout.setSpacing(gap["sm"])
        search_row = QHBoxLayout()
        search_label = self._label("Hledat:", TextRole.META)
        search_row.addWidget(search_label)
        self.search_edit = QLineEdit()
        theme.apply_role(self.search_edit, TextRole.BODY)
        search_label.setBuddy(self.search_edit)
        self.search_edit.setPlaceholderText("Jméno, ev. číslo nebo čip…")
        self.search_edit.setClearButtonEnabled(True)
        search_row.addWidget(self.search_edit, 1)
        diner_list_layout.addLayout(search_row)
        diner_list_layout.addWidget(
            self._label("SEZNAM POVOLENÝCH STRÁVNÍKŮ", TextRole.ACTION, "accent")
        )
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(
            ["Jméno", "Kat.", "Třída", "Ev. číslo"]
        )
        for column, tooltip in enumerate(
            ("Jméno", "Kategorie", "Třída", "Evidenční číslo")
        ):
            self.results.horizontalHeaderItem(column).setToolTip(tooltip)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setWordWrap(False)
        self.results.setTextElideMode(Qt.ElideRight)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        self.results.horizontalHeader().setStretchLastSection(False)
        self.results.viewport().installEventFilter(self)
        self.results.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        diner_list_layout.addWidget(self.results, 1)
        diner_list.setMinimumWidth(self.LEFT_PANEL_MIN_WIDTH)
        diner_list.setMaximumWidth(self.LEFT_PANEL_MAX_WIDTH)
        self.splitter.addWidget(diner_list)

        self.detail_splitter = QSplitter(Qt.Vertical)
        self.detail_splitter.setChildrenCollapsible(False)

        month_pane = QWidget()
        month_layout = QVBoxLayout(month_pane)
        month_layout.setContentsMargins(0, 0, 0, 0)
        month_layout.setSpacing(gap["sm"])
        identity_row = QHBoxLayout()
        identity_row.setSpacing(gap["md"])
        self.diner_label = self._label("Vyberte strávníka", TextRole.PRIMARY)
        identity_row.addWidget(self.diner_label)
        identity_row.addStretch()
        self.previous_month = self._button("‹")
        self.previous_month.setProperty("variant", "compact")
        self.previous_month.setToolTip("Předchozí měsíc")
        self.previous_month.clicked.connect(lambda: self._move_month(-1))
        identity_row.addWidget(self.previous_month)
        self.month_label = self._label("—", TextRole.ACTION, "accent")
        self.month_label.setAlignment(Qt.AlignCenter)
        identity_row.addWidget(self.month_label)
        self.next_month = self._button("›")
        self.next_month.setProperty("variant", "compact")
        self.next_month.setToolTip("Následující měsíc")
        self.next_month.clicked.connect(lambda: self._move_month(1))
        identity_row.addWidget(self.next_month)
        self.date_edit = QDateEdit()
        theme.apply_role(self.date_edit, TextRole.META)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setToolTip("Přesný výběr dne")
        identity_row.addWidget(self.date_edit)
        month_layout.addLayout(identity_row)
        identity_details = QHBoxLayout()
        identity_details.setSpacing(gap["xl"])
        self.diner_meta_label = self._label(
            "Kategorie • třída • evidenční číslo",
            TextRole.META,
        )
        identity_details.addWidget(self.diner_meta_label)
        self.credit_label = self._label("Kredit: —", TextRole.ACTION)
        identity_details.addWidget(self.credit_label)
        self.chip_label = self._label("Čipy: —", TextRole.META)
        identity_details.addWidget(self.chip_label)
        identity_details.addStretch()
        self.chip_action_buttons: dict[Permission, QPushButton] = {}
        for permission, text, operation in (
            (Permission.CHIPS_ASSIGN, "Přidělit čip", "assign"),
            (Permission.CHIPS_RETURN, "Vrátit čip", "return"),
            (Permission.CHIPS_BLOCK, "Zablokovat čip", "block"),
            (Permission.CHIPS_LOST, "Označit ztrátu", "lost"),
        ):
            button = self._button(text)
            button.setEnabled(False)
            button.setProperty("contractOperation", operation)
            button.setProperty(
                "contractStatus",
                CHIP_WRITE_GATES[operation].status.value,
            )
            button.setToolTip(CHIP_WRITE_GATES[operation].tooltip)
            self.chip_action_buttons[permission] = button
            identity_details.addWidget(button)
        month_layout.addLayout(identity_details)
        month_header = QHBoxLayout()
        month_header.setSpacing(gap["md"])
        self.month_title = self._label(
            "MĚSÍČNÍ PŘEHLED PŘIHLÁŠEK",
            TextRole.ACTION,
            "accent",
        )
        month_header.addWidget(self.month_title)
        month_header.addWidget(
            self._label("* = nevaří se", TextRole.META)
        )
        month_header.addStretch()
        month_layout.addLayout(month_header)
        self.month_table = QTableWidget(0, 0)
        self.month_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.month_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.month_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.month_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.month_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.month_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        header_view = self.month_table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Fixed)
        header_view.setMinimumSectionSize(self.MIN_DAY_COLUMN_WIDTH)
        header_view.setHighlightSections(False)
        self.month_table.viewport().installEventFilter(self)
        month_layout.addWidget(self.month_table, 1)
        self.detail_splitter.addWidget(month_pane)

        day_pane = QWidget()
        day_layout = QVBoxLayout(day_pane)
        day_layout.setContentsMargins(0, 0, 0, 0)
        day_layout.setSpacing(gap["sm"])
        self.day_title = self._label(
            "JÍDELNÍČEK VYBRANÉHO DNE",
            TextRole.ACTION,
            "accent",
        )
        day_layout.addWidget(self.day_title)
        self.meals_scroll = QScrollArea()
        self.meals_scroll.setWidgetResizable(True)
        self.meals_scroll.setFrameShape(QFrame.NoFrame)
        self.meals_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.meals_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        meals_host = QWidget()
        self.meals_layout = QVBoxLayout(meals_host)
        self.meals_layout.setContentsMargins(0, 0, 0, 0)
        self.meals_layout.setSpacing(gap["sm"])
        self.meals_layout.addWidget(
            self._label(
                "Po výběru strávníka se načte jídelníček a objednávky.",
                TextRole.BODY,
            )
        )
        self.meals_layout.addStretch()
        self.meals_scroll.setWidget(meals_host)
        day_layout.addWidget(self.meals_scroll, 1)
        self.detail_splitter.addWidget(day_pane)
        self.detail_splitter.setStretchFactor(0, 0)
        self.detail_splitter.setStretchFactor(1, 1)

        self.splitter.addWidget(self.detail_splitter)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.installEventFilter(self)
        self.splitter.splitterMoved.connect(self._remember_panel_width)
        self.detail_splitter.splitterMoved.connect(self._remember_detail_split)
        outer.addWidget(self.splitter, 1)

        self.diagnostic_group = QGroupBox("LAB diagnostika")
        theme.apply_role(self.diagnostic_group, TextRole.ACTION)
        self.diagnostic_group.setCheckable(True)
        self.diagnostic_group.setChecked(False)
        diagnostics_layout = QFormLayout(self.diagnostic_group)
        self.diag_database = self._label(
            f"{self.config.host}:{self.config.port}/{self.config.database}",
            TextRole.META,
        )
        self.diag_system = self._label("—", TextRole.META)
        self.diag_timezone = self._label(
            self.config.business_timezone,
            TextRole.META,
        )
        self.diag_lock = self._label(str(self.config.strict_config_lock), TextRole.META)
        self.diag_scope = self._label(
            ", ".join(sorted(self.config.allowed_categories)),
            TextRole.META,
        )
        self.diag_permissions = self._label(
            ", ".join(
                sorted(
                    permission.value
                    for permission in self.application_service.policy.permissions
                )
            ),
            TextRole.META,
        )
        self.diag_error = self._label("—", TextRole.META)
        self.diag_duration = self._label("—", TextRole.META)
        self.diag_version = self._label(
            f"{application_version()} (audit {audit_client_version()})",
            TextRole.META,
        )
        for caption, field in (
            ("Verze klienta:", self.diag_version),
            ("DB:", self.diag_database),
            ("System identifier:", self.diag_system),
            ("Business timezone:", self.diag_timezone),
            ("strict_config_lock:", self.diag_lock),
            ("allowed_categories:", self.diag_scope),
            ("permissions:", self.diag_permissions),
            ("Poslední error code:", self.diag_error),
            ("Poslední request:", self.diag_duration),
        ):
            diagnostics_layout.addRow(self._label(caption, TextRole.META), field)
        for index in range(diagnostics_layout.rowCount()):
            item = diagnostics_layout.itemAt(index, QFormLayout.FieldRole)
            if item and item.widget():
                item.widget().setVisible(False)
        self.diagnostic_group.toggled.connect(self._toggle_diagnostics)
        outer.addWidget(self.diagnostic_group)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Spouštím LAB aplikaci…")
        self._toggle_diagnostics(False)

    def _apply_style(self) -> None:
        """Vzhled je pouze v centrálním theme; okno nemá vlastní QSS."""

        theme.apply_theme(QApplication.instance())
        self._apply_metrics()

    def _apply_metrics(self) -> None:
        """Rozměry odvozené z fontu, aby přežily Windows scaling 100–150 %."""

        metrics = QFontMetrics(self.font())
        pad = theme.SPACING["md"]
        line = metrics.height()
        self.month_table.verticalHeader().setDefaultSectionSize(line + pad)
        self.month_table.verticalHeader().setMinimumWidth(
            metrics.horizontalAdvance("Oběd-Xxxx") + pad + theme.SPACING["sm"]
        )
        arrow = metrics.horizontalAdvance("‹") + 2 * theme.SPACING["lg"]
        for button in (self.previous_month, self.next_month):
            button.setMinimumWidth(arrow)
            button.setMaximumWidth(arrow * 2)
        self.month_label.setMinimumWidth(
            metrics.horizontalAdvance("ČERVENEC 2026") + 2 * pad
        )

    def _setup_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence("Ctrl+F"), self),
            QShortcut(QKeySequence("Escape"), self),
            QShortcut(QKeySequence("Down"), self),
            QShortcut(QKeySequence("Up"), self),
        ]
        self._shortcuts[0].activated.connect(self.search_edit.setFocus)
        self._shortcuts[1].activated.connect(self._escape_context)
        self._shortcuts[2].activated.connect(lambda: self._move_result(1))
        self._shortcuts[3].activated.connect(lambda: self._move_result(-1))
        self.search_edit.returnPressed.connect(self._open_current_result)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._handle_menu_digit(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_menu_digit(self, event: QKeyEvent) -> bool:
        """Klávesy 1..9 volí číslo menu aktivního typu stravy."""

        text = event.text()
        if len(text) != 1 or text not in "123456789":
            return False
        if event.modifiers() & ~Qt.KeypadModifier:
            return False
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QDateEdit)):
            return False
        meal_type = self._active_meal_type
        if meal_type is None:
            return False
        row = self._menu_rows.get((meal_type, int(text)))
        if row is None or not row.action_button.isEnabled():
            return False
        if not row.clickable:
            self.statusBar().showMessage(
                f"{meal_type}, menu {text} je objednáno. "
                f"Odhlášení je jen tlačítkem Odhlásit {text}."
            )
            return True
        row.activate()
        return True

    def _move_result(self, direction: int) -> None:
        if not (self.search_edit.hasFocus() or self.results.hasFocus()):
            return
        count = self.results.rowCount()
        if not count:
            return
        current = self.results.currentRow()
        target = max(0, min(count - 1, current + direction))
        self.results.selectRow(target)
        self.results.setFocus()

    def _open_current_result(self) -> None:
        if self.results.rowCount() and self.results.currentRow() < 0:
            self.results.selectRow(0)
        self._result_selected()

    def _escape_context(self) -> None:
        if self.search_edit.text():
            self.search_edit.clear()
            self.search_edit.setFocus()
            return
        if self._current_diner is not None:
            self.results.clearSelection()
            self._current_diner = None
            self._current_day = None
            self._active_meal_type = None
            self._menu_rows = {}
            self._month_layout_signature = None
            self.diner_label.setText("Vyberte strávníka")
            self.diner_meta_label.setText("Kategorie • třída • evidenční číslo")
            self.credit_label.setText("Kredit: —")
            self.chip_label.setText("Čipy: —")
            self.chip_label.setToolTip("")
            self.month_label.setText("—")
            self.day_title.setText("JÍDELNÍČEK VYBRANÉHO DNE")
            self.month_table.clear()
            self.month_table.setRowCount(0)
            self.month_table.setColumnCount(0)
            self._clear_layout(self.meals_layout)
            self.meals_layout.addWidget(
                self._label(
                    "Po výběru strávníka se načte jídelníček a objednávky.",
                    TextRole.BODY,
                )
            )
            self.meals_layout.addStretch()

    def _move_month(self, offset: int) -> None:
        self.date_edit.setDate(self.date_edit.date().addMonths(offset))

    def _current_policy(self) -> SessionPolicy:
        return (
            self.session_manager.current_policy()
            if self.session_manager is not None
            else self.application_service.policy
        )

    def _refresh_policy(self) -> None:
        try:
            policy = self._current_policy()
        except Exception:
            self.admin_button.setEnabled(False)
            self.search_edit.setEnabled(False)
            return
        self.admin_button.setEnabled(Permission.ADMIN_USERS in policy.permissions)
        self.pickup_button.setVisible(
            Permission.PICKUP_STATUS_VIEW in policy.permissions
        )
        self.pickup_button.setEnabled(
            self._lab_guard_verified
            and Permission.PICKUP_STATUS_VIEW in policy.permissions
        )
        self.reports_button.setVisible(
            Permission.REPORTS_VIEW in policy.permissions
        )
        self.reports_button.setEnabled(
            self._lab_guard_verified
            and Permission.REPORTS_VIEW in policy.permissions
        )
        self.new_diner_button.setVisible(
            Permission.DINERS_CREATE in policy.permissions
        )
        self.edit_diner_button.setVisible(
            Permission.DINERS_EDIT in policy.permissions
        )
        self.new_diner_button.setEnabled(False)
        self.edit_diner_button.setEnabled(False)
        for permission, button in self.chip_action_buttons.items():
            button.setVisible(permission in policy.permissions)
            button.setEnabled(False)
        self.diag_permissions.setText(
            ", ".join(sorted(permission.value for permission in policy.permissions))
        )
        can_view = Permission.DINERS_VIEW in policy.permissions
        self.search_edit.setEnabled(can_view and self._lab_guard_verified)
        self.results.setEnabled(can_view and self._lab_guard_verified)
        if not can_view and self._current_diner is not None:
            self._escape_context()
        if self.session_manager is not None:
            self.user_label.setText(
                f"Přihlášený uživatel: "
                f"{self.session_manager.current_user().display_name}"
            )
        if self._current_day is not None:
            self._render_day(self._current_day)

    def _open_pickup_status(self) -> None:
        try:
            self._current_policy().require(Permission.PICKUP_STATUS_VIEW)
            PickupStatusDialog(
                self.read_service,
                self.date_edit.date().toPython(),
                self,
            ).exec()
        except Exception as exc:
            self._show_error(exc)

    def _open_reports(self) -> None:
        try:
            self._current_policy().require(Permission.REPORTS_VIEW)
            ReportsDialog(
                self.read_service,
                self.date_edit.date().toPython(),
                self,
            ).exec()
        except Exception as exc:
            self._show_error(exc)

    def _open_admin(self) -> None:
        if self.admin_service is None:
            return
        pin, accepted = QInputDialog.getText(
            self,
            "Administrace – opětovné ověření",
            "Zadejte svůj PIN:",
            QLineEdit.Password,
        )
        if not accepted:
            return
        try:
            self.admin_service.reauthenticate(pin)
            dialog = AdminDialog(
                self.config,
                self.admin_service,
                self.chip_reader,
                self,
            )
            dialog.policy_changed.connect(self._refresh_policy)
            dialog.exec()
            self._refresh_policy()
        except Exception as exc:
            QMessageBox.warning(self, "Administrace není dostupná", str(exc))

    def _toggle_diagnostics(self, expanded: bool) -> None:
        layout = self.diagnostic_group.layout()
        for index in range(layout.rowCount()):
            item = layout.itemAt(index, QFormLayout.LabelRole)
            if item and item.widget():
                item.widget().setVisible(expanded)
            item = layout.itemAt(index, QFormLayout.FieldRole)
            if item and item.widget():
                item.widget().setVisible(expanded)
        for label in self._state_labels:
            label.setVisible(expanded)
        if self._current_day is not None:
            self._render_month(self._current_day)

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        self._apply_panel_sizes()
        self._apply_month_columns()

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if event.type() == QEvent.Resize:
            if watched is self.month_table.viewport():
                self._apply_month_columns()
            elif watched is self.results.viewport():
                self._apply_result_columns()
            elif watched is self.splitter:
                self._apply_panel_sizes()
        return super().eventFilter(watched, event)

    def _apply_result_columns(self) -> None:
        """Jméno dostane zbytek šířky, ostatní sloupce zůstanou celé."""

        available = self.results.viewport().width()
        if available <= 0 or self._sizing_result_columns:
            return
        self._sizing_result_columns = True
        try:
            metrics = QFontMetrics(self.font())
            header = self.results.horizontalHeader()
            side_widths: list[int] = []
            for column in (1, 2, 3):
                item = self.results.horizontalHeaderItem(column)
                label = item.text() if item is not None else ""
                wanted = max(
                    metrics.horizontalAdvance(label),
                    self.results.sizeHintForColumn(column),
                )
                side_widths.append(min(available // 4, wanted + 16))
            for column, width in zip((1, 2, 3), side_widths):
                header.resizeSection(column, width)
            header.resizeSection(
                0,
                max(
                    metrics.horizontalAdvance("Jméno") + 16,
                    available - sum(side_widths),
                ),
            )
        finally:
            self._sizing_result_columns = False

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self._apply_metrics()
            self._apply_month_columns()

    def _remember_panel_width(self, _position: int, _index: int) -> None:
        self._left_panel_width = self.splitter.sizes()[0]

    def _remember_detail_split(self, _position: int, _index: int) -> None:
        self._detail_split_by_user = True

    def _apply_panel_sizes(self) -> None:
        total = self.splitter.width()
        if total <= 0:
            return
        left = (
            self._left_panel_width
            if self._left_panel_width is not None
            else int(total * self.LEFT_PANEL_RATIO)
        )
        left = max(self.LEFT_PANEL_MIN_WIDTH, min(self.LEFT_PANEL_MAX_WIDTH, left))
        left = min(left, max(1, total - self.LEFT_PANEL_MIN_WIDTH))
        if self.splitter.sizes()[0] == left:
            return
        self.splitter.setSizes([left, max(1, total - left)])

    def _apply_month_columns(self) -> None:
        """Šířka dnů se počítá z viewportu, aby se vešel celý měsíc."""

        columns = self.month_table.columnCount()
        if columns == 0 or self._sizing_month_columns:
            return
        self._sizing_month_columns = True
        try:
            header = self.month_table.horizontalHeader()
            available = self.month_table.viewport().width()
            base = available // columns
            width = max(self.MIN_DAY_COLUMN_WIDTH, base)
            remainder = available - width * columns if width == base else 0
            for column in range(columns):
                extra = 1 if column < remainder else 0
                header.resizeSection(column, width + extra)
        finally:
            self._sizing_month_columns = False

    def _fit_month_pane(self) -> None:
        """Grid dostane právě potřebnou výšku, zbytek patří jídelníčku."""

        rows = self.month_table.rowCount()
        signature = (rows, self.month_table.columnCount())
        if (
            rows == 0
            or self._detail_split_by_user
            or signature == self._month_layout_signature
        ):
            return
        self._month_layout_signature = signature
        row_height = self.month_table.verticalHeader().defaultSectionSize()
        grid_height = (
            self.month_table.horizontalHeader().height()
            + rows * row_height
            + 2 * self.month_table.frameWidth()
            + self.month_table.horizontalScrollBar().sizeHint().height()
        )
        pane = self.detail_splitter.widget(0)
        chrome = pane.sizeHint().height() - self.month_table.sizeHint().height()
        total = self.detail_splitter.height()
        wanted = min(grid_height + max(0, chrome), max(1, total // 2))
        self.detail_splitter.setSizes([wanted, max(1, total - wanted)])

    def _set_blocked(self, blocked: bool, message: str) -> None:
        if not blocked:
            try:
                policy = self._current_policy()
                policy.require(Permission.DINERS_VIEW)
            except Exception:
                blocked = True
                message = "Přihlášený uživatel nemá oprávnění diners.view."
        self.search_edit.setEnabled(not blocked)
        self.results.setEnabled(not blocked)
        self.date_edit.setEnabled(not blocked)
        self.pickup_button.setEnabled(
            not blocked
            and Permission.PICKUP_STATUS_VIEW
            in self._current_policy().permissions
        )
        self.reports_button.setEnabled(
            not blocked
            and Permission.REPORTS_VIEW in self._current_policy().permissions
        )
        self.guard_label.setText(
            "LAB guard: BLOKOVÁNO" if blocked else "LAB guard: OVĚŘENO"
        )
        self.guard_label.setProperty("tone", "danger" if blocked else "ordered")
        theme.repolish(self.guard_label)
        self.statusBar().showMessage(message)

    def _start_lab_verification(self) -> None:
        worker = FunctionWorker(
            1,
            lambda: (self.read_service.verify_lab(), self.read_service.server_today()),
        )
        worker.signals.succeeded.connect(self._lab_verified)
        worker.signals.failed.connect(self._lab_failed)
        self.thread_pool.start(worker)

    def _lab_verified(
        self,
        _request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        diagnostics, server_date = result
        assert isinstance(diagnostics, LabDiagnostics)
        assert isinstance(server_date, date)
        self._diagnostics = diagnostics
        self._lab_guard_verified = True
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(QDate(server_date.year, server_date.month, server_date.day))
        self.date_edit.blockSignals(False)
        self.diag_system.setText(
            diagnostics.system_identifier[:8]
            + "…"
            + diagnostics.system_identifier[-4:]
        )
        self._set_duration("read", duration_ms)
        self._set_blocked(False, "LAB databáze ověřena. Načítám první stránku…")
        self._start_initial_list()
        self.search_edit.setFocus()

    def _lab_failed(
        self,
        _request_id: int,
        error: object,
        duration_ms: float,
    ) -> None:
        safe = present_error(error if isinstance(error, BaseException) else Exception())
        self._lab_guard_verified = False
        self._record_error(safe.code)
        self._set_duration("read", duration_ms)
        self._set_blocked(True, safe.user_message)
        SafeErrorDialog(
            "LAB guard zablokoval aplikaci",
            safe.user_message,
            safe.code,
            safe.correlation_id,
            self,
        ).open()

    def _queue_search(self, _text: str) -> None:
        self._search_generation += 1
        self.search_timer.stop()
        stripped = self.search_edit.text().strip()
        if not stripped:
            self._start_initial_list()
            return
        if len(stripped) < 2:
            self._fill_results([])
            self.statusBar().showMessage("Zadejte alespoň 2 znaky.")
            return
        self.search_timer.start()

    def _start_initial_list(self) -> None:
        self._search_generation += 1
        request_id = self._search_generation
        worker = FunctionWorker(request_id, self.read_service.list_diners)
        worker.signals.succeeded.connect(self._search_succeeded)
        worker.signals.failed.connect(self._search_failed)
        self.thread_pool.start(worker)

    def _start_search(self) -> None:
        request_id = self._search_generation
        query = self.search_edit.text()
        self.statusBar().showMessage("Vyhledávám…")
        worker = FunctionWorker(
            request_id,
            lambda: self.read_service.search_diners(query),
        )
        worker.signals.succeeded.connect(self._search_succeeded)
        worker.signals.failed.connect(self._search_failed)
        self.thread_pool.start(worker)

    def _search_succeeded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._search_generation:
            return
        rows = list(result)
        self._fill_results(rows)
        self._set_duration("read", duration_ms)
        self.statusBar().showMessage(
            f"Nalezeno: {len(rows)} (limit {self.config.search_limit})"
        )

    def _search_failed(
        self,
        request_id: int,
        error: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._search_generation:
            return
        self._set_duration("read", duration_ms)
        self._show_error(
            error if isinstance(error, BaseException) else Exception()
        )

    def _fill_results(self, rows: list[DinerSummary]) -> None:
        selected_evidcislo = (
            self._current_diner.evidcislo
            if self._current_diner is not None
            else None
        )
        self.results.setRowCount(0)
        for row_number, diner in enumerate(rows):
            self.results.insertRow(row_number)
            values = [
                diner.name,
                diner.category,
                diner.class_name,
                str(diner.evidcislo),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, diner)
                self.results.setItem(row_number, column, item)
            if diner.evidcislo == selected_evidcislo:
                self.results.selectRow(row_number)
        self._apply_result_columns()

    def _result_selected(self) -> None:
        items = self.results.selectedItems()
        if not items:
            return
        diner = self.results.item(items[0].row(), 0).data(Qt.UserRole)
        if not isinstance(diner, DinerSummary):
            return
        self._current_diner = diner
        self._load_current_day()

    def _date_changed(self, _date: QDate) -> None:
        if self._current_diner is not None:
            self._load_current_day()

    def _load_current_day(self) -> None:
        diner = self._current_diner
        if diner is None:
            return
        self._detail_generation += 1
        request_id = self._detail_generation
        target = self.date_edit.date().toPython()
        self.statusBar().showMessage("Načítám objednávky…")
        worker = FunctionWorker(
            request_id,
            lambda: self.read_service.load_diner_day(diner.evidcislo, target),
        )
        worker.signals.succeeded.connect(self._detail_succeeded)
        worker.signals.failed.connect(self._detail_failed)
        self.thread_pool.start(worker)

    def _detail_succeeded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._detail_generation:
            return
        if not isinstance(result, DinerDay):
            return
        self._set_duration("read", duration_ms)
        self._render_day(result)
        self.statusBar().showMessage("Objednávky načteny z LAB databáze.")

    def _detail_failed(
        self,
        request_id: int,
        error: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._detail_generation:
            return
        self._set_duration("read", duration_ms)
        self._show_error(
            error if isinstance(error, BaseException) else Exception()
        )

    @staticmethod
    def _money(value: Decimal) -> str:
        return format_money(value)

    @staticmethod
    def _chip_rows(diner: DinerDetail) -> list[str]:
        rows = [
            f"{chip.code} — {chip.status_label}"
            for chip in diner.chips
        ]
        known_codes = {chip.code for chip in diner.chips}
        if diner.chip_number and diner.chip_number not in known_codes:
            rows.append(f"{diner.chip_number} — legacy pole stravnik.cip")
        return rows

    @staticmethod
    def _chip_text(diner: DinerDetail) -> str:
        rows = MainWindow._chip_rows(diner)
        if not rows:
            return "Čipy: —"
        if len(rows) == 1:
            return f"Čipy: {rows[0]}"
        return f"Čipy ({len(rows)}): {rows[0]} …"

    @staticmethod
    def _chip_tooltip(diner: DinerDetail) -> str:
        rows = MainWindow._chip_rows(diner)
        return "IDENTIFIKAČNÍ ČIPY (pouze pro čtení):\n" + (
            "\n".join(rows) if rows else "—"
        )

    def _render_day(self, day: DinerDay) -> None:
        self._current_day = day
        diner = day.diner
        self.diner_label.setText(diner.name)
        self.diner_meta_label.setText(
            f"{diner.category} • {diner.class_name or '—'} • ev. {diner.evidcislo}"
        )
        self.credit_label.setText(
            "Kredit: " + self._money(diner.available_credit)
        )
        self.chip_label.setText(self._chip_text(diner))
        self.chip_label.setToolTip(self._chip_tooltip(diner))
        self._render_month(day)
        self._clear_layout(self.meals_layout)
        self._state_labels = []
        self._menu_rows = {}
        if self._active_meal_type not in {meal.meal_type for meal in day.meals}:
            self._active_meal_type = None
        lunch = [item for item in day.meals if item.code in LUNCH_CODES]
        others = [item for item in day.meals if item.code not in LUNCH_CODES]
        if lunch:
            self.meals_layout.addWidget(self._meal_group("OBĚD", lunch))
        for meal in others:
            self.meals_layout.addWidget(
                self._meal_group(meal.meal_type.upper(), [meal])
            )
        if not day.meals:
            self.meals_layout.addWidget(
                self._label(
                    "Pro tento den nejsou dostupné typy stravy.",
                    TextRole.BODY,
                )
            )
        self.meals_layout.addStretch()
        self._render_active_marker()

    def _render_month(self, day: DinerDay) -> None:
        days_in_month = calendar.monthrange(
            day.target_date.year,
            day.target_date.month,
        )[1]
        self.month_title.setText("MĚSÍČNÍ PŘEHLED PŘIHLÁŠEK")
        self.month_label.setText(
            f"{MONTH_NAMES[day.target_date.month - 1]} {day.target_date.year}"
        )
        self.month_table.clear()
        self.month_table.setRowCount(len(day.meals))
        self.month_table.setColumnCount(days_in_month)
        self.month_table.setHorizontalHeaderLabels(
            [str(number) for number in range(1, days_in_month + 1)]
        )
        self.month_table.setVerticalHeaderLabels(
            [meal.meal_type for meal in day.meals]
        )
        today = day.server_now.date()
        for row, meal in enumerate(day.meals):
            for column in range(days_in_month):
                day_number = column + 1
                value = (
                    meal.month_states[column]
                    if len(meal.month_states) > column
                    else None
                )
                ordered = (
                    value is not None
                    and len(value) == 1
                    and "1" <= value <= "9"
                )
                cell_date = date(
                    day.target_date.year,
                    day.target_date.month,
                    day_number,
                )
                selected = day_number == day.target_date.day
                cooking = day_number in meal.cooking_days
                if ordered:
                    text = value
                elif not cooking:
                    text = self.NON_COOKING_MARK
                else:
                    text = ""
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, (meal.meal_type, day_number))
                lines = [meal.meal_type, f"{cell_date:%d.%m.%Y}"]
                if ordered:
                    lines.append(f"Menu {value}")
                elif not cooking:
                    lines.append("Nevaří se")
                else:
                    lines.append("Bez objednávky")
                if self.diagnostic_group.isChecked():
                    lines.append(f"LAB diagnostika: stav {value or 'NULL'}")
                item.setToolTip("\n".join(lines))
                if ordered:
                    item.setBackground(
                        QColor(
                            theme.COLORS["ordered_selected"]
                            if selected
                            else theme.COLORS["ordered_background"]
                        )
                    )
                    item.setForeground(QColor(theme.COLORS["ordered_accent"]))
                    item.setFont(theme.font(TextRole.ACTION))
                elif selected:
                    item.setBackground(QColor(theme.COLORS["selected"]))
                elif not cooking:
                    item.setBackground(QColor(theme.COLORS["non_cooking"]))
                    item.setForeground(QColor(theme.COLORS["text_primary"]))
                    item.setFont(theme.font(TextRole.ACTION))
                elif cell_date == today:
                    item.setBackground(QColor(theme.COLORS["today"]))
                elif cell_date.weekday() >= 5:
                    item.setBackground(QColor(theme.COLORS["weekend"]))
                self.month_table.setItem(row, column, item)
        self._apply_month_columns()
        self._fit_month_pane()

    def _month_cell_clicked(self, row: int, column: int) -> None:
        item = self.month_table.item(row, column)
        if item is not None:
            payload = item.data(Qt.UserRole)
            if isinstance(payload, tuple) and payload:
                self._set_active_meal_type(str(payload[0]))
        current = self.date_edit.date().toPython()
        day_number = column + 1
        try:
            selected = date(current.year, current.month, day_number)
        except ValueError:
            return
        if selected == current:
            self._render_active_marker()
            return
        self.date_edit.setDate(
            QDate(selected.year, selected.month, selected.day)
        )

    def _set_active_meal_type(self, meal_type: str | None) -> None:
        self._active_meal_type = meal_type
        self._render_active_marker()

    def _render_active_marker(self) -> None:
        day = self._current_day
        if day is None:
            self.day_title.setText("JÍDELNÍČEK VYBRANÉHO DNE")
            return
        active = self._active_meal_type
        allowed = next(
            (meal.allowed_menus for meal in day.meals if meal.meal_type == active),
            (),
        )
        if active is None or not allowed:
            self.day_title.setText(
                f"JÍDELNÍČEK – {day.target_date:%d.%m.%Y}"
            )
            return
        numbers = ", ".join(str(number) for number in allowed)
        self.day_title.setText(
            f"JÍDELNÍČEK – {day.target_date:%d.%m.%Y} · aktivní {active}"
            f" · klávesy {numbers}"
        )

    def _meal_group(self, title: str, meals: list[MealDay]) -> QGroupBox:
        group = QGroupBox(title)
        theme.apply_role(group, TextRole.ACTION)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, theme.SPACING["md"], 0, 0)
        layout.setSpacing(theme.SPACING["sm"])
        ordered_in_group = any(meal.ordered_menu is not None for meal in meals)
        if not any(meal.options for meal in meals):
            layout.addWidget(self._label(self._no_menu_text(meals), TextRole.BODY))
            return group
        for meal in meals:
            # Duplicitní nadpis nemá informaci: skupina jednoho typu už název nese.
            if len(meals) > 1 or meal.meal_type.upper() != title:
                type_label = self._label(
                    meal.meal_type,
                    TextRole.ACTION,
                    "secondary",
                )
                type_label.setObjectName("mealTypeTitle")
                layout.addWidget(type_label)
            if not meal.options:
                layout.addWidget(
                    self._label(self._no_menu_text([meal]), TextRole.BODY)
                )
                continue
            for option in meal.options:
                layout.addWidget(self._menu_row(meal, option, ordered_in_group))
        return group

    def _menu_row(
        self,
        meal: MealDay,
        option: MenuOption,
        ordered_in_group: bool,
    ) -> MenuRow:
        row = MenuRow(
            option.menu,
            option.dish_name,
            option.price,
            ordered=meal.ordered_menu == option.menu,
            published=option.published,
        )
        state = meal.current_state if meal.current_state is not None else "chybí"
        row.set_diagnostic(f"stav: {state}", self.diagnostic_group.isChecked())
        self._state_labels.append(row.diagnostic_label)
        self._configure_menu_row(row, meal, option.menu, ordered_in_group)
        row.activated.connect(
            lambda current_meal=meal, current_option=option, current_row=row: (
                self._selection_clicked(
                    current_meal, current_option, current_row.action_button
                )
            )
        )
        row.action_triggered.connect(
            lambda current_meal=meal, current_option=option, current_row=row: (
                self._selection_clicked(
                    current_meal, current_option, current_row.action_button
                )
            )
        )
        self._menu_rows[(meal.meal_type, option.menu)] = row
        return row

    @staticmethod
    def _no_menu_text(meals: list[MealDay]) -> str:
        if all(meal.allowed_menu_count == 0 for meal in meals):
            return "Pro kategorii strávníka není v public.sazby povoleno žádné menu."
        return "Jídelníček pro tento den není zveřejněn."

    def _configure_menu_row(
        self,
        row: MenuRow,
        meal: MealDay,
        menu: int,
        ordered_in_group: bool,
    ) -> None:
        """Řádek nese jen bezpečný záměr; odhlášení zůstává na tlačítku."""

        action = row.action_button
        try:
            intent = determine_action(meal, menu)
            if Permission.ORDERS_CHANGE not in self._current_policy().permissions:
                raise OrderBusinessError(
                    ErrorCode.OUT_OF_SCOPE_OR_INACTIVE,
                    "Session nemá oprávnění měnit objednávky.",
                )
            action_text = {
                OrderAction.MENU_ADD: "Přihlásit",
                OrderAction.MENU_DELETE: "Odhlásit",
                OrderAction.MENU_CHANGE: "Změnit",
            }[intent]
            if (
                intent is OrderAction.MENU_ADD
                and meal.code in LUNCH_CODES
                and ordered_in_group
            ):
                action_text = "Změnit"
            action.setText(f"{action_text} {menu}")
            action.setProperty(
                "variant",
                "destructive"
                if intent is OrderAction.MENU_DELETE
                else "primary"
                if action_text == "Přihlásit"
                else "secondary",
            )
            tooltip = f"{action_text}: {meal.meal_type}, menu {menu}"
            action.setToolTip(tooltip)
            if intent is OrderAction.MENU_DELETE:
                row.set_clickable(
                    False,
                    f"Objednáno. Odhlásit lze jen tlačítkem Odhlásit {menu}.",
                )
            else:
                row.set_clickable(True, f"Klikněte na řádek: {tooltip}")
        except OrderBusinessError:
            action.setText("Nedostupné")
            action.setEnabled(False)
            action.setProperty("variant", "secondary")
            row.set_clickable(False, "Operace nyní není dostupná.")

    def _selection_clicked(
        self,
        meal: MealDay,
        option: MenuOption,
        button: QPushButton,
    ) -> None:
        day = self._current_day
        if day is None:
            return
        self._set_active_meal_type(meal.meal_type)
        try:
            action = determine_action(meal, option.menu)
        except OrderBusinessError as exc:
            self._show_error(exc)
            return
        if action is OrderAction.MENU_DELETE:
            answer = QMessageBox.question(
                self,
                "Potvrdit odhlášení",
                (
                    f"Opravdu odhlásit {meal.meal_type}, "
                    f"menu {option.menu}?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._mutation_generation += 1
        request_id = self._mutation_generation
        self._mutation_context = (day.diner.evidcislo, day.target_date)
        self._active_write_button = button
        self._active_write_button_text = button.text()
        self._active_write_button_variant = button.property("variant")
        button.setEnabled(False)
        button.setText("Probíhá…")
        button.setProperty("variant", "pending")
        theme.repolish(button)
        for row in self._menu_rows.values():
            row.set_clickable(False, "Probíhá LAB operace…")
        self.statusBar().showMessage("Provádím atomickou LAB operaci…")
        worker = FunctionWorker(
            request_id,
            lambda: self.application_service.execute_selection(
                day.diner.evidcislo,
                day.target_date,
                meal.meal_type,
                option.menu,
            ),
        )
        worker.signals.succeeded.connect(self._mutation_succeeded)
        worker.signals.failed.connect(self._mutation_failed)
        self.thread_pool.start(worker)

    def _mutation_succeeded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._mutation_generation:
            return
        self._restore_write_button()
        self._set_duration("write", duration_ms)
        if not isinstance(result, MutationOutcome):
            return
        context = self._mutation_context
        current_matches = (
            self._current_diner is not None
            and context is not None
            and self._current_diner.evidcislo == context[0]
            and self.date_edit.date().toPython() == context[1]
        )
        if current_matches and result.refreshed is not None:
            self._render_day(result.refreshed)
        elif self._current_diner is not None:
            self._load_current_day()
        if result.error is not None:
            self._record_error(result.error.code)
            SafeErrorDialog(
                "Objednávku nelze dokončit",
                result.error.user_message,
                result.error.code,
                result.error.correlation_id,
                self,
            ).open()
            self.statusBar().showMessage(result.error.user_message)
        elif result.succeeded:
            self.statusBar().showMessage(
                "Operace potvrzena databází a zobrazení obnoveno."
            )
        if result.refresh_error is not None:
            self._record_error(result.refresh_error.code)
            self.statusBar().showMessage(
                "Operace skončila, ale následné načtení selhalo."
            )

    def _mutation_failed(
        self,
        request_id: int,
        error: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._mutation_generation:
            return
        self._restore_write_button()
        self._set_duration("write", duration_ms)
        self._show_error(
            error if isinstance(error, BaseException) else Exception()
        )
        if self._current_diner is not None:
            self._load_current_day()

    def _restore_write_button(self) -> None:
        if self._active_write_button is not None:
            self._active_write_button.setText(self._active_write_button_text)
            self._active_write_button.setEnabled(True)
            self._active_write_button.setProperty(
                "variant",
                self._active_write_button_variant,
            )
            theme.repolish(self._active_write_button)
        self._active_write_button = None

    def _record_error(self, code: str) -> None:
        self._last_error_code = code
        self.diag_error.setText(code)

    def _set_duration(self, kind: str, duration_ms: float) -> None:
        self.diag_duration.setText(f"{kind}: {duration_ms:.1f} ms")

    def _show_error(self, error: BaseException) -> None:
        safe = present_error(error)
        self._record_error(safe.code)
        self.statusBar().showMessage(safe.user_message)
        SafeErrorDialog(
            "Požadavek selhal",
            safe.user_message,
            safe.code,
            safe.correlation_id,
            self,
        ).open()

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                MainWindow._clear_layout(child_layout)
