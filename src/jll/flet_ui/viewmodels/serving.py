"""Pickup / serving status viewmodel."""

from __future__ import annotations

from datetime import date, timedelta

from ...policy import Permission
from ...read_models import PickupStatusRow
from ..state import AppState


class ServingViewModel:
    def __init__(self, state: AppState) -> None:
        self.state = state

    def can_view(self) -> bool:
        return self.state.has_perm(Permission.PICKUP_STATUS_VIEW)

    def load(self, target: date | None = None) -> tuple[date, list[PickupStatusRow]]:
        assert self.state.read_service is not None
        day = target or self.state.read_service.server_today()
        rows = list(self.state.read_service.load_pickup_status(day))
        return day, rows

    def remaining_total(self, rows: list[PickupStatusRow]) -> int:
        return sum(max(0, row.remaining) for row in rows)

    def ordered_total(self, rows: list[PickupStatusRow]) -> int:
        return sum(max(0, row.ordered) for row in rows)
