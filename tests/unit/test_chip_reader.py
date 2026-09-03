from __future__ import annotations

import threading

import pytest

from jll.chip_reader import (
    ChipReaderCancelled,
    ChipReaderError,
    ChipReaderTimeout,
    FakeChipReader,
    ReaderState,
    SerialLineChipReader,
    masked_chip_summary,
)
import jll.chip_reader as reader_module


def test_fake_reader_lifecycle_and_read() -> None:
    reader = FakeChipReader(["12345678"])
    assert reader.status().state is ReaderState.STOPPED
    reader.start()
    assert reader.status().state is ReaderState.READY
    result = reader.read_once(timeout_seconds=0.2)
    assert result.code == "12345678"
    assert result.device.adapter == "fake"
    assert reader.status().last_read_at == result.read_at
    reader.stop()
    assert reader.status().state is ReaderState.STOPPED


def test_fake_reader_duplicate_debounce_and_timeout() -> None:
    reader = FakeChipReader(
        ["1234", "1234"],
        duplicate_debounce_seconds=1,
    )
    reader.start()
    assert reader.read_once(timeout_seconds=0.2).code == "1234"
    with pytest.raises(ChipReaderTimeout):
        reader.read_once(timeout_seconds=0.05)


def test_fake_reader_cancellation_and_stopped_guard() -> None:
    reader = FakeChipReader()
    with pytest.raises(ChipReaderError):
        reader.read_once(timeout_seconds=0.1)
    reader.start()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ChipReaderCancelled):
        reader.read_once(timeout_seconds=0.2, cancel_event=cancelled)


def test_reader_masks_last_read_in_diagnostics() -> None:
    assert masked_chip_summary(None) == "žádné načtení"
    assert masked_chip_summary("12345678") == "••••5678"
    assert masked_chip_summary("1234") == "••••"


class _Port:
    device = "COM7"
    manufacturer = "Reference"
    product = "Serial reader"
    description = "Serial reader"
    serial_number = "TEST-1"


class _Serial:
    def __init__(self, *_args, **_kwargs) -> None:
        self.data = iter(b"98765\r")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return bytes((next(self.data),))


def test_serial_line_reader_uses_explicit_port_and_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader_module.list_ports, "comports", lambda: [_Port()])
    monkeypatch.setattr(reader_module.serial, "Serial", _Serial)
    reader = SerialLineChipReader("COM7")
    reader.start()
    result = reader.read_once(timeout_seconds=0.2)
    assert result.code == "0000000000098765"
    assert result.device.port == "COM7"
    assert result.device.serial_number == "TEST-1"


def test_serial_line_reader_fails_closed_for_missing_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader_module.list_ports, "comports", lambda: [])
    reader = SerialLineChipReader("COM8")
    with pytest.raises(ChipReaderError, match="není dostupný"):
        reader.start()
