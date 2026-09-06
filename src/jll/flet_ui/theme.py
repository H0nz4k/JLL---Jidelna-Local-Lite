"""Flet typography and visual tokens – exactly four text roles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TextRole(Enum):
    """Role textu v UI.

    PRIMARY – nadpis (jméno strávníka, název obrazovky)
    ACTION  – tlačítka, aktivní popisky, záložky
    BODY    – běžné hodnoty a řádky seznamů
    META    – info, pomocný text, mřížka, ceny
    """

    PRIMARY = "PRIMARY"
    BODY = "BODY"
    ACTION = "ACTION"
    META = "META"


class TextScale(Enum):
    """Zvětšení textu (a odvozených výšek buněk/tlačítek přes role_size)."""

    NORMAL = 1.0
    LARGE = 1.15
    EXTRA_LARGE = 1.3
    HUGE = 1.5

    @property
    def label_cs(self) -> str:
        pct = int(round(self.value * 100))
        return f"{pct} %"


@dataclass(frozen=True, slots=True)
class RoleStyle:
    size: float
    weight: str


BASE_ROLES: dict[TextRole, RoleStyle] = {
    TextRole.PRIMARY: RoleStyle(22.0, "w700"),
    TextRole.BODY: RoleStyle(15.0, "w400"),
    TextRole.ACTION: RoleStyle(14.0, "w600"),
    TextRole.META: RoleStyle(12.5, "w400"),
}

COLORS: dict[str, str] = {
    "background": "#EEF2F6",
    "surface": "#FFFFFF",
    "surface_muted": "#F7F9FB",
    "border": "#D5DEE7",
    "block_border": "#7A8794",
    "text_primary": "#14202B",
    "text_secondary": "#5A6B7A",
    "hint_warning": "#D45353",
    "accent": "#1E5A84",
    "accent_soft": "#D9EAF7",
    "selected": "#C8DFF2",
    "today": "#FBF3D6",
    "today_column": "#FFE08A",
    "today_column_border": "#1E5A84",
    "ordered": "#D7F0DF",
    "ordered_selected": "#A9DDB8",
    "subscribed": "#B7C4BE",
    "subscribed_selected": "#9AABA3",
    "non_cooking": "#E6EBEF",
    "danger": "#9B1C1C",
    "lab": "#8A1F1F",
    "nav": "#102433",
    "nav_text": "#E8EEF4",
}

SPACING: dict[str, int] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

NAV_WIDTH = 0  # menu je v horní liště
LIST_WIDTH = 220
LIST_RATIO = 0.18
DETAIL_RATIO = 0.82
WINDOW_WIDTH = 1366
WINDOW_HEIGHT = 768
BLOCK_BORDER_WIDTH = 2

_active_scale: TextScale = TextScale.NORMAL


def set_active_scale(scale: TextScale) -> None:
    """Nastaví aktivní velikost textu pro `role_size` / `scaled`."""

    global _active_scale
    _active_scale = scale


def get_active_scale() -> TextScale:
    return _active_scale


def role_size(role: TextRole, scale: TextScale | None = None) -> float:
    active = _active_scale if scale is None else scale
    return round(BASE_ROLES[role].size * active.value, 2)


def scaled(base: float, scale: TextScale | None = None) -> float:
    """Škáluje pevnou velikost (výška buňky, ikona, padding)."""

    active = _active_scale if scale is None else scale
    return round(base * active.value, 2)


def assert_four_roles() -> tuple[str, ...]:
    names = tuple(sorted(item.name for item in TextRole))
    if names != ("ACTION", "BODY", "META", "PRIMARY"):
        raise AssertionError(f"Neočekávané TextRole: {names}")
    return names
