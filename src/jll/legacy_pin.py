"""Legacy GetPIN parity (Pomoc.pas)."""

from __future__ import annotations


def legacy_get_pin(jmeno: str, chip: str, evidcislo: int) -> str:
    """Port `GetPIN(Jmeno, Ecip, Evid)` z Pomoc.pas.

    `chip` se v algoritmu nepoužívá (stejně jako v legacy), ale zůstává
    v signature kvůli volacímu kontraktu.
    """

    _ = chip
    evid = f"{int(evidcislo):010d}"
    padded = (jmeno or "")[:20].ljust(20)
    suma = sum(ord(ch) for ch in padded)
    sum1 = (suma % 100) + int(evid[8:10]) + int(evid[4:6])
    sum2 = ((suma // 100) % 100) + int(evid[6:8]) + int(evid[2:4])
    pin = ((sum1 % 100) + (sum2 % 100) * 100) * 13 % 10000
    if pin < 1000:
        pin += 1000
    return f"{pin:04d}"
