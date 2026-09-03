from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContractStatus(StrEnum):
    PROVEN = "PROVEN"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class WriteContractNotProven(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WriteGate:
    status: ContractStatus
    reason: str

    @property
    def enabled(self) -> bool:
        return self.status is ContractStatus.PROVEN

    @property
    def tooltip(self) -> str:
        if self.enabled:
            return "Write kontrakt je ověřen."
        return f"Write kontrakt zatím není ověřen ({self.status}): {self.reason}"


CHIP_WRITE_GATES: dict[str, WriteGate] = {
    "assign": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí autoritativní historie, audit a mixed-writer pravidla.",
    ),
    "return": WriteGate(
        ContractStatus.BLOCKED,
        "Cílový stav, odvázání a historizace nejsou doloženy.",
    ),
    "block": WriteGate(
        ContractStatus.BLOCKED,
        "Write přechod do B a jeho audit nejsou doloženy.",
    ),
    "lost": WriteGate(
        ContractStatus.BLOCKED,
        "Write přechod do Z a jeho audit nejsou doloženy.",
    ),
    "unblock": WriteGate(
        ContractStatus.BLOCKED,
        "Reaktivace B/Z do P není autoritativně doložena.",
    ),
    "transfer": WriteGate(
        ContractStatus.BLOCKED,
        "Helper přepisuje vlastníka v konfliktu s neznámou historií a auditem.",
    ),
}


DINER_WRITE_GATES: dict[str, WriteGate] = {
    "create": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí bezpečný allocator a jednoznačný kontrakt návazných řádků.",
    ),
    "edit_personal": WriteGate(
        ContractStatus.BLOCKED,
        "Chybí autoritativní whitelist polí a auditní kontrakt.",
    ),
    "category_change": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí úplná orchestrace měsíčních přihlášek a návratových stavů.",
    ),
}


def require_proven(gates: dict[str, WriteGate], operation: str) -> None:
    gate = gates.get(operation)
    if gate is None:
        raise ValueError("Neznámá write operace.")
    if not gate.enabled:
        raise WriteContractNotProven(gate.tooltip)
