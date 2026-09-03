"""Detailní read-only karta strávníka a náhledy zápisových formulářů.

Karta zobrazuje jen doložené sloupce. Tajné hodnoty (PIN), rodné číslo ani
kontaktní údaje se z databáze vůbec nečtou. Formuláře pro editaci a nového
strávníka jsou pouze náhledy: `Uložit` je zakázané, dokud příslušný write
gate není `PROVEN`.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..policy import Permission, SessionPolicy
from ..read_models import DinerProfile
from ..read_service import OrderReadService
from ..write_gates import DINER_WRITE_GATES, WriteGate
from . import theme
from .menu_row import format_money
from .theme import TextRole
from .workers import FunctionWorker

UNKNOWN_VALUE = "—"

SAVE_BLOCKED_TEXT = (
    "Uložení je bezpečnostně blokované. Formulář slouží jen jako náhled "
    "polí; JidelnaLocalLite v tomto stavu do databáze nezapisuje."
)


def format_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value is not None else UNKNOWN_VALUE


def _text(value: str | None) -> str:
    return value if value else UNKNOWN_VALUE


class DinerFormDialog(QDialog):
    """Náhled formuláře strávníka bez možnosti zápisu."""

    def __init__(
        self,
        gate: WriteGate,
        *,
        title: str,
        profile: DinerProfile | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.gate = gate
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING["md"])

        banner = QLabel(SAVE_BLOCKED_TEXT)
        banner.setWordWrap(True)
        banner.setProperty("tone", "danger")
        theme.apply_role(banner, TextRole.ACTION)
        layout.addWidget(banner)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.fields: dict[str, QLineEdit] = {}
        for key, label, value in (
            ("name", "Jméno:", profile.name if profile else ""),
            (
                "evidcislo",
                "Evidenční číslo:",
                str(profile.evidcislo) if profile else "",
            ),
            ("category", "Kategorie:", profile.category if profile else ""),
            ("class_name", "Třída:", profile.class_name if profile else ""),
            (
                "birth_date",
                "Datum narození:",
                format_date(profile.birth_date) if profile else "",
            ),
            (
                "variable_symbol",
                "Variabilní symbol:",
                (profile.variable_symbol or "") if profile else "",
            ),
            (
                "payment_method",
                "Způsob platby:",
                (profile.payment_method or "") if profile else "",
            ),
            ("note", "Poznámka:", (profile.note or "") if profile else ""),
        ):
            field = QLineEdit(value)
            field.setReadOnly(True)
            theme.apply_role(field, TextRole.BODY)
            self.fields[key] = field
            form.addRow(label, field)
        layout.addWidget(form_host)

        if profile is None:
            hint = QLabel(
                "Evidenční číslo nového strávníka nelze bezpečně přidělit. "
                "Odvození z MAX(evidcislo)+1 není doložené jako bezpečné."
            )
            hint.setWordWrap(True)
            theme.apply_role(hint, TextRole.META)
            layout.addWidget(hint)

        reason = QLabel(gate.tooltip)
        reason.setWordWrap(True)
        theme.apply_role(reason, TextRole.META)
        layout.addWidget(reason)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.save_button = QPushButton("Uložit")
        theme.apply_role(self.save_button, TextRole.ACTION)
        self.save_button.setProperty("variant", "primary")
        self.save_button.setEnabled(gate.enabled)
        self.save_button.setToolTip(gate.tooltip)
        buttons.addWidget(self.save_button)
        self.close_button = QPushButton("Zavřít")
        theme.apply_role(self.close_button, TextRole.ACTION)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)


class DinerCardDialog(QDialog):
    """Karta strávníka: Údaje, Finance a Čipy v read-only režimu."""

    def __init__(
        self,
        service: OrderReadService,
        evidcislo: int,
        policy: SessionPolicy,
        *,
        highlight_chip: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.evidcislo = evidcislo
        self.policy = policy
        self.highlight_chip = highlight_chip
        self.profile: DinerProfile | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._generation = 0

        self.setWindowTitle("Karta strávníka")
        self.resize(660, 620)
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING["md"])

        self.name_label = QLabel("Načítám…")
        theme.apply_role(self.name_label, TextRole.PRIMARY)
        layout.addWidget(self.name_label)
        self.meta_label = QLabel(UNKNOWN_VALUE)
        theme.apply_role(self.meta_label, TextRole.META)
        layout.addWidget(self.meta_label)
        self.status_label = QLabel("Načítám detail z LAB databáze…")
        self.status_label.setWordWrap(True)
        theme.apply_role(self.status_label, TextRole.META)
        layout.addWidget(self.status_label)

        self.details_group = QGroupBox("Údaje")
        theme.apply_role(self.details_group, TextRole.ACTION)
        self.details_form = QFormLayout(self.details_group)
        self.detail_fields: dict[str, QLabel] = {}
        for key, caption in (
            ("evidcislo", "Evidenční číslo:"),
            ("category", "Kategorie:"),
            ("norm", "Norma kategorie:"),
            ("class_name", "Třída:"),
            ("birth_date", "Datum narození:"),
            ("variable_symbol", "Variabilní symbol:"),
            ("payment_method", "Způsob platby:"),
            ("state", "Stav:"),
            ("note", "Poznámka:"),
        ):
            value_label = QLabel(UNKNOWN_VALUE)
            value_label.setWordWrap(True)
            theme.apply_role(value_label, TextRole.BODY)
            caption_label = QLabel(caption)
            theme.apply_role(caption_label, TextRole.META)
            self.detail_fields[key] = value_label
            self.details_form.addRow(caption_label, value_label)
        layout.addWidget(self.details_group)

        self.finance_group = QGroupBox("Finance")
        theme.apply_role(self.finance_group, TextRole.ACTION)
        finance_form = QFormLayout(self.finance_group)
        self.finance_fields: dict[str, QLabel] = {}
        for key, caption in (
            ("credit", "Disponibilní kredit:"),
            ("minimum", "Minimální povolený zůstatek:"),
            ("headroom", "Zbývá do limitu:"),
        ):
            value_label = QLabel(UNKNOWN_VALUE)
            theme.apply_role(
                value_label,
                TextRole.ACTION if key == "credit" else TextRole.BODY,
            )
            caption_label = QLabel(caption)
            theme.apply_role(caption_label, TextRole.META)
            self.finance_fields[key] = value_label
            finance_form.addRow(caption_label, value_label)
        finance_note = QLabel(
            "Zobrazují se jen hodnoty s doloženým významem. Další finanční "
            "sloupce nejsou interpretačně doložené, proto se neuvádějí."
        )
        finance_note.setWordWrap(True)
        theme.apply_role(finance_note, TextRole.META)
        finance_form.addRow(finance_note)
        layout.addWidget(self.finance_group)

        self.chips_group = QGroupBox("Čipy")
        theme.apply_role(self.chips_group, TextRole.ACTION)
        chips_layout = QVBoxLayout(self.chips_group)
        self.chips_table = QTableWidget(0, 2)
        self.chips_table.setHorizontalHeaderLabels(["Kód čipu", "Stav"])
        self.chips_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.chips_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.chips_table.verticalHeader().setVisible(False)
        self.chips_table.horizontalHeader().setStretchLastSection(True)
        self.chips_table.setMaximumHeight(150)
        chips_layout.addWidget(self.chips_table)
        self.chips_note = QLabel(
            "Čipy jsou pouze pro čtení. Změny stavu čipu nemají doložený "
            "write kontrakt."
        )
        self.chips_note.setWordWrap(True)
        theme.apply_role(self.chips_note, TextRole.META)
        chips_layout.addWidget(self.chips_note)
        self.chips_group.setVisible(Permission.CHIPS_VIEW in policy.permissions)
        layout.addWidget(self.chips_group)

        layout.addStretch()
        footer = QHBoxLayout()
        self.edit_preview_button = QPushButton("Náhled editace strávníka")
        theme.apply_role(self.edit_preview_button, TextRole.ACTION)
        self.edit_preview_button.setToolTip(
            DINER_WRITE_GATES["edit_personal"].tooltip
        )
        self.edit_preview_button.clicked.connect(self._open_edit_preview)
        self.edit_preview_button.setVisible(
            Permission.DINERS_EDIT in policy.permissions
        )
        footer.addWidget(self.edit_preview_button)
        self.create_preview_button = QPushButton("Náhled nového strávníka")
        theme.apply_role(self.create_preview_button, TextRole.ACTION)
        self.create_preview_button.setToolTip(
            DINER_WRITE_GATES["create"].tooltip
        )
        self.create_preview_button.clicked.connect(self._open_create_preview)
        self.create_preview_button.setVisible(
            Permission.DINERS_CREATE in policy.permissions
        )
        footer.addWidget(self.create_preview_button)
        footer.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)

        self.reload()

    def reload(self) -> None:
        self._generation += 1
        request_id = self._generation
        evidcislo = self.evidcislo
        service = self.service
        worker = FunctionWorker(
            request_id,
            lambda: service.load_diner_profile(evidcislo),
        )
        worker.signals.succeeded.connect(self._loaded)
        worker.signals.failed.connect(self._load_failed)
        self.thread_pool.start(worker)

    def _loaded(
        self,
        request_id: int,
        result: object,
        duration_ms: float,
    ) -> None:
        if request_id != self._generation or not isinstance(
            result, DinerProfile
        ):
            return
        self.render(result)
        self.status_label.setText(
            f"Načteno z LAB databáze za {duration_ms:.0f} ms."
        )

    def _load_failed(
        self,
        request_id: int,
        error: object,
        _duration_ms: float,
    ) -> None:
        if request_id != self._generation:
            return
        self.name_label.setText("Detail není dostupný")
        self.status_label.setText(
            "Detail strávníka nelze bezpečně načíst. "
            f"Důvod: {error}"
        )
        self.status_label.setProperty("tone", "danger")
        theme.repolish(self.status_label)

    def render(self, profile: DinerProfile) -> None:
        self.profile = profile
        self.name_label.setText(profile.name)
        category_label = (
            f"{profile.category} – {profile.category_name}"
            if profile.category_name
            else profile.category
        )
        self.meta_label.setText(
            " · ".join(
                part
                for part in (
                    category_label,
                    f"třída {profile.class_name}" if profile.class_name else None,
                    f"ev. č. {profile.evidcislo}",
                )
                if part
            )
        )
        self.detail_fields["evidcislo"].setText(str(profile.evidcislo))
        self.detail_fields["category"].setText(category_label)
        self.detail_fields["norm"].setText(_text(profile.category_norm))
        self.detail_fields["class_name"].setText(_text(profile.class_name))
        self.detail_fields["birth_date"].setText(
            format_date(profile.birth_date)
        )
        self.detail_fields["variable_symbol"].setText(
            _text(profile.variable_symbol)
        )
        self.detail_fields["payment_method"].setText(
            _text(profile.payment_method)
        )
        self.detail_fields["state"].setText(profile.state_label)
        self.detail_fields["note"].setText(_text(profile.note))

        self.finance_fields["credit"].setText(
            format_money(profile.finance.available_credit)
        )
        self.finance_fields["minimum"].setText(
            format_money(profile.finance.minimum_balance)
        )
        self.finance_fields["headroom"].setText(
            format_money(profile.finance.headroom)
        )

        self.chips_table.setRowCount(len(profile.chips))
        for row, chip in enumerate(profile.chips):
            code_item = QTableWidgetItem(chip.code)
            status_item = QTableWidgetItem(chip.status_label)
            if self.highlight_chip and chip.code == self.highlight_chip:
                for item in (code_item, status_item):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                code_item.setToolTip("Právě identifikovaný čip")
            self.chips_table.setItem(row, 0, code_item)
            self.chips_table.setItem(row, 1, status_item)
        if not profile.chips:
            self.chips_note.setText("Strávník nemá žádný evidovaný čip.")

    def _open_edit_preview(self) -> None:
        dialog = DinerFormDialog(
            DINER_WRITE_GATES["edit_personal"],
            title="Editace strávníka – náhled",
            profile=self.profile,
            parent=self,
        )
        dialog.exec()

    def _open_create_preview(self) -> None:
        dialog = DinerFormDialog(
            DINER_WRITE_GATES["create"],
            title="Nový strávník – náhled",
            profile=None,
            parent=self,
        )
        dialog.exec()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
