"""Flet typography and visual tokens – exactly four editable text roles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import flet as ft

from ..typography_settings import (
    DEFAULT_TYPOGRAPHY,
    TypographySettings,
    typography_from_legacy_scale,
)


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
    """Legacy scale presets (pre-editable typography). Not an active multiplier anymore."""

    NORMAL = 1.0
    LARGE = 1.15
    EXTRA_LARGE = 1.3
    HUGE = 1.5

    @property
    def label_cs(self) -> str:
        pct = int(round(self.value * 100))
        return f"{pct} %"


@dataclass(frozen=True, slots=True)
class TypographySignature:
    font_family: str
    size: float
    weight: str


# Jedna font family pro celou Flet aplikaci (Windows desktop).
FONT_FAMILY = "Segoe UI"

# Historical unscaled BODY size – layout `scaled()` tracks BODY relative to this.
_HISTORICAL_BODY_BASE = 15.0

# Kept for docs/migration reference; runtime uses DEFAULT_TYPOGRAPHY / _active.
BASE_ROLES = {
    TextRole.PRIMARY: (22.0, True),
    TextRole.BODY: (15.0, False),
    TextRole.ACTION: (14.0, True),
    TextRole.META: (12.5, False),
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
    # Textová zeleň ze stejné rodiny jako pozadí objednávky (čitelná na bílém).
    "credit_positive": "#2F8A52",
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
    "Vzhled": 760,
}

_active_typography: TypographySettings = DEFAULT_TYPOGRAPHY


def set_typography(settings: TypographySettings) -> None:
    """Nastaví runtime typography pro celou Flet aplikaci."""

    global _active_typography
    _active_typography = settings


def get_typography() -> TypographySettings:
    return _active_typography


def set_active_scale(scale: TextScale) -> None:
    """Legacy: convert scale preset to absolute role sizes (no dual multiplier)."""

    set_typography(typography_from_legacy_scale(scale.value))


def get_active_scale() -> TextScale:
    """Best-effort reverse map for legacy callers; prefers EXTRA_LARGE default."""

    body = _active_typography.body.size
    for scale in TextScale:
        if abs(round(15.0 * scale.value, 2) - body) < 0.05:
            return scale
    return TextScale.EXTRA_LARGE


def _role_settings(role: TextRole):
    key = role.name.lower()
    return _active_typography.for_key(key)


def role_size(role: TextRole, scale: TextScale | None = None) -> float:
    if scale is not None:
        return typography_from_legacy_scale(scale.value).for_key(role.name.lower()).size
    return _role_settings(role).size


def role_weight(role: TextRole) -> ft.FontWeight:
    """Centrální weight role – bold → W700, jinak W400. Žádné W500/W600."""

    return ft.FontWeight.W_700 if _role_settings(role).bold else ft.FontWeight.W_400


def role_weight_value(role: TextRole) -> int:
    return 700 if _role_settings(role).bold else 400


def role_style(
    role: TextRole,
    *,
    color: str | None = None,
    scale: TextScale | None = None,
) -> ft.TextStyle:
    """Celý typografický styl role (family + size + weight)."""

    size = role_size(role, scale)
    weight = (
        ft.FontWeight.W_700
        if (
            typography_from_legacy_scale(scale.value).for_key(role.name.lower()).bold
            if scale is not None
            else _role_settings(role).bold
        )
        else ft.FontWeight.W_400
    )
    return ft.TextStyle(
        size=size,
        weight=weight,
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

    style = role_style(role, color=color, scale=scale)
    return ft.Text(
        value,
        size=style.size,
        weight=style.weight,
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
    """Škáluje geometrii (buňka, padding) podle BODY vůči historickému base 15."""

    if scale is not None:
        factor = scale.value
    else:
        factor = role_size(TextRole.BODY) / _HISTORICAL_BODY_BASE
    return round(base * factor, 2)


def role_signature(role: TextRole) -> TypographySignature:
    return TypographySignature(
        font_family=FONT_FAMILY,
        size=role_size(role),
        weight=f"w{role_weight_value(role)}",
    )


def all_role_signatures() -> tuple[TypographySignature, ...]:
    return tuple(role_signature(role) for role in TextRole)


def assert_four_roles() -> tuple[str, ...]:
    names = tuple(sorted(item.name for item in TextRole))
    if names != ("ACTION", "BODY", "META", "PRIMARY"):
        raise AssertionError(f"Neočekávané TextRole: {names}")
    return names


def assert_role_weights() -> dict[str, int]:
    """Default weights after set_typography(DEFAULT) / fresh process."""

    expected = {
        "PRIMARY": 700,
        "BODY": 400,
        "ACTION": 700,
        "META": 400,
    }
    actual = {role.name: role_weight_value(role) for role in TextRole}
    if actual != expected:
        raise AssertionError(f"Neočekávané weight role: {actual}")
    return actual


def assert_max_four_signatures() -> int:
    count = len(set(all_role_signatures()))
    if count > 4:
        raise AssertionError(f"Příliš mnoho typografických signatures: {count}")
    return count
