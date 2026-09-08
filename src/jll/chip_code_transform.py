"""Reader-side transformace čísla čipu (IKonverze / Pridat00).

Business vrstva vždy pracuje s kanonickým DB tvarem (`varchar(16)`,
doplněno zleva nulami). Konverze ze čtečky patří sem — ne do repository
ani do OrderService.

Postup odpovídá JídelnaSQL / `Prilozcip.pas` a
`docs/JLL_CHIP_IKONVERZE_PRIDAT00.md`.
"""

from __future__ import annotations

_NIBBLE_REVERSE = {
    "0": "0",
    "1": "8",
    "2": "4",
    "3": "C",
    "4": "2",
    "5": "A",
    "6": "6",
    "7": "E",
    "8": "1",
    "9": "9",
    "A": "5",
    "B": "D",
    "C": "3",
    "D": "B",
    "E": "7",
    "F": "F",
}


def clean_chip_raw(raw: str) -> str:
    """Odstraní whitespace; ponechá alfanumerické znaky (HEX/DEC)."""

    if not isinstance(raw, str):
        raise ValueError("Kód čipu musí být text.")
    value = "".join(raw.strip().split()).upper()
    if not value:
        raise ValueError("Kód čipu je prázdný.")
    if any(not character.isalnum() for character in value):
        raise ValueError("Kód čipu nemá platný formát.")
    if len(value) > 32:
        raise ValueError("Kód čipu je příliš dlouhý.")
    return value


def pad_chip_to_db(code: str) -> str:
    """Doplní kód zleva nulami na 16 znaků (DB `public.cipy.cislo`)."""

    value = clean_chip_raw(code)
    if len(value) > 16:
        raise ValueError("Kód čipu po úpravě přesahuje 16 znaků.")
    return value.zfill(16)


def apply_ikonverze(raw_hex: str) -> str:
    """IKonverze: 10 HEX znaků → drop 1. byte → reverse nibble bitů → DEC."""

    cleaned = clean_chip_raw(raw_hex)
    hex_only = "".join(
        character for character in cleaned if character in _NIBBLE_REVERSE
    )
    if len(hex_only) < 10:
        hex_only = hex_only.zfill(10)
    else:
        hex_only = hex_only[-10:]
    body = hex_only[2:]
    reversed_nibbles = "".join(_NIBBLE_REVERSE[character] for character in body)
    return str(int(reversed_nibbles, 16))


def apply_pridat00(code: str) -> str:
    """Připojí literál `00` na konec (ne HEX konverze)."""

    return f"{clean_chip_raw(code)}00"


def transform_reader_chip_code(
    raw: str,
    *,
    ikonverze: bool = False,
    pridat00: bool = False,
) -> str:
    """Upraví vstup ze čtečky podle stančních přepínačů.

    - oba `False` → jen strip/upper + pad na 16 (bez IKonverze),
    - `ikonverze` → HEX→DEC dle JídelnaSQL,
    - `pridat00` → připojí `00` (typicky po IKonverzi),
    - výsledek vždy doplněn zleva na 16 znaků.
    """

    value = clean_chip_raw(raw)
    if not ikonverze and not pridat00:
        return pad_chip_to_db(value)
    if ikonverze:
        value = apply_ikonverze(value)
    if pridat00:
        value = apply_pridat00(value)
    return pad_chip_to_db(value)
