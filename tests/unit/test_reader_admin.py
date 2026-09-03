"""Administrace čtečky: enumerace portů, oprávnění, reauth a uložení."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher, Type

from jll.admin_service import AdminReauthenticationRequired, AdminService
from jll.chip_reader import (
    SerialLineChipReader,
    UnavailableChipReader,
    available_serial_ports,
    build_chip_reader,
)
from jll.chip_reader import list_ports as reader_list_ports
from jll.config import LabConfig, load_lab_config, save_lab_config
from jll.gui.admin_dialog import BAUD_RATES, AdminDialog, reader_state_label
from jll.chip_reader import FakeChipReader, ReaderState
from jll.identity_store import IdentityStore
from jll.orders.errors import OrderBusinessError
from jll.policy import Permission
from jll.session import AuthService, SessionManager


def fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
        hash_len=16,
        salt_len=16,
        type=Type.ID,
    )


def config(reader_port: str | None = None) -> LabConfig:
    return LabConfig(
        site_name="DEMO LAB",
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        allowed_categories=frozenset({"KAT2"}),
        host="127.0.0.1",
        port=5433,
        database="jll_test",
        user="postgres",
        environment="lab",
        expected_system_identifier="1000000000000000001",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
        reader_port=reader_port,
    )


class _Port:
    def __init__(self, device: str, description: str | None = None) -> None:
        self.device = device
        self.description = description
        self.manufacturer = None


def admin_service(
    tmp_path: Path,
    permissions: frozenset[Permission],
    *,
    lab_config: LabConfig | None = None,
    config_path: Path | None = None,
) -> AdminService:
    store = IdentityStore(tmp_path / "users.json", password_hasher=fast_hasher())
    store.initialize(
        [("admin", "LAB Admin", "ADM", "2468", permissions)]
    )
    lab = lab_config or config()
    session = SessionManager(lab, store)
    session.start(store.get_user("admin"))
    return AdminService(
        session,
        AuthService(store),
        store,
        lab_config=lab,
        config_path=config_path,
    )


def test_com_ports_come_from_operating_system_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reader_list_ports,
        "comports",
        lambda: [_Port("COM9", "Serial reader"), _Port("COM3"), _Port(" ")],
    )
    options = available_serial_ports()
    assert [option.device for option in options] == ["COM3", "COM9"]
    assert options[1].label == "COM9 — Serial reader"


def test_reader_is_never_built_without_configured_port() -> None:
    assert isinstance(build_chip_reader(None), UnavailableChipReader)
    assert isinstance(build_chip_reader("   "), UnavailableChipReader)
    reader = build_chip_reader("COM7", baud_rate=9_600, line_end="\r\n")
    assert isinstance(reader, SerialLineChipReader)
    assert (reader.port, reader.baud_rate, reader.line_end) == (
        "COM7",
        9_600,
        b"\r\n",
    )


def test_invalid_reader_settings_stay_unavailable_instead_of_crashing() -> None:
    reader = build_chip_reader("COM7", baud_rate=0)
    assert isinstance(reader, UnavailableChipReader)
    assert "není platné" in reader.reason


def test_reader_state_labels_are_human_czech() -> None:
    assert reader_state_label(ReaderState.READY) == "Připojena"
    assert reader_state_label(ReaderState.DISCONNECTED) == "Nepřipojena"
    assert reader_state_label(ReaderState.ERROR) == "Chyba"


def test_reader_diagnostics_requires_admin_reader_permission(
    tmp_path: Path,
) -> None:
    service = admin_service(
        tmp_path,
        frozenset({Permission.ADMIN_USERS, Permission.ADMIN_PERMISSIONS}),
    )
    service.reauthenticate("2468")
    with pytest.raises(OrderBusinessError):
        service.require_reader_diagnostics()


def test_reader_settings_require_reauthentication(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    save_lab_config(config(), path)
    service = admin_service(
        tmp_path,
        frozenset(Permission),
        config_path=path,
    )
    with pytest.raises(AdminReauthenticationRequired):
        service.save_reader_settings(
            port="COM5",
            baud_rate=19_200,
            line_end="\r",
        )
    assert load_lab_config(path).reader_port is None


def test_reader_settings_save_only_to_local_installation_config(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lab.json"
    save_lab_config(config(), path)
    service = admin_service(
        tmp_path,
        frozenset(Permission),
        config_path=path,
    )
    service.reauthenticate("2468")
    updated = service.save_reader_settings(
        port="COM5",
        baud_rate=115_200,
        line_end="\r\n",
    )
    assert (updated.reader_port, updated.reader_baud_rate) == ("COM5", 115_200)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["reader_port"] == "COM5"
    assert stored["reader_baud_rate"] == 115_200
    assert stored["reader_line_end"] == "\r\n"
    # Instalační identita ani databáze se nastavením čtečky nemění.
    assert stored["database"] == "jll_test"
    assert stored["instance_id"] == "DEMO-LAB01"


def test_reader_settings_reject_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    save_lab_config(config(), path)
    service = admin_service(
        tmp_path,
        frozenset(Permission),
        config_path=path,
    )
    service.reauthenticate("2468")
    with pytest.raises(ValueError):
        service.save_reader_settings(port="COM5", baud_rate=0, line_end="\r")
    assert load_lab_config(path).reader_port is None


def test_reader_settings_are_read_only_without_installation_config(
    tmp_path: Path,
) -> None:
    service = admin_service(tmp_path, frozenset(Permission))
    assert not service.reader_settings_writable
    service.reauthenticate("2468")
    with pytest.raises(RuntimeError):
        service.save_reader_settings(
            port="COM5",
            baud_rate=19_200,
            line_end="\r",
        )


def test_admin_reader_tab_offers_ports_baudrate_and_test(
    qtbot: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reader_list_ports,
        "comports",
        lambda: [_Port("COM4", "Serial reader")],
    )
    path = tmp_path / "lab.json"
    lab = config("COM4")
    save_lab_config(lab, path)
    service = admin_service(
        tmp_path,
        frozenset(Permission),
        lab_config=lab,
        config_path=path,
    )
    service.reauthenticate("2468")
    reader = FakeChipReader(["0000000000098765"])
    dialog = AdminDialog(lab, service, reader)
    qtbot.addWidget(dialog)

    assert dialog.reader_port.currentData() == "COM4"
    assert dialog.reader_baud.currentData() == lab.reader_baud_rate
    assert dialog.reader_baud.count() == len(BAUD_RATES)
    assert dialog.reader_line_end.currentData() == "\r"
    assert dialog.reader_save_button.isEnabled()
    assert dialog.reader_test_button.isEnabled()
    assert "Nepřipojena" in dialog.reader_status.text()


def test_admin_reader_tab_keeps_configured_port_when_unplugged(
    qtbot: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader_list_ports, "comports", lambda: [])
    lab = config("COM12")
    service = admin_service(tmp_path, frozenset(Permission), lab_config=lab)
    service.reauthenticate("2468")
    dialog = AdminDialog(lab, service, FakeChipReader())
    qtbot.addWidget(dialog)

    assert dialog.reader_port.currentData() == "COM12"
    assert "nedostupný" in dialog.reader_port.currentText()
    assert not dialog.reader_save_button.isEnabled()
