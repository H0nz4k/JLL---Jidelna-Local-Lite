"""Daily reports viewmodel."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ...policy import Permission
from ...read_models import DailyReport
from ..state import AppState


class ReportsViewModel:
    def __init__(self, state: AppState) -> None:
        self.state = state

    def can_view(self) -> bool:
        return self.state.has_perm(Permission.REPORTS_VIEW)

    def can_print(self) -> bool:
        return self.state.has_perm(Permission.REPORTS_PRINT)

    def today(self) -> date:
        assert self.state.read_service is not None
        return self.state.read_service.server_today()

    def tomorrow(self) -> date:
        return self.today() + timedelta(days=1)

    def next_cooking_day(self) -> date | None:
        assert self.state.read_service is not None
        return self.state.read_service.next_cooking_day(after=self.today())

    def load(self, target: date) -> DailyReport:
        assert self.state.read_service is not None
        return self.state.read_service.load_daily_report(target)

    def export_pdf(self, report: DailyReport, path: Path) -> Path:
        from ...reports_pdf import create_report_pdf

        create_report_pdf(report, path)
        return path
