from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    succeeded = Signal(int, object, float)
    failed = Signal(int, object, float)


class FunctionWorker(QRunnable):
    def __init__(
        self,
        request_id: int,
        operation: Callable[[], Any],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            result = self.operation()
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            self.signals.failed.emit(self.request_id, exc, duration_ms)
            return
        duration_ms = (time.perf_counter() - started) * 1000
        self.signals.succeeded.emit(self.request_id, result, duration_ms)
