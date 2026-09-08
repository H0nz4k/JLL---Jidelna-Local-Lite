"""Flet typography and visual tokens – exactly four text roles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import flet as ft


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


# Jedna font family pro celou Flet aplikaci (Windows desktop).
FONT_FAMILY = "Segoe UI"

BASE_ROLES: dict[TextRole, RoleStyle] = {
    TextRole.PRIMARY: RoleStyle(22.0, "w700"),
    TextRole.BODY: RoleStyle(15.0, "w400"),
    TextRole.ACTION: RoleStyle(14.0, "w600"),
    TextRole.META: RoleStyle(12.5, "w400"),
}

_WEIGHT_TO_FLET: dict[str, ft.FontWeight] = {
    "w400": ft.FontWeight.W_400,
    "w600": ft.FontWeight.W_600,
    "w700": ft.FontWeight.W_700,
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
    "picked": "#FFE566",
    "picked_selected": "#F0C000",
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
LIST_WIDTH = 240
LIST_RATIO = 0.18
DETAIL_RATIO = 0.82
WINDOW_WIDTH = 1366
WINDOW_HEIGHT = 768
BLOCK_BORDER_WIDTH = 2
CONTENT_BORDER_WIDTH = 1

# Content-driven šířky Administrace (UI polish).
ADMIN_CONTENT_WIDTH: dict[str, int] = {
    "Uživatelé": 980,
    "Oprávnění": 980,
    "Kategorie": 640,
    "Info": 860,
    "Čtečka": 720,
    "Vzhled": 680,
}

_active_scale: TextScale = TextScale.EXTRA_LARGE


def set_active_scale(scale: TextScale) -> None:
    """Nastaví aktivní velikost textu pro `role_size` / `scaled`."""

    global _active_scale
    _active_scale = scale


def get_active_scale() -> TextScale:
    return _active_scale


def role_size(role: TextRole, scale: TextScale | None = None) -> float:
    active = _active_scale if scale is None else scale
    return round(BASE_ROLES[role].size * active.value, 2)


def role_weight(role: TextRole) -> ft.FontWeight:
    """Centrální weight role – komponenty nesmí volit weight ad-hoc."""

    return _WEIGHT_TO_FLET[BASE_ROLES[role].weight]


def role_weight_value(role: TextRole) -> int:
    return {"w400": 400, "w600": 600, "w700": 700}[BASE_ROLES[role].weight]


def role_style(
    role: TextRole,
    *,
    color: str | None = None,
    scale: TextScale | None = None,
) -> ft.TextStyle:
    """Celý typografický styl role (family + size + weight)."""

    return ft.TextStyle(
        size=role_size(role, scale),
        weight=role_weight(role),
        font_family=FONT_FAMILY,
        color=color,
    )


def text(
    value: str,
    role: TextRole,
    *,
    color: str | None = None,
    scale: TextScale | None = None,
    **kwargs: Any,
) -> ft.Text:
    """ft.Text s centrálním stylem role."""

    return ft.Text(
        value,
        size=role_size(role, scale),
        weight=role_weight(role),
        font_family=FONT_FAMILY,
        color=color,
        **kwargs,
    )


def button_text_style(*, scale: TextScale | None = None) -> ft.TextStyle:
    return role_style(TextRole.ACTION, scale=scale)


def button_style(*, scale: TextScale | None = None, **kwargs: Any) -> ft.ButtonStyle:
    """ButtonStyle s ACTION typografií; varianty řeší fill/border, ne font."""

    return ft.ButtonStyle(text_style=button_text_style(scale=scale), **kwargs)


def field_text_size(scale: TextScale | None = None) -> float:
    """Hodnota TextField / Dropdown = BODY."""

    return role_size(TextRole.BODY, scale)


def field_label_style(*, scale: TextScale | None = None) -> ft.TextStyle:
    return role_style(TextRole.META, color=COLORS["text_secondary"], scale=scale)


def scaled(base: float, scale: TextScale | None = None) -> float:
    """Škáluje pevnou velikost (výška buňky, ikona, padding)."""

    active = _active_scale if scale is None else scale
    return round(base * active.value, 2)


def assert_four_roles() -> tuple[str, ...]:
    names = tuple(sorted(item.name for item in TextRole))
    if names != ("ACTION", "BODY", "META", "PRIMARY"):
        raise AssertionError(f"Neočekávané TextRole: {names}")
    return names


def assert_role_weights() -> dict[str, int]:
    expected = {
        "PRIMARY": 700,
        "BODY": 400,
        "ACTION": 600,
        "META": 400,
    }
    actual = {role.name: role_weight_value(role) for role in TextRole}
    if actual != expected:
        raise AssertionError(f"Neočekávané weight role: {actual}")
    return actual
