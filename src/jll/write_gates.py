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
        ContractStatus.PROVEN,
        "Data.pas NajdiCip(P): INSERT/UPDATE cipy P + histcipu + stravnik.cip; "
        "odmítá P/B; Z jen s allow_reassign_lost. Finance VyberzaCip (INI "
        "CenaZaPrvniCip) — DB path odpovídá CenaZaPrvniCip=0; "
        "nenulová záloha je mimo tuto misi (platby).",
        "Přidělit čip",
    ),
    "return": WriteGate(
        ContractStatus.BLOCKED,
        "NajdiCip(V) je doložen, ale legacy volá VratzaCip (finanční vratka). "
        "Bez PaymentService 0.4.0 zůstává return fail-closed.",
        "Vrátit čip",
    ),
    "block": WriteGate(
        ContractStatus.PROVEN,
        "stravnik.pas BitBtn13 / NajdiCip(B): cipy.stav=B + histcipu B, "
        "vlastník zůstává; jen z P.",
        "Blokovat čip",
    ),
    "lost": WriteGate(
        ContractStatus.PROVEN,
        "stravnik.pas BitBtn14: cipy.stav=Z + histcipu Z + clear stravnik.cip.",
        "Označit čip jako ztracený",
    ),
    "unblock": WriteGate(
        ContractStatus.PROVEN,
        "NajdiCip(B) když už B a owner match → stav P + histcipu P.",
        "Odblokovat čip",
    ),
    "transfer": WriteGate(
        ContractStatus.BLOCKED,
        "Legacy nemá samostatný transfer; tiché převedení vlastníka zakázáno.",
        "Převést čip",
    ),
}


DINER_WRITE_GATES: dict[str, WriteGate] = {
    "create": WriteGate(
        ContractStatus.PROVEN,
        "pridel_cislo_stravnika + insert stravnik (AfterInsert defaults) + "
        "doplnobvyklestravnikakategor AM/BM + podmíněný nastavprihlasdleobvykle + "
        "insert_udalost. Gate platí pro JLL-only LAB režim.",
        "Přidat strávníka",
    ),
    "edit_personal": WriteGate(
        ContractStatus.PROVEN,
        "Explicitní whitelist (jmeno/trida/adresa/kontakt/poznámky); "
        "FOR UPDATE + expected updated_dt; audit insert_udalost; "
        "kategorie/finance/čip/stav zakázány.",
        "Upravit strávníka",
    ),
    "category_change": WriteGate(
        ContractStatus.PARTIAL,
        "DB doplnobvyklestravnikakategor doložena, ale AM/BM dialogy a "
        "prihlas/penden orchestrace z DBEdit3Exit nejsou kompletně portované.",
        "Změnit kategorii strávníka",
    ),
}


SERVING_WRITE_GATES: dict[str, WriteGate] = {
    "record_pickup": WriteGate(
        ContractStatus.PROVEN,
        "LAB identity + scope + aktivní strávník + prihlaska.id; write jen "
        "public.zapis_odber. Charakterizace LAB: úspěšný zápis O do odebral, "
        "duplicate i concurrent vrátí true (idempotentní značka), rollback "
        "vnější transakce vrátí stav. Bez mutual-exclusion locku v DB.",
        "Zapsat odběr",
    ),
}


def require_proven(gates: dict[str, WriteGate], operation: str) -> None:
    gate = gates.get(operation)
    if gate is None:
        raise ValueError("Neznámá write operace.")
    if not gate.enabled:
        raise WriteContractNotProven(gate.tooltip)
