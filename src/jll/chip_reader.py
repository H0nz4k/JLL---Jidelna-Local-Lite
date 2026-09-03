from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

import serial
from serial.tools import list_ports


class ReaderState(StrEnum):
    STOPPED = "stopped"
    READY = "ready"
    READING = "reading"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ReaderStatus:
    state: ReaderState
    message: str
    last_read_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReaderDeviceInfo:
    adapter: str
    port: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None


@dataclass(frozen=True, slots=True)
class ChipRead:
    code: str
    read_at: datetime
    device: ReaderDeviceInfo


class ChipReaderError(RuntimeError):
    pass


class ChipReaderTimeout(ChipReaderError):
    pass


class ChipReaderCancelled(ChipReaderError):
    pass


class ChipReader(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def read_once(
        self,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> ChipRead: ...

    @abstractmethod
    def status(self) -> ReaderStatus: ...

    @abstractmethod
    def device_info(self) -> ReaderDeviceInfo: ...


class FakeChipReader(ChipReader):
    def __init__(
        self,
        codes: list[str] | None = None,
        *,
        duplicate_debounce_seconds: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if duplicate_debounce_seconds < 0:
            raise ValueError("duplicate_debounce_seconds nesmí být záporný.")
        self._codes: deque[str] = deque(
            _normalize_code(code) for code in (codes or [])
        )
        self._condition = threading.Condition()
        self._running = False
        self._reading = False
        self._last_code: str | None = None
        self._last_code_at = float("-inf")
        self._last_read_at: datetime | None = None
        self._debounce = duplicate_debounce_seconds
        self._clock = clock
        self._device = ReaderDeviceInfo(adapter="fake", product="LAB FakeChipReader")

    def start(self) -> None:
        with self._condition:
            self._running = True
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._reading = False
            self._condition.notify_all()

    def feed(self, code: str) -> None:
        normalized = _normalize_code(code)
        with self._condition:
            self._codes.append(normalized)
            self._condition.notify_all()

    def read_once(
        self,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> ChipRead:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Reader timeout musí být v rozsahu (0, 30].")
        deadline = self._clock() + timeout_seconds
        with self._condition:
            if not self._running:
                raise ChipReaderError("Čtečka není spuštěná.")
            self._reading = True
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ChipReaderCancelled("Čtení bylo zrušeno.")
                    if not self._running:
                        raise ChipReaderCancelled("Čtečka byla zastavena.")
                    while self._codes:
                        code = self._codes.popleft()
                        now = self._clock()
                        if (
                            code == self._last_code
                            and now - self._last_code_at < self._debounce
                        ):
                            continue
                        self._last_code = code
                        self._last_code_at = now
                        self._last_read_at = datetime.now(timezone.utc)
                        return ChipRead(code, self._last_read_at, self._device)
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise ChipReaderTimeout("Čas pro načtení čipu vypršel.")
                    self._condition.wait(min(remaining, 0.1))
            finally:
                self._reading = False

    def status(self) -> ReaderStatus:
        with self._condition:
            if not self._running:
                state = ReaderState.STOPPED
                message = "LAB fake čtečka je zastavená."
            elif self._reading:
                state = ReaderState.READING
                message = "Čekám na čip."
            else:
                state = ReaderState.READY
                message = "LAB fake čtečka je připravená."
            return ReaderStatus(state, message, self._last_read_at)

    def device_info(self) -> ReaderDeviceInfo:
        return self._device


class UnavailableChipReader(ChipReader):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self._device = ReaderDeviceInfo(adapter="unavailable")

    def start(self) -> None:
        raise ChipReaderError(self.reason)

    def stop(self) -> None:
        return None

    def read_once(
        self,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> ChipRead:
        raise ChipReaderError(self.reason)

    def status(self) -> ReaderStatus:
        return ReaderStatus(ReaderState.DISCONNECTED, self.reason)

    def device_info(self) -> ReaderDeviceInfo:
        return self._device


class SerialLineChipReader(ChipReader):
    """Adapter pro doložený referenční serial-line protokol.

    Port se nikdy nevybírá automaticky. Musí být explicitně nakonfigurovaný;
    enumerace COM/USB slouží jen k ověření identity a diagnostice.
    """

    def __init__(
        self,
        port: str,
        *,
        baud_rate: int = 19_200,
        line_end: bytes = b"\r",
        duplicate_debounce_seconds: float = 0.75,
        reconnect_attempts: int = 2,
    ) -> None:
        if not port.strip():
            raise ValueError("Serial port nesmí být prázdný.")
        if not 1 <= baud_rate <= 4_000_000:
            raise ValueError("Neplatná přenosová rychlost.")
        if not 1 <= len(line_end) <= 4:
            raise ValueError("Ukončení zprávy musí mít 1 až 4 bajty.")
        if duplicate_debounce_seconds < 0:
            raise ValueError("duplicate_debounce_seconds nesmí být záporný.")
        if not 0 <= reconnect_attempts <= 5:
            raise ValueError("reconnect_attempts musí být v rozsahu 0..5.")
        self.port = port.strip()
        self.baud_rate = baud_rate
        self.line_end = line_end
        self._debounce = duplicate_debounce_seconds
        self._reconnect_attempts = reconnect_attempts
        self._running = False
        self._reading = False
        self._stop = threading.Event()
        self._read_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._last_code: str | None = None
        self._last_code_at = float("-inf")
        self._last_read_at: datetime | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        device = self._discover()
        if device is None:
            with self._status_lock:
                self._running = False
                self._last_error = (
                    f"Nakonfigurovaný port {self.port} není dostupný."
                )
            raise ChipReaderError(self._last_error)
        with self._status_lock:
            self._stop.clear()
            self._running = True
            self._last_error = None

    def stop(self) -> None:
        self._stop.set()
        with self._status_lock:
            self._running = False

    def read_once(
        self,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> ChipRead:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Reader timeout musí být v rozsahu (0, 30].")
        if not self._running:
            raise ChipReaderError("Čtečka není spuštěná.")
        if not self._read_lock.acquire(blocking=False):
            raise ChipReaderError("Na čtečce již probíhá jiné čtení.")
        deadline = time.monotonic() + timeout_seconds
        try:
            with self._status_lock:
                self._reading = True
            for attempt in range(self._reconnect_attempts + 1):
                self._check_cancelled(cancel_event)
                try:
                    while time.monotonic() < deadline:
                        code = self._read_frame(deadline, cancel_event)
                        now = time.monotonic()
                        if (
                            code == self._last_code
                            and now - self._last_code_at < self._debounce
                        ):
                            continue
                        self._last_code = code
                        self._last_code_at = now
                        self._last_read_at = datetime.now(timezone.utc)
                        return ChipRead(
                            code=code,
                            read_at=self._last_read_at,
                            device=self.device_info(),
                        )
                except serial.SerialException as exc:
                    with self._status_lock:
                        self._last_error = f"Serial komunikace selhala: {exc}"
                    if attempt >= self._reconnect_attempts:
                        raise ChipReaderError(self._last_error) from exc
                    self._wait_for_reconnect(deadline, cancel_event)
            raise ChipReaderTimeout("Čas pro načtení čipu vypršel.")
        finally:
            with self._status_lock:
                self._reading = False
            self._read_lock.release()

    def status(self) -> ReaderStatus:
        with self._status_lock:
            if self._last_error:
                state = ReaderState.ERROR
                message = self._last_error
            elif not self._running:
                state = ReaderState.STOPPED
                message = "Serial čtečka je zastavená."
            elif self._discover() is None:
                state = ReaderState.DISCONNECTED
                message = f"Port {self.port} není dostupný."
            elif self._reading:
                state = ReaderState.READING
                message = "Čekám na čip."
            else:
                state = ReaderState.READY
                message = "Serial čtečka je připravená."
            return ReaderStatus(state, message, self._last_read_at)

    def device_info(self) -> ReaderDeviceInfo:
        port = self._discover()
        return ReaderDeviceInfo(
            adapter="serial-line",
            port=self.port,
            manufacturer=getattr(port, "manufacturer", None),
            product=getattr(port, "product", None)
            or getattr(port, "description", None),
            serial_number=getattr(port, "serial_number", None),
        )

    def _discover(self):
        wanted = self.port.casefold()
        return next(
            (
                item
                for item in list_ports.comports()
                if str(item.device).casefold() == wanted
            ),
            None,
        )

    def _read_frame(
        self,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> str:
        frame = bytearray()
        with serial.Serial(
            self.port,
            self.baud_rate,
            timeout=0.1,
            write_timeout=0.5,
        ) as connection:
            while time.monotonic() < deadline:
                self._check_cancelled(cancel_event)
                byte = connection.read(1)
                if not byte:
                    continue
                frame.extend(byte)
                if frame.endswith(self.line_end):
                    raw = bytes(frame[: -len(self.line_end)])
                    try:
                        text = raw.decode("ascii", errors="strict")
                    except UnicodeDecodeError as exc:
                        raise ChipReaderError(
                            "Čtečka vrátila neplatné ne-ASCII znaky."
                        ) from exc
                    return _normalize_code(text).zfill(16)
                if len(frame) > 128 + len(self.line_end):
                    raise ChipReaderError("Čtečka vrátila příliš dlouhou zprávu.")
        raise ChipReaderTimeout("Čas pro načtení čipu vypršel.")

    def _check_cancelled(
        self,
        cancel_event: threading.Event | None,
    ) -> None:
        if self._stop.is_set() or (
            cancel_event is not None and cancel_event.is_set()
        ):
            raise ChipReaderCancelled("Čtení bylo zrušeno.")

    def _wait_for_reconnect(
        self,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> None:
        while time.monotonic() < deadline:
            self._check_cancelled(cancel_event)
            if self._discover() is not None:
                return
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raise ChipReaderTimeout("Čtečka se v časovém limitu znovu nepřipojila.")


@dataclass(frozen=True, slots=True)
class SerialPortOption:
    """Jeden COM port z OS enumerace.

    Model, VID ani PID se nedopočítávají; zobrazuje se jen to, co OS vrátí.
    """

    device: str
    description: str | None = None
    manufacturer: str | None = None

    @property
    def label(self) -> str:
        detail = self.description or self.manufacturer
        return f"{self.device} — {detail}" if detail else self.device


def available_serial_ports() -> tuple[SerialPortOption, ...]:
    """COM porty podle OS enumerace, seřazené podle názvu zařízení."""

    options = [
        SerialPortOption(
            device=str(port.device),
            description=_optional_port_text(
                getattr(port, "description", None)
            ),
            manufacturer=_optional_port_text(
                getattr(port, "manufacturer", None)
            ),
        )
        for port in list_ports.comports()
        if str(getattr(port, "device", "")).strip()
    ]
    return tuple(sorted(options, key=lambda item: item.device.casefold()))


def build_chip_reader(
    port: str | None,
    *,
    baud_rate: int = 19_200,
    line_end: str = "\r",
) -> ChipReader:
    """Vytvoří čtečku podle instalační konfigurace.

    Bez nakonfigurovaného portu vrací `UnavailableChipReader`; port se nikdy
    nehádá z enumerace, protože model čtečky není autoritativně doložený.
    """

    if not port or not port.strip():
        return UnavailableChipReader(
            "Čtečka není nakonfigurována. Vyberte COM port v administraci."
        )
    try:
        return SerialLineChipReader(
            port.strip(),
            baud_rate=baud_rate,
            line_end=line_end.encode("ascii"),
        )
    except (ValueError, UnicodeEncodeError) as exc:
        return UnavailableChipReader(f"Nastavení čtečky není platné: {exc}")


def _optional_port_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() == "n/a":
        return None
    return text


def masked_chip_summary(code: str | None) -> str:
    if not code:
        return "žádné načtení"
    return f"••••{code[-4:]}" if len(code) > 4 else "••••"


def _normalize_code(code: str) -> str:
    if not isinstance(code, str):
        raise ValueError("Kód čipu musí být text.")
    value = code.strip()
    if not value or len(value) > 128 or any(not char.isprintable() for char in value):
        raise ValueError("Kód čipu nemá platný formát.")
    return value
