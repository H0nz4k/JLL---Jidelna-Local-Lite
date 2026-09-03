"""Denní sestavy: agregace, dialog a PDF export."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from jll.gui.report_dialog import NO_ORDERS_TEXT, DailyReportDialog
from jll.policy import Permission, SessionPolicy
from jll.read_models import (
    MISSING_MEAL_NAME,
    MISSING_NORM,
    CategoryOrderSummary,
    DailyReport,
    NamedOrderRow,
    NormMenuSummary,
    OrderReportRow,
)
from jll.reports import group_by_category, norm_matrices, sort_named_rows

TARGET = date(2026, 9, 4)


def named(
    name: str,
    category: str = "KAT2",
    category_name: str | None = "Žáci druhý stupeň",
    norm: str | None = "B",
    meal_type: str = "Oběd",
    menu: int = 1,
    meal_name: str | None = "Svíčková",
    evidcislo: int = 1,
) -> NamedOrderRow:
    return NamedOrderRow(
        evidcislo=evidcislo,
        name=name,
        category=category,
        category_name=category_name,
        norm=norm,
        meal_type=meal_type,
        menu=menu,
        meal_name=meal_name,
    )


def report(
    diners: tuple[NamedOrderRow, ...] = (),
    menus: tuple[OrderReportRow, ...] = (),
    categories: tuple[CategoryOrderSummary, ...] = (),
    norms: tuple[NormMenuSummary, ...] = (),
) -> DailyReport:
    return DailyReport(
        target_date=TARGET,
        subject_name="DEMO LAB",
        menus=menus,
        categories=categories,
        norms=norms,
        diners=diners,
    )


def full_report() -> DailyReport:
    return report(
        diners=(
            named("Čermák Adam", evidcislo=3),
            named("adamec bořek", evidcislo=1, menu=2, meal_name=None),
            named(
                "Zdeněk Cyril",
                category="KAT1",
                category_name="Zaměstnanci",
                norm=None,
                evidcislo=2,
            ),
        ),
        menus=(
            OrderReportRow("Oběd", 1, 2, "Svíčková"),
            OrderReportRow("Oběd", 2, 1, None),
        ),
        categories=(
            CategoryOrderSummary("KAT1", "Zaměstnanci", None, 1),
            CategoryOrderSummary("KAT2", "Žáci druhý stupeň", "B", 2),
        ),
        norms=(
            NormMenuSummary("Oběd", "B", 1, 2),
            NormMenuSummary("Oběd", None, 2, 1),
        ),
    )


def policy(
    permissions: frozenset[Permission] | None = None,
) -> SessionPolicy:
    return SessionPolicy(
        "LAB tester",
        frozenset({"KAT1", "KAT2"}),
        permissions
        or frozenset({Permission.REPORTS_VIEW, Permission.REPORTS_PRINT}),
    )


class FakeReportService:
    def __init__(
        self,
        value: DailyReport | Exception | None = None,
        *,
        today: date = date(2026, 9, 3),
        next_day: date | None = date(2026, 9, 7),
    ) -> None:
        self.value = value if value is not None else full_report()
        self.today = today
        self.next_day = next_day
        self.requested_dates: list[date] = []

    def server_today(self) -> date:
        return self.today

    def next_cooking_day(self, reference: date) -> date | None:
        self.next_reference = reference
        return self.next_day

    def load_daily_report(self, target: date) -> DailyReport:
        self.requested_dates.append(target)
        if isinstance(self.value, Exception):
            raise self.value
        return DailyReport(
            target_date=target,
            subject_name=self.value.subject_name,
            menus=self.value.menus,
            categories=self.value.categories,
            norms=self.value.norms,
            diners=self.value.diners,
        )


def build_dialog(
    qtbot: Any,
    service: FakeReportService | None = None,
    session: SessionPolicy | None = None,
) -> DailyReportDialog:
    service = service or FakeReportService()
    dialog = DailyReportDialog(
        service,  # type: ignore[arg-type]
        TARGET,
        session or policy(),
        allowed_categories=frozenset({"KAT2", "KAT1"}),
    )
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.report is not None)
    return dialog


def test_named_rows_sort_by_name_then_meal_and_menu() -> None:
    rows = sort_named_rows(full_report().diners)
    assert [row.name for row in rows] == [
        "adamec bořek",
        "Čermák Adam",
        "Zdeněk Cyril",
    ]


def test_diacritics_do_not_break_alphabetical_order() -> None:
    rows = sort_named_rows(
        (
            named("Dvořák Jan", evidcislo=4),
            named("Čermák Adam", evidcislo=3),
            named("Cejnar Petr", evidcislo=2),
        )
    )
    assert [row.name for row in rows] == [
        "Cejnar Petr",
        "Čermák Adam",
        "Dvořák Jan",
    ]


def test_grouping_follows_given_order_and_skips_empty_categories() -> None:
    blocks = group_by_category(full_report().diners, ("KAT2", "KAT1", "KAT9"))
    assert [block.category for block in blocks] == ["KAT2", "KAT1"]
    assert blocks[0].label == "Žáci druhý stupeň"
    assert [row.name for row in blocks[0].rows] == [
        "adamec bořek",
        "Čermák Adam",
    ]


def test_norm_matrix_keeps_all_default_norms_with_zero() -> None:
    matrix = norm_matrices(full_report().norms)[0]
    assert matrix.meal_type == "Oběd"
    assert matrix.menus == (1, 2)
    assert matrix.norms[:4] == ("A", "B", "C", "D")
    assert MISSING_NORM in matrix.norms
    assert matrix.portions("B", 1) == 2
    assert matrix.portions("A", 1) == 0
    assert matrix.menu_total(2) == 1
    assert matrix.norm_total("B") == 2
    assert matrix.total == 3


def test_report_totals_come_from_portions_not_row_count() -> None:
    data = full_report()
    assert data.total_portions == 3
    assert data.total_orders == 3


def test_dialog_renders_named_list_and_summaries(qtbot: Any) -> None:
    dialog = build_dialog(qtbot)

    assert dialog.named_table.rowCount() == 3
    assert dialog.named_table.item(0, 0).text() == "adamec bořek"
    assert dialog.named_table.item(0, 5).text() == MISSING_MEAL_NAME
    assert dialog.named_table.item(2, 4).text() == MISSING_NORM
    assert dialog.menu_table.rowCount() == 2
    assert dialog.category_table.rowCount() == 2
    assert dialog.norm_table.rowCount() == len(("A", "B", "C", "D", "x")) * 2
    assert "Celkem porcí: 3" in dialog.summary_label.text()
    assert "04.09.2026" in dialog.day_label.text()


def test_grouped_named_list_adds_category_headers(qtbot: Any) -> None:
    dialog = build_dialog(qtbot)
    dialog.grouped_radio.setChecked(True)

    headers = [
        dialog.named_table.item(row, 0).text()
        for row in range(dialog.named_table.rowCount())
        if dialog.named_table.item(row, 0).text().startswith("—")
    ]
    assert headers == [
        "— Zaměstnanci (1) —",
        "— Žáci druhý stupeň (2) —",
    ]
    assert dialog.named_table.rowCount() == 5
    assert dialog.named_table.item(1, 0).text() == "Zdeněk Cyril"


def test_empty_day_is_reported_without_fake_rows(qtbot: Any) -> None:
    dialog = build_dialog(qtbot, FakeReportService(report()))
    assert dialog.named_table.rowCount() == 0
    assert dialog.summary_label.text() == NO_ORDERS_TEXT


def test_today_and_tomorrow_use_server_business_date(qtbot: Any) -> None:
    service = FakeReportService()
    dialog = build_dialog(qtbot, service)

    dialog.today_button.click()
    qtbot.waitUntil(lambda: dialog.target_date == date(2026, 9, 3))
    dialog.tomorrow_button.click()
    qtbot.waitUntil(lambda: dialog.target_date == date(2026, 9, 4))
    assert service.requested_dates[-2:] == [date(2026, 9, 3), date(2026, 9, 4)]


def test_next_cooking_day_jumps_to_service_answer(qtbot: Any) -> None:
    service = FakeReportService()
    dialog = build_dialog(qtbot, service)

    dialog.next_cooking_button.click()
    qtbot.waitUntil(lambda: dialog.target_date == date(2026, 9, 7))
    assert service.next_reference == TARGET
    assert dialog.next_cooking_button.isEnabled()


def test_missing_cooking_day_keeps_current_date(qtbot: Any) -> None:
    service = FakeReportService(next_day=None)
    dialog = build_dialog(qtbot, service)

    dialog.next_cooking_button.click()
    qtbot.waitUntil(lambda: dialog.next_cooking_button.isEnabled())
    assert dialog.target_date == TARGET
    assert "varný den" in dialog.status_label.text()


def test_selected_date_reloads_report(qtbot: Any) -> None:
    from PySide6.QtCore import QDate

    service = FakeReportService()
    dialog = build_dialog(qtbot, service)
    dialog.date_edit.setDate(QDate(2026, 9, 10))
    qtbot.waitUntil(lambda: date(2026, 9, 10) in service.requested_dates)


def test_failed_report_shows_safe_status(qtbot: Any) -> None:
    service = FakeReportService(RuntimeError("spojení selhalo"))
    dialog = DailyReportDialog(
        service,  # type: ignore[arg-type]
        TARGET,
        policy(),
    )
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: "nelze načíst" in dialog.status_label.text())
    assert dialog.report is None
    assert dialog.named_table.rowCount() == 0


def test_pdf_button_needs_print_permission(qtbot: Any) -> None:
    dialog = build_dialog(
        qtbot,
        session=policy(frozenset({Permission.REPORTS_VIEW})),
    )
    dialog.show()
    assert not dialog.print_button.isVisible()

    allowed = build_dialog(qtbot)
    allowed.show()
    assert allowed.print_button.isVisible()


def test_pdf_export_writes_a_readable_file(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    from jll.reports_pdf import create_report_pdf

    target = tmp_path / "sestava.pdf"
    created = create_report_pdf(full_report(), target, grouped=True)

    assert created == target.resolve()
    content = target.read_bytes()
    assert content.startswith(b"%PDF-")
    assert content.rstrip().endswith(b"%%EOF")
    assert target.stat().st_size > 1000
    assert not list(tmp_path.glob(".*.tmp.pdf"))


def test_pdf_export_rejects_non_pdf_target(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    from jll.reports_pdf import create_report_pdf

    with pytest.raises(ValueError):
        create_report_pdf(full_report(), tmp_path / "sestava.txt")


def test_pdf_font_override_must_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jll.reports_pdf import (
        FONT_ENV_VARIABLE,
        PdfDependencyMissing,
        resolve_report_fonts,
    )

    monkeypatch.setenv(FONT_ENV_VARIABLE, str(tmp_path / "chybi.ttf"))
    with pytest.raises(PdfDependencyMissing):
        resolve_report_fonts()


def test_pdf_uses_font_with_czech_diacritics(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    from reportlab.pdfbase.ttfonts import TTFont

    from jll.reports_pdf import resolve_report_fonts

    regular, _bold = resolve_report_fonts()
    font = TTFont("JllProbe", str(regular))
    face = font.face
    for character in "ěščřžýáíéúůňťďĚŠČŘŽ":
        assert face.charToGlyph.get(ord(character))
