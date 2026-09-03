"""Řádek denního jídelníčku. Celý řádek je klikací hit-area."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from . import theme
from .theme import TextRole


def format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))} Kč".replace(".", ",")


class MenuRow(QFrame):
    """Jedno číslo menu jednoho typu stravy.

    Klik kamkoli do řádku spustí pouze bezpečný přihlašovací záměr.
    Odhlášení je vždy jen explicitní tlačítko, proto klik na již objednaný
    řádek nikdy nic nemaže.
    """

    activated = Signal()
    action_triggered = Signal()

    def __init__(
        self,
        menu: int,
        dish_name: str,
        price: Decimal,
        *,
        ordered: bool,
        published: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("menuRow")
        self.menu = menu
        self._ordered = ordered
        self._clickable = False
        self.setMinimumHeight(theme.ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setProperty("ordered", ordered)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING["md"],
            theme.SPACING["sm"],
            theme.SPACING["md"],
            theme.SPACING["sm"],
        )
        layout.setSpacing(theme.SPACING["lg"])

        self.number_label = QLabel(str(menu))
        self.number_label.setObjectName("menuNumber")
        self.number_label.setProperty("ordered", ordered)
        self.number_label.setAlignment(Qt.AlignCenter)
        theme.apply_role(self.number_label, TextRole.ACTION)
        layout.addWidget(self.number_label)

        self.dish_label = QLabel(
            f"{dish_name}   ✓ OBJEDNÁNO" if ordered else dish_name
        )
        self.dish_label.setWordWrap(True)
        self.dish_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if ordered:
            theme.apply_role(self.dish_label, TextRole.ACTION)
            self.dish_label.setProperty("tone", "ordered")
        else:
            theme.apply_role(self.dish_label, TextRole.BODY)
            if not published:
                self.dish_label.setProperty("tone", "secondary")
        layout.addWidget(self.dish_label, 1)

        self.price_label = QLabel(format_money(price))
        self.price_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        theme.apply_role(self.price_label, TextRole.META)
        layout.addWidget(self.price_label)

        self.action_button = QPushButton()
        theme.apply_role(self.action_button, TextRole.ACTION)
        self.action_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.action_button.clicked.connect(self.action_triggered.emit)
        layout.addWidget(self.action_button)

        self.diagnostic_label = QLabel()
        self.diagnostic_label.setToolTip("Diagnostický DB stav")
        theme.apply_role(self.diagnostic_label, TextRole.META)
        self.diagnostic_label.setVisible(False)
        layout.addWidget(self.diagnostic_label)

        for label in self.hit_area_labels():
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    @property
    def ordered(self) -> bool:
        return self._ordered

    @property
    def clickable(self) -> bool:
        return self._clickable

    def hit_area_labels(self) -> tuple[QLabel, ...]:
        """Popisky nesmí ukrojit hit-area; klik na text patří celému řádku."""

        return (
            self.number_label,
            self.dish_label,
            self.price_label,
            self.diagnostic_label,
        )

    def set_clickable(self, clickable: bool, hint: str) -> None:
        self._clickable = clickable
        self.setProperty("clickable", clickable)
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.setToolTip(hint)
        self.number_label.setToolTip(hint)
        self.dish_label.setToolTip(hint)
        self.price_label.setToolTip(hint)
        theme.repolish(self)

    def set_diagnostic(self, text: str, visible: bool) -> None:
        self.diagnostic_label.setText(text)
        self.diagnostic_label.setVisible(visible)

    def activate(self) -> None:
        """Bezpečná aktivace řádku; objednaný řádek se nikdy neodhlásí."""

        if self._clickable:
            self.activated.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.activate()
        super().mouseReleaseEvent(event)
