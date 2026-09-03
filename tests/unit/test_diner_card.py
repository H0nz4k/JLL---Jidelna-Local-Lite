"""Karta strávníka a náhledy zápisových formulářů."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from PySide6.QtWidgets import QFormLayout, QLabel

from jll.gui.diner_card_dialog import (
    SAVE_BLOCKED_TEXT,
    UNKNOWN_VALUE,
    DinerCardDialog,
    DinerFormDialog,
)
from jll.policy import Permission, SessionPolicy
from jll.read_models import DinerChip, DinerFinance, DinerProfile
from jll.write_gates import DINER_WRITE_GATES

SECRET_COLUMNS = ("pin", "heslo", "rodne", "rc", "password", "hash")


def profile(
    chips: tuple[DinerChip, ...] = (),
    credit: Decimal = Decimal("512.50"),
    minimum: Decimal = Decimal("-100.00"),
) -> DinerProfile:
    return DinerProfile(
        evidcislo=123,
        name="LAB Test",
        category="KAT2",
        category_name="Žáci druhý stupeň",
        category_norm="B",
        class_name="8.A",
        birth_date=date(2012, 5, 17),
        variable_symbol="123456",
        payment_method="Inkaso",
        state_code="A",
        state_label="Aktivní",
        note=None,
        finance=DinerFinance(credit, minimum),
        chips=chips,
    )


def policy(permissions: frozenset[Permission] | None = None) -> SessionPolicy:
    return SessionPolicy(
        "LAB tester",
        frozenset({"KAT2"}),
        permissions
        or frozenset({Permission.DINERS_VIEW, Permission.CHIPS_VIEW}),
    )


class FakeCardService:
    def __init__(self, value: DinerProfile | Exception) -> None:
        self.value = value
        self.calls: list[int] = []

    def load_diner_profile(self, evidcislo: int) -> DinerProfile:
        self.calls.append(evidcislo)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def build_card(
    qtbot: Any,
    service: FakeCardService | None = None,
    session: SessionPolicy | None = None,
    highlight_chip: str | None = None,
) -> DinerCardDialog:
    dialog = DinerCardDialog(
        service or FakeCardService(profile()),  # type: ignore[arg-type]
        123,
        session or policy(),
        highlight_chip=highlight_chip,
    )
    qtbot.addWidget(dialog)
    return dialog


def test_card_shows_only_documented_columns(qtbot: Any) -> None:
    service = FakeCardService(profile())
    dialog = build_card(qtbot, service)
    qtbot.waitUntil(lambda: dialog.profile is not None)

    assert service.calls == [123]
    assert dialog.name_label.text() == "LAB Test"
    assert dialog.detail_fields["category"].text() == "KAT2 – Žáci druhý stupeň"
    assert dialog.detail_fields["norm"].text() == "B"
    assert dialog.detail_fields["birth_date"].text() == "17.05.2012"
    assert dialog.detail_fields["state"].text() == "Aktivní"
    assert dialog.detail_fields["note"].text() == UNKNOWN_VALUE

    captions = [
        dialog.details_form.itemAt(row, QFormLayout.LabelRole)
        .widget()
        .text()
        .casefold()
        for row in range(dialog.details_form.rowCount())
    ]
    for secret in SECRET_COLUMNS:
        assert all(secret not in caption for caption in captions)


def test_card_finance_uses_documented_credit_and_limit(qtbot: Any) -> None:
    dialog = build_card(qtbot)
    qtbot.waitUntil(lambda: dialog.profile is not None)

    assert "512,50" in dialog.finance_fields["credit"].text()
    assert "-100,00" in dialog.finance_fields["minimum"].text()
    assert "612,50" in dialog.finance_fields["headroom"].text()


def test_headroom_is_credit_minus_allowed_minimum() -> None:
    finance = DinerFinance(Decimal("10.00"), Decimal("-50.00"))
    assert finance.headroom == Decimal("60.00")


def test_card_lists_chips_and_marks_identified_one(qtbot: Any) -> None:
    chips = (
        DinerChip("0000000000098765", "P", "Přidělen"),
        DinerChip("0000000000011111", "Z", "Ztracen"),
    )
    dialog = build_card(
        qtbot,
        FakeCardService(profile(chips)),
        highlight_chip="0000000000011111",
    )
    qtbot.waitUntil(lambda: dialog.profile is not None)

    assert dialog.chips_table.rowCount() == 2
    codes = [
        dialog.chips_table.item(row, 0).text()
        for row in range(dialog.chips_table.rowCount())
    ]
    assert codes == ["0000000000098765", "0000000000011111"]
    assert dialog.chips_table.item(1, 1).text() == "Ztracen"
    assert dialog.chips_table.item(1, 0).font().bold()
    assert not dialog.chips_table.item(0, 0).font().bold()


def test_chip_section_hidden_without_chip_permission(qtbot: Any) -> None:
    dialog = build_card(
        qtbot,
        session=policy(frozenset({Permission.DINERS_VIEW})),
    )
    dialog.show()
    qtbot.waitUntil(lambda: dialog.profile is not None)
    assert not dialog.chips_group.isVisible()


def test_card_without_chips_says_so(qtbot: Any) -> None:
    dialog = build_card(qtbot)
    qtbot.waitUntil(lambda: dialog.profile is not None)
    assert dialog.chips_table.rowCount() == 0
    assert "nemá žádný evidovaný čip" in dialog.chips_note.text()


def test_failed_load_never_shows_partial_identity(qtbot: Any) -> None:
    dialog = build_card(qtbot, FakeCardService(RuntimeError("DB je pryč")))
    qtbot.waitUntil(lambda: "není dostupný" in dialog.name_label.text())
    assert dialog.profile is None
    assert dialog.detail_fields["evidcislo"].text() == UNKNOWN_VALUE
    assert dialog.finance_fields["credit"].text() == UNKNOWN_VALUE


@pytest.mark.parametrize("gate_key", ["edit_personal", "create"])
def test_form_preview_cannot_save(qtbot: Any, gate_key: str) -> None:
    gate = DINER_WRITE_GATES[gate_key]
    dialog = DinerFormDialog(
        gate,
        title="Náhled",
        profile=profile() if gate_key == "edit_personal" else None,
    )
    qtbot.addWidget(dialog)

    assert not gate.enabled
    assert not dialog.save_button.isEnabled()
    assert dialog.save_button.toolTip() == gate.tooltip
    assert all(field.isReadOnly() for field in dialog.fields.values())


def test_edit_preview_shows_current_values(qtbot: Any) -> None:
    dialog = DinerFormDialog(
        DINER_WRITE_GATES["edit_personal"],
        title="Náhled",
        profile=profile(),
    )
    qtbot.addWidget(dialog)
    assert dialog.fields["name"].text() == "LAB Test"
    assert dialog.fields["evidcislo"].text() == "123"
    assert dialog.fields["category"].text() == "KAT2"


def test_create_preview_starts_empty_and_explains_evidcislo(
    qtbot: Any,
) -> None:
    dialog = DinerFormDialog(
        DINER_WRITE_GATES["create"],
        title="Náhled",
        profile=None,
    )
    qtbot.addWidget(dialog)
    assert all(not field.text() for field in dialog.fields.values())
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("evidenční číslo" in text.casefold() for text in texts)
    assert any(SAVE_BLOCKED_TEXT in text for text in texts)
