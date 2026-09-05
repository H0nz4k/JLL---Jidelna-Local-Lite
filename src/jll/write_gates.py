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
    action_label: str

    @property
    def enabled(self) -> bool:
        return self.status is ContractStatus.PROVEN

    @property
    def tooltip(self) -> str:
        """Lidská hláška pro GUI; technický důvod zůstává v `reason`."""

        if self.enabled:
            return f"Funkce „{self.action_label}“ je dostupná."
        return (
            "Funkce je v této verzi bezpečnostně blokována.\n"
            f"Databázový zápis pro „{self.action_label}“ zatím není ověřen."
        )

    @property
    def badge(self) -> str | None:
        if self.enabled:
            return None
        return "Dosud nepovoleno"


CHIP_WRITE_GATES: dict[str, WriteGate] = {
    "assign": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí autoritativní historie, audit a mixed-writer pravidla.",
        "Přidělit čip",
    ),
    "return": WriteGate(
        ContractStatus.BLOCKED,
        "Cílový stav, odvázání a historizace nejsou doloženy.",
        "Vrátit čip",
    ),
    "block": WriteGate(
        ContractStatus.BLOCKED,
        "Write přechod do B a jeho audit nejsou doloženy.",
        "Blokovat čip",
    ),
    "lost": WriteGate(
        ContractStatus.BLOCKED,
        "Write přechod do Z a jeho audit nejsou doloženy.",
        "Označit čip jako ztracený",
    ),
    "unblock": WriteGate(
        ContractStatus.BLOCKED,
        "Reaktivace B/Z do P není autoritativně doložena.",
        "Odblokovat čip",
    ),
    "transfer": WriteGate(
        ContractStatus.BLOCKED,
        "Helper přepisuje vlastníka v konfliktu s neznámou historií a auditem.",
        "Převést čip",
    ),
}


DINER_WRITE_GATES: dict[str, WriteGate] = {
    "create": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí bezpečný allocator a jednoznačný kontrakt návazných řádků.",
        "Přidat strávníka",
    ),
    "edit_personal": WriteGate(
        ContractStatus.BLOCKED,
        "Chybí autoritativní whitelist polí a auditní kontrakt.",
        "Upravit strávníka",
    ),
    "category_change": WriteGate(
        ContractStatus.PARTIAL,
        "Chybí úplná orchestrace měsíčních přihlášek a návratových stavů.",
        "Změnit kategorii strávníka",
    ),
}


def require_proven(gates: dict[str, WriteGate], operation: str) -> None:
    gate = gates.get(operation)
    if gate is None:
        raise ValueError("Neznámá write operace.")
    if not gate.enabled:
        raise WriteContractNotProven(gate.tooltip)
