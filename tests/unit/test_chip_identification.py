"""Čtení čipu a scope-safe workflow „Identifikovat čip“."""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from PySide6.QtWidgets import QMessageBox

from jll.application import OrderApplicationService
from jll.chip_reader import (
    ChipRead,
    FakeChipReader,
    UnavailableChipReader,
)
from jll.config import LabConfig
from jll.gui.chip_dialog import (
    CANCELLED_MESSAGE,
    TIMEOUT_MESSAGE,
    ChipReadDialog,
)
from jll.gui.main_window import MainWindow
from jll.identity import ActorContext
from jll.orders.models import OrderAction
from jll.policy import Permission, SessionPolicy
from jll.read_models import (
    CHIP_NOT_FOUND,
    CHIP_OUT_OF_SCOPE,
    CHIP_OWNER_UNAVAILABLE,
    ActionAvailability,
    ChipIdentification,
    DinerDay,
    DinerDetail,
    DinerSummary,
    LabDiagnostics,
    MealDay,
    MenuOption,
)
from jll.read_service import normalize_chip_code


def lab_config() -> LabConfig:
    return LabConfig(
        site_name="DEMO LAB",
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        allowed_categories=frozenset({"KAT2"}),
        host="127.0.0.1",
        port=5433,
        database="jll_test",
        user="postgres",
        environment="lab",
        expected_system_identifier="1000000000000000001",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
        reader_port="COM4",
    )


def session_policy(
    permissions: frozenset[Permission] | None = None,
) -> SessionPolicy:
    return SessionPolicy(
        "LAB tester",
        frozenset({"KAT2"}),
        permissions
        or frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.CHIPS_VIEW,
                Permission.ORDERS_VIEW,
            }
        ),
    )


def actor_context() -> ActorContext:
    return ActorContext(
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        user_id="tester",
        short_code="TST",
        session_id="session-1",
        client_version="0.1",
    )


def day_view(target: date = date(2026, 9, 4)) -> DinerDay:
    days = calendar.monthrange(target.year, target.month)[1]
    return DinerDay(
        diner=DinerDetail(123, "LAB Test", "KAT2", "8.A", Decimal("500")),
        target_date=target,
        server_now=datetime(2026, 9, 3, 8),
        meals=(
            MealDay(
                code="A",
                meal_type="Oběd-A",
                display_order=1,
                current_state="N",
                options=(MenuOption(1, "Jídlo", Decimal("83")),),
                availability=tuple(
                    ActionAvailability(action, True) for action in OrderAction
                ),
                exclusive_codes=frozenset(),
                allowed_menus=(1,),
                month_states=tuple("N" for _ in range(days)),
                cooking_days=frozenset(range(1, days + 1)),
            ),
        ),
    )


class FakeReadService:
    def __init__(self, identification: ChipIdentification | None = None) -> None:
        self.identification = identification
        self.identify_calls: list[str] = []
        self.view = day_view()

    def verify_lab(self) -> LabDiagnostics:
        return LabDiagnostics(
            "jll_test",
            "127.0.0.1",
            5433,
            "1000000000000000001",
            "Europe/Prague",
        )

    def server_today(self) -> date:
        return date(2026, 9, 3)

    def search_diners(self, _text: str) -> list[DinerSummary]:
        return []

    def list_diners(self) -> list[DinerSummary]:
        return []

    def load_diner_day(self, _evidcislo: int, _target: date) -> DinerDay:
        return self.view

    def identify_chip(self, code: str) -> ChipIdentification:
        self.identify_calls.append(code)
        assert self.identification is not None
        return self.identification


class FakeOrderService:
    def execute(self, _command: Any) -> Any:
        return object()


def build_window(
    qtbot: Any,
    read: FakeReadService | None = None,
    policy: SessionPolicy | None = None,
    reader: Any = None,
) -> MainWindow:
    read = read or FakeReadService()
    application = OrderApplicationService(
        FakeOrderService(),  # type: ignore[arg-type]
        read,  # type: ignore[arg-type]
        policy or session_policy(),
        actor_context,
    )
    window = MainWindow(
        config=lab_config(),
        read_service=read,  # type: ignore[arg-type]
        application_service=application,
        chip_reader=reader if reader is not None else FakeChipReader(),
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.search_edit.isEnabled())
    return window


def test_normalized_chip_code_keeps_only_plausible_values() -> None:
    assert normalize_chip_code("  0012 ") == "0012"
    for invalid in ("", "   ", "12345678901234567", "12-34", "abc def"):
        with pytest.raises(ValueError):
            normalize_chip_code(invalid)


def test_reader_dialog_reads_one_chip_and_accepts(qtbot: Any) -> None:
    reader = FakeChipReader(["0000000000098765"])
    dialog = ChipReadDialog(reader, timeout_seconds=2)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.read_succeeded, timeout=3000):
        dialog.start_read()
    assert isinstance(dialog.chip_read, ChipRead)
    assert dialog.chip_read.code == "0000000000098765"
    assert dialog.error_message is None


def test_reader_dialog_times_out_with_human_message(qtbot: Any) -> None:
    reader = FakeChipReader()
    dialog = ChipReadDialog(reader, timeout_seconds=0.3)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.read_failed, timeout=5000) as blocker:
        dialog.start_read()
    assert blocker.args == [TIMEOUT_MESSAGE]
    assert dialog.error_message == TIMEOUT_MESSAGE
    assert dialog.chip_read is None


def test_reader_dialog_cancellation_stops_waiting(qtbot: Any) -> None:
    reader = FakeChipReader()
    dialog = ChipReadDialog(reader, timeout_seconds=25)
    qtbot.addWidget(dialog)
    dialog.start_read()
    dialog.cancel()
    assert dialog.error_message == CANCELLED_MESSAGE
    assert dialog.chip_read is None
    assert dialog.result() == ChipReadDialog.Rejected


