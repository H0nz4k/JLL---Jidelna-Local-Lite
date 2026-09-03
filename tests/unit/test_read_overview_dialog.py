from __future__ import annotations

from datetime import date
from typing import Any

from jll.gui.read_overview_dialog import PickupStatusDialog, ReportsDialog
from jll.read_models import DinerReportRow, OrderReportRow, PickupStatusRow


class _ReadService:
    def load_pickup_status(self, _target: date) -> list[PickupStatusRow]:
        return [PickupStatusRow("Oběd", 1, 12, 5)]

    def load_order_report(self, _target: date) -> list[OrderReportRow]:
        return [OrderReportRow("Oběd", 1, 12, "LAB jídlo")]

    def load_diner_report(self) -> list[DinerReportRow]:
        return [DinerReportRow(123, "LAB Test", "KAT2", "8.A")]


def test_pickup_dialog_loads_batch_status_off_gui_thread(
    qtbot: Any,
) -> None:
    dialog = PickupStatusDialog(_ReadService(), date(2026, 9, 3))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: len(dialog.panel.rows) == 1)
    row = dialog.panel.rows[0]
    assert (row.ordered, row.picked_up, row.remaining) == (12, 5, 7)


def test_reports_dialog_loads_scoped_previews_off_gui_thread(
    qtbot: Any,
) -> None:
    dialog = ReportsDialog(_ReadService(), date(2026, 9, 3))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(
        lambda: dialog.orders.rowCount() == 1 and dialog.diners.rowCount() == 1
    )
    assert dialog.orders.item(0, 3).text() == "LAB jídlo"
    assert dialog.diners.item(0, 1).text() == "KAT2"
