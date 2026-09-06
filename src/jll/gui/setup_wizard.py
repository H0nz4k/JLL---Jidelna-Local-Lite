"""First-run Setup Wizard – provozovna, stanice a identity bez technického šumu."""

from __future__ import annotations

import logging
from pathlib import Path

import keyring
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
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
from ..identity_store import (
    SHORT_CODE_HINT,
    IdentityStore,
    generate_user_id,
)
from ..permission_catalog import (
    DEFAULT_OPERATOR_PERMISSIONS,
    summarize_permissions,
)
from ..policy import Permission
from ..setup_probe import DatabaseProbe, StationOption, derive_site_id, probe_lab_database
from . import theme
from .permission_list import (
    permission_list_widget,
    selected_permissions_from_list,
)
from .theme import TextRole
from .workers import FunctionWorker

logger = logging.getLogger(__name__)

SUBJECT_MISSING_TEXT = (
    "V databázi chybí název provozovny (parametr BACKUP / NameSubject). "
    "Zadejte jej ručně, nebo doplňte parametr v databázi."
)
NEW_STATION_BLOCKED_TEXT = (
    "Založení nové stanice zatím není povoleno. "
    "Databázový zápis do public.stanice není v JLL bezpečně ověřen. "
    "Vyberte existující stanici ze seznamu."
)
SETUP_FAILED_TEXT = (
    "Nastavení se nepodařilo uložit. "
    "Podrobnosti byly zapsány do diagnostického logu."
)


