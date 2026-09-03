"""Centrální design tokeny JLL klienta.

Jediný bod pravdy pro typografii, barvy, spacing a rozměry ovládacích prvků.
Widgety nesmí nastavovat vlastní `font-size`; místo toho použijí jednu ze
čtyř typografických rolí.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

FONT_FAMILY = "Segoe UI"


class TextRole(Enum):
    """Povolené typografické role. Pátý „skoro stejný“ styl neexistuje."""

    PRIMARY = "T1"
    BODY = "T2"
    ACTION = "T3"
    META = "T4"


class TextScale(Enum):
    """Připravené režimy velikosti textu."""

    NORMAL = 1.0
    LARGE = 1.15
    EXTRA_LARGE = 1.3


@dataclass(frozen=True, slots=True)
class RoleStyle:
    point_size: float
    bold: bool


BASE_ROLES: dict[TextRole, RoleStyle] = {
    TextRole.PRIMARY: RoleStyle(15.5, True),
    TextRole.BODY: RoleStyle(11.5, False),
    TextRole.ACTION: RoleStyle(11.0, True),
    TextRole.META: RoleStyle(10.0, False),
}

COLORS: dict[str, str] = {
    "background": "#f4f6f8",
    "surface": "#ffffff",
    "border": "#d7dee5",
    "text_primary": "#16202a",
    "text_secondary": "#5b6b7a",
    "accent": "#1f4f72",
    "selected": "#bcd9f2",
    "today": "#fdf7e0",
    "ordered_background": "#e4f4e8",
    "ordered_selected": "#b9e3c6",
    "ordered_accent": "#1c6b41",
    "ordered_text": "#0f1b13",
    "non_cooking": "#e7ebef",
    "weekend": "#eef1f4",
    "disabled": "#9aa7b3",
    "danger": "#9b1c1c",
    "lab_warning": "#9b1c1c",
}

SPACING: dict[str, int] = {
    "xs": 2,
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
}

RADIUS: dict[str, int] = {
    "sm": 3,
    "md": 5,
}

BORDER_WIDTH = 1
CONTROL_HEIGHT = 30
ROW_HEIGHT = 32
MENU_BADGE_WIDTH = 30

_scale = TextScale.NORMAL


def set_text_scale(scale: TextScale) -> None:
    global _scale
    _scale = scale


def text_scale() -> TextScale:
    return _scale


def point_size(role: TextRole) -> float:
    return round(BASE_ROLES[role].point_size * _scale.value, 1)


def role_point_sizes() -> set[float]:
    return {point_size(role) for role in TextRole}


def font(role: TextRole) -> QFont:
    style = BASE_ROLES[role]
    value = QFont(FONT_FAMILY)
    value.setPointSizeF(point_size(role))
    value.setBold(style.bold)
    return value


def apply_role(widget: QWidget, role: TextRole) -> None:
    """Nastaví typografickou roli widgetu a zpřístupní ji QSS i testům."""

    widget.setFont(font(role))
    widget.setProperty("textRole", role.value)


def style_sheet() -> str:
    """Jediný QSS blok aplikace; barvy a rozměry pouze z tokenů."""

    return f"""
    QWidget {{
        color: {COLORS["text_primary"]};
    }}
    QMainWindow, QDialog {{
        background: {COLORS["background"]};
    }}
    QLabel[textRole="{TextRole.PRIMARY.value}"] {{
        color: {COLORS["text_primary"]};
    }}
    QLabel[textRole="{TextRole.META.value}"] {{
        color: {COLORS["text_secondary"]};
    }}
    QLabel[tone="secondary"] {{
        color: {COLORS["text_secondary"]};
    }}
    QLabel[tone="accent"] {{
        color: {COLORS["accent"]};
    }}
    QLabel[tone="danger"] {{
        color: {COLORS["danger"]};
    }}
    QLabel[tone="ordered"] {{
        color: {COLORS["ordered_text"]};
    }}
    QLabel[tone="labBanner"] {{
        background: {COLORS["lab_warning"]};
        color: {COLORS["surface"]};
        padding: {SPACING["xs"]}px {SPACING["md"]}px;
        border-radius: {RADIUS["sm"]}px;
    }}
    QLineEdit, QDateEdit, QComboBox, QSpinBox {{
        background: {COLORS["surface"]};
        border: {BORDER_WIDTH}px solid {COLORS["border"]};
        border-radius: {RADIUS["sm"]}px;
        padding: {SPACING["sm"]}px {SPACING["md"]}px;
        min-height: {CONTROL_HEIGHT - 2 * SPACING["sm"] - 2}px;
    }}
    QPushButton {{
        background: {COLORS["surface"]};
        border: {BORDER_WIDTH}px solid {COLORS["border"]};
        border-radius: {RADIUS["sm"]}px;
        padding: {SPACING["sm"]}px {SPACING["lg"]}px;
        min-height: {CONTROL_HEIGHT - 2 * SPACING["sm"] - 2}px;
    }}
    QPushButton:hover:enabled {{
        border-color: {COLORS["accent"]};
    }}
    QPushButton:disabled {{
        color: {COLORS["disabled"]};
        background: {COLORS["background"]};
    }}
    QPushButton[variant="primary"]:enabled {{
        background: {COLORS["accent"]};
        border-color: {COLORS["accent"]};
        color: {COLORS["surface"]};
    }}
    QPushButton[variant="destructive"]:enabled {{
        background: {COLORS["surface"]};
        border-color: {COLORS["danger"]};
        color: {COLORS["danger"]};
    }}
    QPushButton[variant="pending"] {{
        background: {COLORS["today"]};
        border-color: {COLORS["ordered_accent"]};
        color: {COLORS["text_primary"]};
    }}
    QPushButton[variant="compact"] {{
        padding: {SPACING["xs"]}px {SPACING["md"]}px;
    }}
    QFrame#menuRow {{
        background: {COLORS["surface"]};
        border: {BORDER_WIDTH}px solid {COLORS["border"]};
        border-radius: {RADIUS["sm"]}px;
    }}
    QFrame#menuRow[clickable="true"]:hover {{
        border-color: {COLORS["accent"]};
    }}
    QFrame#menuRow[ordered="true"] {{
        background: {COLORS["ordered_background"]};
        border-color: {COLORS["ordered_accent"]};
    }}
    QFrame#menuRow[ordered="true"]:hover {{
        background: {COLORS["ordered_background"]};
        border-color: {COLORS["ordered_accent"]};
    }}
    QFrame#pickupRow {{
        background: {COLORS["surface"]};
        border: {BORDER_WIDTH}px solid {COLORS["border"]};
        border-radius: {RADIUS["md"]}px;
    }}
    QFrame#pickupRow[complete="true"] {{
        background: {COLORS["ordered_background"]};
        border-color: {COLORS["ordered_accent"]};
    }}
    QLabel#pickupRemaining {{
        color: {COLORS["accent"]};
        min-width: {2 * MENU_BADGE_WIDTH}px;
    }}
    QFrame#pickupRow[complete="true"] QLabel#pickupRemaining {{
        color: {COLORS["ordered_accent"]};
    }}
    QLabel#menuNumber {{
        color: {COLORS["text_secondary"]};
        min-width: {MENU_BADGE_WIDTH}px;
    }}
    QLabel#menuNumber[ordered="true"] {{
        color: {COLORS["ordered_accent"]};
    }}
    QTableWidget {{
        background: {COLORS["surface"]};
        border: {BORDER_WIDTH}px solid {COLORS["border"]};
        gridline-color: {COLORS["border"]};
    }}
    QTableWidget::item:selected {{
        background: {COLORS["accent"]};
        color: {COLORS["surface"]};
    }}
    QHeaderView::section {{
        background: {COLORS["background"]};
        border: 0px;
        border-bottom: {BORDER_WIDTH}px solid {COLORS["border"]};
        padding: {SPACING["xs"]}px {SPACING["sm"]}px;
    }}
    QGroupBox {{
        background: transparent;
        border: 0px;
        margin-top: {SPACING["md"]}px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 0px;
        color: {COLORS["accent"]};
    }}
    QScrollArea {{
        background: transparent;
        border: 0px;
    }}
    """


def apply_theme(application: QApplication | None = None) -> None:
    """Nastaví globální font a jediný QSS blok."""

    target = application or QApplication.instance()
    if target is None:
        return
    target.setFont(font(TextRole.BODY))
    target.setStyleSheet(style_sheet())


def repolish(widget: QWidget) -> None:
    """Vynutí přepočet QSS po změně dynamické property."""

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
