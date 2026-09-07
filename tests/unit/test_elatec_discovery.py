"""Unit tests for ELATEC discovery and auto reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jll.chip_reader import (
    AutoElatecChipReader,
    ChipReaderTimeout,
    ReaderState,
    UnavailableChipReader,
    build_chip_reader,
)
import jll.chip_reader as reader_module
from jll.config import LabConfig, load_lab_config, save_lab_config
from jll.reader_discovery import (
    ReaderDiscoveryStatus,
    is_elatec_port,
    select_elatec_reader,
)


class _FakePort:
    def __init__(
        self,
        device: str,
        *,
        manufacturer: str | None = None,
        description: str | None = None,
        product: str | None = None,
        serial_number: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
        hwid: str | None = None,
    ) -> None:
        self.device = device
        self.manufacturer = manufacturer
        self.description = description
        self.product = product
        self.serial_number = serial_number
        self.vid = vid
        self.pid = pid
        self.hwid = hwid
        self.location = None


def test_is_elatec_by_manufacturer_casefold() -> None:
    assert is_elatec_port(_FakePort("COM7", manufacturer="Elatec"))
    assert is_elatec_port(_FakePort("COM7", manufacturer="ELATEC GmbH"))
    assert not is_elatec_port(_FakePort("COM7", manufacturer="Microsoft"))
    assert not is_elatec_port(
        _FakePort("COM7", manufacturer="Other", description="Serial RFID Device")
    )


def test_is_elatec_by_hil_vid_pid() -> None:
    assert is_elatec_port(_FakePort("COM7", vid=0x09D8, pid=0x0420))
    assert is_elatec_port(
        _FakePort("COM7", hwid="USB VID:PID=09D8:0420 SER= LOCATION=1-1")
    )


def test_select_found_single() -> None:
    ports = [_FakePort("COM7", manufacturer="Elatec", description="Serial RFID Device")]
    result = select_elatec_reader(port_lister=lambda: ports)
    assert result.status is ReaderDiscoveryStatus.FOUND
    assert result.selected is not None
    assert result.selected.device == "COM7"


def test_select_not_found() -> None:
    ports = [_FakePort("COM3", manufacturer="Microsoft")]
    result = select_elatec_reader(port_lister=lambda: ports)
    assert result.status is ReaderDiscoveryStatus.NOT_FOUND


def test_select_ambiguous_without_serial() -> None:
    ports = [
        _FakePort("COM7", manufacturer="Elatec", serial_number="A"),
        _FakePort("COM8", manufacturer="Elatec", serial_number="B"),
    ]
    result = select_elatec_reader(port_lister=lambda: ports)
    assert result.status is ReaderDiscoveryStatus.AMBIGUOUS


def test_select_preferred_serial() -> None:
    ports = [
        _FakePort("COM7", manufacturer="Elatec", serial_number="AAA"),
        _FakePort("COM11", manufacturer="Elatec", serial_number="BBB"),
    ]
    result = select_elatec_reader(
        preferred_serial="BBB",
        port_lister=lambda: ports,
    )
    assert result.status is ReaderDiscoveryStatus.FOUND
    assert result.selected is not None
    assert result.selected.device == "COM11"


def test_build_auto_reader_without_port() -> None:
    reader = build_chip_reader(None, mode="auto_elatec")
    assert isinstance(reader, AutoElatecChipReader)


def test_build_manual_without_port_unavailable() -> None:
    reader = build_chip_reader(None, mode="manual")
    assert isinstance(reader, UnavailableChipReader)


def test_auto_reader_com_reassignment(monkeypatch: pytest.MonkeyPatch) -> None:
    waves = [
        [_FakePort("COM7", manufacturer="Elatec")],
        [],
        [_FakePort("COM11", manufacturer="Elatec")],
    ]
    index = {"i": 0}

    def _lister():
        i = min(index["i"], len(waves) - 1)
        return waves[i]

    class _Serial:
        def __init__(self, port, *_args, **_kwargs) -> None:
            self.port = port
            self.data = iter(b"112233\r")

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return bytes((next(self.data),))

    monkeypatch.setattr(reader_module.serial, "Serial", _Serial)
    monkeypatch.setattr(reader_module.list_ports, "comports", _lister)
    reader = AutoElatecChipReader(port_lister=_lister, rediscovery_seconds=1.0)
    reader.start()
    assert reader.device_info().port == "COM7"
    assert reader.status().state is ReaderState.READY

    index["i"] = 1
    assert reader.status().state is ReaderState.DISCONNECTED

    index["i"] = 2
    assert reader.device_info().port == "COM11"
    result = reader.read_once(timeout_seconds=0.5)
    assert result.code.endswith("112233")
    assert result.device.port == "COM11"
    reader.stop()


def test_legacy_config_with_port_loads_as_manual(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    path.write_text(
        json.dumps(
            {
                "site_name": "DEMO",
                "site_id": "DEMO",
                "instance_id": "DEMO-LAB01",
                "allowed_categories": ["KAT2"],
                "host": "127.0.0.1",
                "port": 5433,
                "database": "jll_test",
                "user": "postgres",
                "environment": "lab",
                "expected_system_identifier": "1000000000000000001",
                "business_timezone": "Europe/Prague",
                "strict_config_lock": True,
                "reader_port": "COM7",
            }
        ),
        encoding="utf-8",
    )
    cfg = load_lab_config(path)
    assert cfg.reader_mode == "manual"
    assert cfg.reader_port == "COM7"


def test_new_config_defaults_auto(tmp_path: Path) -> None:
    cfg = LabConfig(
        site_name="DEMO",
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
    )
    assert cfg.reader_mode == "auto_elatec"
    path = tmp_path / "out.json"
    save_lab_config(cfg, path)
    reloaded = load_lab_config(path)
    assert reloaded.reader_mode == "auto_elatec"


def test_invalid_reader_mode_fail_closed() -> None:
    with pytest.raises(ValueError, match="reader_mode"):
        LabConfig(
            site_name="DEMO",
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
            reader_mode="guess",
        )