class SetupWizard(QWizard):
    PAGE_DATABASE = 0
    PAGE_STATION = 1
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
        self._admin_user_id = generate_user_id()
        self._regular_user_id = generate_user_id(
            existing={self._admin_user_id}
        )
        self.setWindowTitle("JidelnaLocalLite – první nastavení")
        self.setWizardStyle(QWizard.ModernStyle)
        self.resize(640, 560)
        self.setButtonText(QWizard.BackButton, "Zpět")
        self.setButtonText(QWizard.NextButton, "Další")
        self.setButtonText(QWizard.FinishButton, "Dokončit")
        self.setButtonText(QWizard.CancelButton, "Zrušit")
        self._database_page()
        self._station_page()
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
        layout = QVBoxLayout(page)
        layout.setSpacing(theme.SPACING["md"])
        return page, layout

    def _database_page(self) -> None:
        page, layout = self._page(
            "1. Databáze",
            "Připojení k lokální LAB databázi. Heslo se neukládá do JSON.",
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
            "Prázdné = environment / keyring / PG auth"
        )
        form.addRow("Host:", self.db_host)
        form.addRow("Port:", self.db_port)
        form.addRow("Databáze:", self.db_name)
        form.addRow("DB uživatel:", self.db_user)
        form.addRow("DB heslo:", self.db_password)
        layout.addLayout(form)
        self.test_database_button = QPushButton("Otestovat spojení")
        theme.apply_role(self.test_database_button, TextRole.ACTION)
        self.test_database_button.setProperty("variant", "primary")
        self.test_database_button.clicked.connect(self._test_database)
        layout.addWidget(self.test_database_button)
        self.database_status = QLabel("Spojení zatím nebylo ověřeno.")
        self.database_status.setWordWrap(True)
        theme.apply_role(self.database_status, TextRole.BODY)
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

    def _station_page(self) -> None:
        page, layout = self._page(
            "2. Provozovna a stanice",
            "Provozovna se načte z databáze. Stanice odpovídá legacy STANICE.",
        )
        form = QFormLayout()
        self.site_name = QLineEdit()
        self.site_name.setReadOnly(True)
        self.site_name.setPlaceholderText("Načte se po ověření databáze")
        form.addRow("Provozovna:", self.site_name)
        self.subject_override = QCheckBox(
            "Zadat název provozovny ručně (jen když chybí v databázi)"
        )
        self.subject_override.toggled.connect(self._toggle_subject_override)
        layout.addLayout(form)
        layout.addWidget(self.subject_override)

        station_row = QHBoxLayout()
        self.station_combo = QComboBox()
        self.station_combo.setMinimumWidth(260)
        station_row.addWidget(self.station_combo, 1)
        self.new_station_button = QPushButton("+ Nová stanice")
        self.new_station_button.setEnabled(False)
        self.new_station_button.setToolTip(NEW_STATION_BLOCKED_TEXT)
        station_row.addWidget(self.new_station_button)
        station_form = QFormLayout()
        station_form.addRow("Stanice:", station_row)
        layout.addLayout(station_form)

        self.station_hint = QLabel(
            "Stanice je stejný pojem jako v JídelnaSQL (např. VEDOUCI). "
            "Interní identifikátor provozovny se generuje automaticky "
            "a v běžném nastavení se nezobrazuje."
        )
        self.station_hint.setWordWrap(True)
        theme.apply_role(self.station_hint, TextRole.META)
        layout.addWidget(self.station_hint)
        layout.addStretch()
        self.addPage(page)

    def _categories_page(self) -> None:
        page, layout = self._page(
            "3. Povolené kategorie",
            "Vyberte kategorie strávníků dostupné na této instalaci.",
        )
        self.categories = QListWidget()
        layout.addWidget(self.categories)
        self.addPage(page)

    def _admin_page(self) -> None:
        page, layout = self._page(
            "4. První administrátor",
            "Administrátor má všechna oprávnění automaticky. PIN se ukládá "
            "jen jako salted Argon2id hash.",
        )
        form = QFormLayout()
        self.admin_name = QLineEdit()
        self.admin_short_code = QLineEdit()
        self.admin_short_code.setPlaceholderText("např. VED")
        self.admin_short_code.setMaxLength(20)
        self.admin_pin = QLineEdit()
        self.admin_pin_confirm = QLineEdit()
        for field in (self.admin_pin, self.admin_pin_confirm):
            field.setEchoMode(QLineEdit.Password)
        form.addRow("Jméno:", self.admin_name)
        form.addRow("Kód uživatele:", self.admin_short_code)
        form.addRow("PIN:", self.admin_pin)
        form.addRow("PIN znovu:", self.admin_pin_confirm)
        layout.addLayout(form)
        hint = QLabel(SHORT_CODE_HINT)
        hint.setWordWrap(True)
        theme.apply_role(hint, TextRole.META)
        layout.addWidget(hint)
        admin_note = QLabel("Administrátor má všechna oprávnění automaticky.")
        admin_note.setWordWrap(True)
        theme.apply_role(admin_note, TextRole.ACTION)
        layout.addWidget(admin_note)
        layout.addStretch()
        self.addPage(page)

    def _users_page(self) -> None:
        page, layout = self._page(
            "5. Další uživatel",
            "Volitelně vytvořte prvního běžného uživatele (např. výdej).",
        )
        self.create_regular_user = QCheckBox("Vytvořit běžného uživatele")
        layout.addWidget(self.create_regular_user)
        form = QFormLayout()
        self.user_name = QLineEdit()
        self.user_short_code = QLineEdit()
        self.user_short_code.setPlaceholderText("např. SUP")
        self.user_short_code.setMaxLength(20)
        self.user_pin = QLineEdit()
        self.user_pin.setEchoMode(QLineEdit.Password)
        form.addRow("Jméno:", self.user_name)
        form.addRow("Kód uživatele:", self.user_short_code)
        form.addRow("PIN:", self.user_pin)
        layout.addLayout(form)
        hint = QLabel(SHORT_CODE_HINT)
        hint.setWordWrap(True)
        theme.apply_role(hint, TextRole.META)
        layout.addWidget(hint)
        self.create_regular_user.toggled.connect(self._toggle_regular_user)
        self.create_regular_user.setChecked(False)
        self._toggle_regular_user(False)
        layout.addStretch()
        self.addPage(page)

    def _permissions_page(self) -> None:
        page, layout = self._page(
            "6. Oprávnění",
            "Nastavte oprávnění běžného uživatele. Administrátor má všechna "
            "automaticky.",
        )
        note = QLabel(
            "Oprávnění říká, co smí uživatel v JLL použít. "
            "Některé zápisy mohou být i při oprávnění blokované, "
            "dokud není ověřen databázový kontrakt."
        )
        note.setWordWrap(True)
        theme.apply_role(note, TextRole.META)
        layout.addWidget(note)
        self.permission_list = permission_list_widget(
            defaults=DEFAULT_OPERATOR_PERMISSIONS,
            include_admin=False,
        )
        layout.addWidget(self.permission_list)
        self.addPage(page)

    def _summary_page(self) -> None:
        page, layout = self._page(
            "7. Souhrn",
            "Kontrola před uložením. Produkční databáze není povolena.",
        )
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        theme.apply_role(self.summary, TextRole.BODY)
        layout.addWidget(self.summary)
        layout.addStretch()
        self.addPage(page)

    def _toggle_subject_override(self, enabled: bool) -> None:
        self.site_name.setReadOnly(not enabled)
        if enabled:
            self.site_name.setFocus()

    def _toggle_regular_user(self, enabled: bool) -> None:
        for widget in (
            self.user_name,
            self.user_short_code,
            self.user_pin,
        ):
            widget.setEnabled(enabled)

    def _invalidate_database_probe(self) -> None:
        self.database_probe = None
        self.database_status.setText("Spojení zatím nebylo ověřeno.")
        self.database_status.setProperty("tone", None)
        theme.repolish(self.database_status)

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
        return probe_lab_database(
            raw_host,
            int(raw_port),
            database,
            user,
            password,
        )

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
            self.database_status.setText(
                "Údaje se změnily; otestujte spojení znovu."
            )
            return
        self.database_probe = result
        if result.subject_name:
            self.site_name.setText(result.subject_name)
            self.site_name.setReadOnly(True)
            self.subject_override.setChecked(False)
            self.subject_override.setEnabled(False)
            self.database_status.setText(
                f"Databáze ověřena.\nProvozovna: {result.subject_name}"
            )
            self.database_status.setProperty("tone", "ordered")
        else:
            self.site_name.clear()
            self.site_name.setReadOnly(False)
            self.subject_override.setChecked(True)
            self.subject_override.setEnabled(True)
            self.database_status.setText(
                "Databáze ověřena, ale chybí název provozovny.\n"
                + SUBJECT_MISSING_TEXT
            )
            self.database_status.setProperty("tone", "danger")
        theme.repolish(self.database_status)
        self._fill_stations(result.stations)
        self._fill_categories(result.categories)

    def _fill_stations(self, stations: tuple[StationOption, ...]) -> None:
        self.station_combo.clear()
        preferred = (
            self.initial_config.instance_id.upper()
            if self.initial_config
            else ""
        )
        usable = [item for item in stations if item.usable_as_instance_id]
        if not usable:
            self.station_combo.addItem(
                "V databázi nejsou použitelné stanice",
                None,
            )
            self.station_combo.setEnabled(False)
            return
        self.station_combo.setEnabled(True)
        selected_index = 0
        for index, station in enumerate(usable):
            self.station_combo.addItem(station.name, station.name)
            if preferred and station.name == preferred:
                selected_index = index
        self.station_combo.setCurrentIndex(selected_index)

    def _fill_categories(self, categories: tuple[str, ...]) -> None:
        self.categories.clear()
        selected = (
            self.initial_config.allowed_categories if self.initial_config else set()
        )
        labels = {
            item.code: item.label
            for item in (
                self.database_probe.category_options if self.database_probe else ()
            )
        }
        for category in categories:
            item = QListWidgetItem(labels.get(category, category))
            item.setData(Qt.UserRole, category)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if category in selected else Qt.Unchecked
            )
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
        self.database_status.setProperty("tone", "danger")
        theme.repolish(self.database_status)
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Databázi se nepodařilo ověřit. Zkontrolujte údaje a zkuste to znovu."
        )
        if not isinstance(error, ValueError):
            logger.exception("Setup database probe failed: %s", error)
        QMessageBox.warning(self, "Databázi nelze ověřit", message)

    def selected_categories(self) -> frozenset[str]:
        result: list[str] = []
        for index in range(self.categories.count()):
            item = self.categories.item(index)
            if item.checkState() != Qt.Checked:
                continue
            code = item.data(Qt.UserRole)
            result.append(str(code) if code else item.text())
        return frozenset(result)

    def selected_permissions(self) -> frozenset[Permission]:
        return selected_permissions_from_list(self.permission_list)

    def selected_station(self) -> str | None:
        data = self.station_combo.currentData()
        return str(data) if data else None

    def validateCurrentPage(self) -> bool:
        page_id = self.currentId()
        try:
            if page_id == self.PAGE_DATABASE and self.database_probe is None:
                raise ValueError("Nejprve úspěšně otestujte databázi.")
            if page_id == self.PAGE_STATION:
                if not self.site_name.text().strip():
                    raise ValueError(
                        "Název provozovny chybí. Doplňte jej, nebo opravte "
                        "parametr NameSubject v databázi."
                    )
                station = self.selected_station()
                if not station:
                    raise ValueError("Vyberte existující stanici.")
                if not IDENTIFIER_PATTERN.fullmatch(station):
                    raise ValueError(
                        "Zvolená stanice nemá formát použitelný jako "
                        "identita JLL stanice."
                    )
            elif page_id == self.PAGE_CATEGORIES and not self.selected_categories():
                raise ValueError("Vyberte alespoň jednu povolenou kategorii.")
            elif page_id == self.PAGE_ADMIN:
                if self.admin_pin.text() != self.admin_pin_confirm.text():
                    raise ValueError("PIN administrátora se neshoduje.")
                self._validate_user_fields(
                    self.admin_name.text(),
                    self.admin_short_code.text(),
                    self.admin_pin.text(),
                )
            elif page_id == self.PAGE_USERS and self.create_regular_user.isChecked():
                self._validate_user_fields(
                    self.user_name.text(),
                    self.user_short_code.text(),
                    self.user_pin.text(),
                )
                if (
                    self.user_short_code.text().strip().upper()
                    == self.admin_short_code.text().strip().upper()
                ):
                    raise ValueError("Kód uživatele musí být unikátní.")
            elif (
                page_id == self.PAGE_PERMISSIONS
                and self.create_regular_user.isChecked()
                and not self.selected_permissions()
            ):
                raise ValueError(
                    "Vyberte alespoň jedno oprávnění pro běžného uživatele."
                )
            elif page_id == self.PAGE_SUMMARY:
                self._complete_setup()
        except ValueError as exc:
            QMessageBox.warning(self, "Nastavení nelze dokončit", str(exc))
            return False
        except Exception:
            logger.exception("Setup validation/complete failed")
            QMessageBox.warning(self, "Nastavení nelze dokončit", SETUP_FAILED_TEXT)
            return False
        return super().validateCurrentPage()

    @staticmethod
    def _validate_user_fields(name: str, short_code: str, pin: str) -> None:
        if not name.strip():
            raise ValueError("Vyplňte jméno uživatele.")
        code = short_code.strip().upper()
        if not IDENTIFIER_PATTERN.fullmatch(code):
            raise ValueError(
                "Kód uživatele musí mít 1–20 znaků (písmena, čísla, _ nebo -)."
            )
        if len(pin) < 4:
            raise ValueError("PIN musí mít alespoň 4 znaky.")

    def _build_config(self) -> LabConfig:
        if self.database_probe is None:
            raise ValueError("Databáze není ověřena.")
        station = self.selected_station()
        if not station:
            raise ValueError("Vyberte existující stanici.")
        site_name = self.site_name.text().strip()
        return LabConfig(
            site_name=site_name,
            site_id=derive_site_id(site_name),
            instance_id=station,
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
            reader_port=(
                self.initial_config.reader_port if self.initial_config else None
            ),
            reader_baud_rate=(
                self.initial_config.reader_baud_rate if self.initial_config else 19_200
            ),
            reader_line_end=(
                self.initial_config.reader_line_end if self.initial_config else "\r"
            ),
        )

    def _page_changed(self, page_id: int) -> None:
        if page_id == self.PAGE_PERMISSIONS:
            self.permission_list.setEnabled(self.create_regular_user.isChecked())
            return
        if page_id != self.PAGE_SUMMARY:
            return
        permissions_text = (
            summarize_permissions(self.selected_permissions())
            if self.create_regular_user.isChecked()
            else "nevytváří se"
        )
        regular = (
            f"{self.user_name.text().strip()} ({self.user_short_code.text().strip().upper()})"
            if self.create_regular_user.isChecked()
            else "nevytváří se"
        )
        self.summary.setText(
            "Databáze\n"
            f"{self.db_host.text()}:{self.db_port.text()} / {self.db_name.text()}\n\n"
            "Provozovna\n"
            f"{self.site_name.text().strip()}\n\n"
            "Stanice\n"
            f"{self.selected_station() or '—'}\n\n"
            "Povolené kategorie\n"
            f"{', '.join(sorted(self.selected_categories()))}\n\n"
            "Administrátor\n"
            f"{self.admin_name.text().strip()} ({self.admin_short_code.text().strip().upper()})\n\n"
            "Běžný uživatel\n"
            f"{regular}\n\n"
            "Oprávnění běžného uživatele\n"
            f"{permissions_text}"
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
                self._admin_user_id,
                self.admin_name.text().strip(),
                self.admin_short_code.text().strip().upper(),
                self.admin_pin.text(),
                admin_permissions,
            )
        ]
        if self.create_regular_user.isChecked():
            users.append(
                (
                    self._regular_user_id,
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
