"""Vizuální stav výdeje: dominantní ZBÝVÁ a typografie FÁZE 3C."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFrame, QLabel

from jll.gui import theme
from jll.gui.read_overview_dialog import PickupStatusPanel
from jll.gui.theme import TextRole
from jll.read_models import PickupStatusRow


def panel(qtbot: Any, rows: list[PickupStatusRow]) -> PickupStatusPanel:
    widget = PickupStatusPanel()
    qtbot.addWidget(widget)
    widget.render(rows)
    return widget


def row_frames(widget: PickupStatusPanel) -> list[QFrame]:
    return [
        frame
        for frame in widget.findChildren(QFrame)
        if frame.objectName() == "pickupRow"
    ]


def remaining_label(frame: QFrame) -> QLabel:
    labels = [
        label
        for label in frame.findChildren(QLabel)
        if label.objectName() == "pickupRemaining"
    ]
    assert len(labels) == 1
    return labels[0]


def test_remaining_is_the_dominant_value(qtbot: Any) -> None:
    widget = panel(qtbot, [PickupStatusRow("Oběd", 1, 40, 12)])
    frame = row_frames(widget)[0]
    value = remaining_label(frame)

    assert value.text() == "28"
    assert value.property("textRole") == TextRole.PRIMARY.value
    captions = [
        label
        for label in frame.findChildren(QLabel)
        if label.text() == "ZBÝVÁ"
    ]
    assert len(captions) == 1
    assert captions[0].property("textRole") == TextRole.META.value
    assert (
        value.font().pointSizeF() > captions[0].font().pointSizeF()
    )


def test_ordered_and_picked_up_stay_readable_context(qtbot: Any) -> None:
    widget = panel(qtbot, [PickupStatusRow("Oběd", 2, 40, 12)])
    texts = [
        label.text() for label in row_frames(widget)[0].findChildren(QLabel)
    ]
    assert "Oběd · menu 2" in texts
    assert "Objednáno 40 · vydáno 12" in texts


def test_finished_row_is_marked_as_complete(qtbot: Any) -> None:
    widget = panel(
        qtbot,
        [
            PickupStatusRow("Oběd", 1, 10, 10),
            PickupStatusRow("Oběd", 2, 10, 3),
        ],
    )
    finished, running = row_frames(widget)

    assert finished.property("complete") == "true"
    assert running.property("complete") == "false"
    assert remaining_label(finished).text() == "0"
    assert remaining_label(running).text() == "7"


def test_completed_state_is_styled_by_central_theme() -> None:
    qss = theme.style_sheet()
    assert 'QFrame#pickupRow[complete="true"]' in qss
    assert "QLabel#pickupRemaining" in qss
    assert theme.COLORS["ordered_accent"] in qss


def test_empty_day_shows_message_and_no_panels(qtbot: Any) -> None:
    widget = panel(qtbot, [])
    assert row_frames(widget) == []
    assert widget.empty_label.isVisible() or not widget.isVisible()
    assert "nejsou žádné objednávky" in widget.empty_label.text()


def test_rerender_replaces_previous_rows(qtbot: Any) -> None:
    widget = panel(qtbot, [PickupStatusRow("Oběd", 1, 5, 1)])
    widget.render([PickupStatusRow("Večeře", 3, 8, 8)])

    frames = row_frames(widget)
    assert len(frames) == 1
    assert remaining_label(frames[0]).text() == "0"
    assert widget.rows == [PickupStatusRow("Večeře", 3, 8, 8)]