def test_reader_dialog_reports_unavailable_reader(qtbot: Any) -> None:
    dialog = ChipReadDialog(
        UnavailableChipReader("Čtečka není nakonfigurována."),
        timeout_seconds=2,
    )
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.read_failed, timeout=3000) as blocker:
        dialog.start_read()
    assert blocker.args == ["Čtečka není nakonfigurována."]


def test_reader_dialog_rejects_unbounded_timeout(qtbot: Any) -> None:
    with pytest.raises(ValueError):
        ChipReadDialog(FakeChipReader(), timeout_seconds=0)
    with pytest.raises(ValueError):
        ChipReadDialog(FakeChipReader(), timeout_seconds=120)


def test_missing_chip_never_pretends_to_have_owner() -> None:
    result = ChipIdentification(code="0001", exists=False)
    assert result.message == CHIP_NOT_FOUND
    assert not result.opens_card


def test_out_of_scope_owner_is_never_disclosed() -> None:
    result = ChipIdentification(
        code="0001",
        exists=True,
        status_code="P",
        status_label="Přidělen",
        owner=None,
        owner_restricted=True,
    )
    assert result.message == CHIP_OUT_OF_SCOPE
    assert not result.opens_card
    assert result.owner is None


def test_chip_without_available_owner_is_reported_neutrally() -> None:
    result = ChipIdentification(
        code="0001",
        exists=True,
        status_code="V",
        status_label="Stav V (význam nedoložen)",
        owner=None,
        owner_restricted=False,
    )
    assert result.message == CHIP_OWNER_UNAVAILABLE


@pytest.mark.parametrize(
    ("status", "expected"),
    [("P", "Přidělen"), ("B", "Blokován"), ("Z", "Ztracen")],
)
def test_in_scope_owner_opens_card_with_documented_status(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: str,
) -> None:
    from jll.read_service import _chip_status_label

    identification = ChipIdentification(
        code="0000000000098765",
        exists=True,
        status_code=status,
        status_label=_chip_status_label(status),
        owner=DinerSummary(123, "LAB Test", "KAT2", "8.A"),
    )
    read = FakeReadService(identification)
    window = build_window(qtbot, read)
    opened: list[tuple[int, str | None]] = []
    monkeypatch.setattr(
        window,
        "open_diner_card",
        lambda evidcislo, highlight_chip=None: opened.append(
            (evidcislo, highlight_chip)
        ),
    )
    window._chip_identified(window._chip_lookup_generation, identification, 5.0)
    assert opened == [(123, "0000000000098765")]
    assert expected in identification.status_label


def test_unknown_chip_status_opens_card_without_guessing_meaning(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jll.read_service import _chip_status_label

    identification = ChipIdentification(
        code="0001",
        exists=True,
        status_code="V",
        status_label=_chip_status_label("V"),
        owner=DinerSummary(123, "LAB Test", "KAT2", "8.A"),
    )
    window = build_window(qtbot, FakeReadService(identification))
    opened: list[int] = []
    monkeypatch.setattr(
        window,
        "open_diner_card",
        lambda evidcislo, highlight_chip=None: opened.append(evidcislo),
    )
    window._chip_identified(window._chip_lookup_generation, identification, 5.0)
    assert opened == [123]
    assert "nedoložen" in identification.status_label
    assert "Vrácen" not in identification.status_label


@pytest.mark.parametrize(
    "identification",
    [
        ChipIdentification(code="0001", exists=False),
        ChipIdentification(
            code="0001",
            exists=True,
            owner=None,
            owner_restricted=True,
        ),
        ChipIdentification(
            code="0001",
            exists=True,
            owner=None,
            owner_restricted=False,
        ),
    ],
)
def test_unusable_identification_never_opens_a_card(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
    identification: ChipIdentification,
) -> None:
    window = build_window(qtbot, FakeReadService(identification))
    opened: list[int] = []
    messages: list[str] = []
    monkeypatch.setattr(
        window,
        "open_diner_card",
        lambda evidcislo, highlight_chip=None: opened.append(evidcislo),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: messages.append(args[2]),
    )
    window._chip_identified(window._chip_lookup_generation, identification, 5.0)
    assert opened == []
    assert messages == [identification.message]


def test_identify_button_needs_chip_permission(qtbot: Any) -> None:
    window = build_window(
        qtbot,
        policy=session_policy(
            frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW})
        ),
    )
    assert not window.identify_chip_button.isVisible()

    allowed = build_window(qtbot)
    assert allowed.identify_chip_button.isVisible()
    assert allowed.identify_chip_button.isEnabled()


def test_identify_button_explains_missing_reader(qtbot: Any) -> None:
    window = build_window(qtbot, reader=None)
    window.chip_reader = None
    window._refresh_policy()
    assert window.identify_chip_button.isVisible()
    assert not window.identify_chip_button.isEnabled()
    assert "Čtečka není nakonfigurována" in (
        window.identify_chip_button.toolTip()
    )


def test_identify_lookup_uses_scope_safe_read_service(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identification = ChipIdentification(
        code="0001",
        exists=True,
        owner=DinerSummary(123, "LAB Test", "KAT2", "8.A"),
    )
    read = FakeReadService(identification)
    window = build_window(qtbot, read)
    opened: list[int] = []
    monkeypatch.setattr(
        window,
        "open_diner_card",
        lambda evidcislo, highlight_chip=None: opened.append(evidcislo),
    )
    window._lookup_chip("0001")
    qtbot.waitUntil(lambda: opened == [123])
    assert read.identify_calls == ["0001"]
    assert window.identify_chip_button.isEnabled()
