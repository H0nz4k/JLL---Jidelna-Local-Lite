"""Idle návrat na HOME z read-only karty strávníka."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

Clock = Callable[[], float]

DINER_IDLE_HOME_SECONDS = 60


@dataclass
class IdleHomeController:
    """Jeden testovatelný controller: monotonic last_activity + suppression flags."""

    timeout_seconds: float = DINER_IDLE_HOME_SECONDS
    clock: Clock = time.monotonic
    last_activity: float = field(default_factory=time.monotonic)
    diner_open: bool = False
    route_is_diners: bool = True
    modal_open: bool = False
    dirty_form: bool = False
    write_in_flight: bool = False

    def note_activity(self) -> None:
        self.last_activity = self.clock()

    def set_diner_open(self, open_: bool) -> None:
        self.diner_open = open_
        if open_:
            self.note_activity()

    def should_return_home(self, *, now: float | None = None) -> bool:
        """True = bezpečně přejít na HOME (privacy reset)."""

        if not self.route_is_diners:
            return False
        if not self.diner_open:
            return False
        if self.modal_open or self.dirty_form or self.write_in_flight:
            return False
        current = self.clock() if now is None else now
        return (current - self.last_activity) >= self.timeout_seconds
