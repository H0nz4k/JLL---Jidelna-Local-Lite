"""ELATEC RFID serial reader discovery (Windows PnP / pyserial)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from serial.tools import list_ports

#: HIL-proven USB identity (COM7 Serial RFID Device, manufacturer=Elatec).
ELATEC_USB_VID = 0x09D8
ELATEC_USB_PID = 0x0420


class ReaderDiscoveryStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class DiscoveredReader:
    device: str
    description: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None
    vid: int | None = None
    pid: int | None = None
    hwid: str | None = None
    location: str | None = None

    @property
    def label(self) -> str:
        parts = [self.device]
        desc = self.description or self.product
        if desc:
            # OS often appends "(COMx)" — trim for human label.
            cleaned = desc
            marker = f"({self.device})"
            if cleaned.endswith(marker):
                cleaned = cleaned[: -len(marker)].strip()
            if cleaned:
                parts.append(cleaned)
        if self.manufacturer:
            parts.append(self.manufacturer)
        return " — ".join(parts)


@dataclass(frozen=True, slots=True)
class ReaderDiscoveryResult:
    status: ReaderDiscoveryStatus
    selected: DiscoveredReader | None = None
    matches: tuple[DiscoveredReader, ...] = ()
    message: str = ""


PortLister = Callable[[], Sequence[Any]]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"n/a", "none"}:
        return None
    return text


def _normalize_serial(value: object) -> str | None:
    text = _optional_text(value)
    return text


def port_to_discovered(port: Any) -> DiscoveredReader:
    return DiscoveredReader(
        device=str(getattr(port, "device", "")).strip(),
        description=_optional_text(getattr(port, "description", None)),
        manufacturer=_optional_text(getattr(port, "manufacturer", None)),
        product=_optional_text(getattr(port, "product", None)),
        serial_number=_normalize_serial(getattr(port, "serial_number", None)),
        vid=getattr(port, "vid", None),
        pid=getattr(port, "pid", None),
        hwid=_optional_text(getattr(port, "hwid", None)),
        location=_optional_text(getattr(port, "location", None)),
    )


def is_elatec_port(port: Any) -> bool:
    """True jen při prokázané ELATEC identitě (ne Microsoft/subser.sys)."""

    manufacturer = _optional_text(getattr(port, "manufacturer", None))
    if manufacturer and "elatec" in manufacturer.casefold():
        return True
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    if vid == ELATEC_USB_VID and pid == ELATEC_USB_PID:
        return True
    hwid = (_optional_text(getattr(port, "hwid", None)) or "").upper()
    if "VID:PID=09D8:0420" in hwid.replace(" ", ""):
        return True
    return False


def discover_elatec_readers(
    *,
    port_lister: PortLister | None = None,
) -> tuple[DiscoveredReader, ...]:
    lister = port_lister or list_ports.comports
    found: list[DiscoveredReader] = []
    for raw in lister():
        if not str(getattr(raw, "device", "")).strip():
            continue
        if not is_elatec_port(raw):
            continue
        found.append(port_to_discovered(raw))
    return tuple(sorted(found, key=lambda item: item.device.casefold()))


def select_elatec_reader(
    *,
    preferred_serial: str | None = None,
    port_lister: PortLister | None = None,
) -> ReaderDiscoveryResult:
    matches = discover_elatec_readers(port_lister=port_lister)
    if not matches:
        return ReaderDiscoveryResult(
            status=ReaderDiscoveryStatus.NOT_FOUND,
            matches=(),
            message="ELATEC čtečka není připojena.",
        )
    if len(matches) == 1:
        return ReaderDiscoveryResult(
            status=ReaderDiscoveryStatus.FOUND,
            selected=matches[0],
            matches=matches,
            message=f"ELATEC RFID – {matches[0].device}",
        )
    preferred = _normalize_serial(preferred_serial)
    if preferred:
        preferred_matches = tuple(
            item for item in matches if item.serial_number == preferred
        )
        if len(preferred_matches) == 1:
            return ReaderDiscoveryResult(
                status=ReaderDiscoveryStatus.FOUND,
                selected=preferred_matches[0],
                matches=matches,
                message=f"ELATEC RFID – {preferred_matches[0].device}",
            )
    return ReaderDiscoveryResult(
        status=ReaderDiscoveryStatus.AMBIGUOUS,
        selected=None,
        matches=matches,
        message=(
            f"Bylo nalezeno více čteček ELATEC ({len(matches)}). "
            "Vyberte zařízení v Administraci."
        ),
    )
