"""Podpis autora a průběžný odhad hodin vývoje JLL."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

AUTHOR_SIGNATURE = "HanzG"
_TZ = ZoneInfo("Europe/Prague")

#: Manuálně udržovaný baseline (aktualizuj při větším milníku).
#: Zobrazené hodiny = baseline + uplynulý wall-clock čas od `BASELINE_AT`,
#: takže počítadlo na obrazovce Info průběžně roste.
BASELINE_HOURS = 82.0
BASELINE_AT = datetime(2026, 9, 8, 18, 0, tzinfo=_TZ)


def development_hours(*, now: datetime | None = None) -> float:
    """Aktuální odhad hodin vývoje (průběžně rostoucí od baseline)."""

    current = now or datetime.now(_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_TZ)
    else:
        current = current.astimezone(_TZ)
    elapsed = max(0.0, (current - BASELINE_AT).total_seconds())
    return BASELINE_HOURS + elapsed / 3600.0


def format_development_hours(*, now: datetime | None = None) -> str:
    return f"{development_hours(now=now):.1f} h"
