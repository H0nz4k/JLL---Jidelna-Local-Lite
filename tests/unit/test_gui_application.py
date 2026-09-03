from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QDate, QThread, QThreadPool, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from jll.application import (
    ERROR_TEXTS,
    OrderApplicationService,
    determine_action,
    present_error,
)
from jll.config import LabConfig, load_lab_config
from jll.gui import main_window as main_window_module
from jll.gui import theme
from jll.gui.main_window import MainWindow
from jll.gui.theme import TextRole
from jll.gui.workers import FunctionWorker
from jll.identity import ActorContext
from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.orders.models import OrderAction
from jll.policy import Permission, SessionPolicy
from jll.read_models import (
    ActionAvailability,
    DinerChip,
    DinerDay,
    DinerDetail,
    DinerSummary,
    LabDiagnostics,
    MealDay,
    MenuOption,
)


def availability() -> tuple[ActionAvailability, ...]:
    return tuple(ActionAvailability(action, True) for action in OrderAction)


def test_chip_card_renders_documented_and_unknown_states() -> None:
    diner = DinerDetail(
        123,
        "LAB Test",
        "KAT2",
        "8.A",
        Decimal("10"),
        chips=(
            DinerChip("0001", "P", "Přidělen"),
            DinerChip("0002", "B", "Blokován"),
        ),
    )
    compact = MainWindow._chip_text(diner)
    assert compact.startswith("Čipy (2):")
    assert "0001 — Přidělen" in compact
    detail = MainWindow._chip_tooltip(diner)
    assert "0001 — Přidělen" in detail
    assert "0002 — Blokován" in detail


def test_single_chip_stays_fully_visible_in_compact_card() -> None:
    diner = DinerDetail(
        123,
        "LAB Test",
        "KAT2",
        "8.A",
        Decimal("10"),
        chips=(DinerChip("0000000000098765", "P", "Přidělen"),),
    )
    assert MainWindow._chip_text(diner) == "Čipy: 0000000000098765 — Přidělen"


def meal(
    code: str,
    name: str,
    state: str | None,
    menus: tuple[int, ...] = (1,),
    month_days: int = 30,
    cooking_days: frozenset[int] | None = None,
) -> MealDay:
    return MealDay(
        code=code,
        meal_type=name,
        display_order=1,
        current_state=state,
        options=tuple(
            MenuOption(menu, f"Jídlo {code}{menu}", Decimal("83"))
            for menu in menus
        ),
        availability=availability(),
        exclusive_codes=frozenset({"A", "B", "C", "D"} - {code}),
        allowed_menus=menus,
        month_states=tuple(
            state if index == 3 else "N" for index in range(month_days)
        ),
        cooking_days=(
            frozenset(range(1, month_days + 1))
            if cooking_days is None
            else cooking_days
        ),
    )


def day_view(
    target: date = date(2026, 9, 4),
    lunch_menus: tuple[int, ...] = (1,),
    cooking_days: frozenset[int] | None = None,
) -> DinerDay:
    days_in_month = calendar.monthrange(target.year, target.month)[1]
    return DinerDay(
        diner=DinerDetail(123, "LAB Test", "KAT2", "8.A", Decimal("1000")),
        target_date=target,
        server_now=datetime(2026, 9, 3, 8),
        meals=(
            meal("A", "Oběd-A", "1", lunch_menus, days_in_month, cooking_days),
            meal("B", "Oběd-B", "N", lunch_menus, days_in_month, cooking_days),
            meal("C", "Oběd-C", "N", lunch_menus, days_in_month, cooking_days),
            meal("D", "Oběd-D", "N", lunch_menus, days_in_month, cooking_days),
        ),
    )


def build_window(
    qtbot: Any,
    read: FakeReadService | None = None,
    policy: SessionPolicy | None = None,
    write: FakeOrderService | None = None,
    size: tuple[int, int] = (1366, 728),
) -> MainWindow:
    read = read or FakeReadService()
    application = OrderApplicationService(
        write or FakeOrderService(),  # type: ignore[arg-type]
        read,  # type: ignore[arg-type]
        policy or session_policy(),
        actor_context,
    )
    window = MainWindow(config=lab_config(), read_service=read, application_service=application)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: window.search_edit.isEnabled())
    return window


class FakeReadService:
    def __init__(self, view: DinerDay | None = None) -> None:
        self.view = view or day_view()
        self.load_calls = 0

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
        self.load_calls += 1
        return self.view


class FakeOrderService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.commands: list[Any] = []
        self.failure = failure

    def execute(self, command: Any) -> Any:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return object()


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
                Permission.ORDERS_CHANGE,
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


@pytest.mark.parametrize(
    ("state", "menu", "expected"),
    [
        ("N", 1, OrderAction.MENU_ADD),
        ("S", 1, OrderAction.MENU_ADD),
        ("1", 1, OrderAction.MENU_DELETE),
        ("1", 2, OrderAction.MENU_CHANGE),
    ],
)
def test_action_mapping(
    state: str,
    menu: int,
    expected: OrderAction,
) -> None:
    target = MealDay(
        code="X",
        meal_type="Svačina",
        display_order=1,
        current_state=state,
        options=(
            MenuOption(1, "První", Decimal("20")),
            MenuOption(2, "Druhé", Decimal("21")),
        ),
        availability=availability(),
        exclusive_codes=frozenset(),
        allowed_menus=(1, 2),
    )
    assert determine_action(target, menu) is expected


def test_a_to_b_intent_calls_order_service_once_and_refreshes() -> None:
    read = FakeReadService()
    write = FakeOrderService()
    application = OrderApplicationService(
        write,  # type: ignore[arg-type]
        read,  # type: ignore[arg-type]
        session_policy(),
        actor_context,
    )

    outcome = application.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-B",
        1,
    )

    assert outcome.succeeded
    assert len(write.commands) == 1
    assert write.commands[0].action is OrderAction.MENU_ADD
    assert write.commands[0].typstravy == "Oběd-B"
    assert write.commands[0].allowed_categories == frozenset({"KAT2"})
    assert write.commands[0].actor == "DEMO-LAB01:TST"
    assert write.commands[0].actor != "JLL"
    assert read.load_calls == 2


def test_failed_write_still_refreshes_database_state() -> None:
    read = FakeReadService()
    write = FakeOrderService(
        OrderBusinessError(
            ErrorCode.CONCURRENT_MODIFICATION,
            "concurrent",
        )
    )
    application = OrderApplicationService(
        write,  # type: ignore[arg-type]
        read,  # type: ignore[arg-type]
        session_policy(),
        actor_context,
    )

    outcome = application.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-B",
        1,
    )

    assert not outcome.succeeded
    assert outcome.error is not None
    assert outcome.error.code == ErrorCode.CONCURRENT_MODIFICATION.value
    assert outcome.refreshed is not None
    assert read.load_calls == 2


def test_orders_change_permission_is_enforced_before_write() -> None:
    read = FakeReadService()
    write = FakeOrderService()
    policy = SessionPolicy(
        "read-only",
        frozenset({"KAT2"}),
        frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW}),
    )
    application = OrderApplicationService(
        write,  # type: ignore[arg-type]
        read,  # type: ignore[arg-type]
        policy,
        actor_context,
    )

    outcome = application.execute_selection(
        123,
        date(2026, 9, 4),
        "Oběd-B",
        1,
    )

    assert not outcome.succeeded
    assert write.commands == []
    assert read.load_calls == 1
    assert outcome.error is not None
    assert outcome.error.code == ErrorCode.OUT_OF_SCOPE_OR_INACTIVE.value


def test_all_business_error_codes_have_safe_czech_text() -> None:
    assert set(ERROR_TEXTS) == set(ErrorCode)
    for code in ErrorCode:
        shown = present_error(OrderBusinessError(code, "SQL detail nesmí ven"))
        assert shown.code == code.value
        assert "SQL detail" not in shown.user_message
        assert shown.correlation_id


def test_shipped_example_config_is_loadable() -> None:
    """README instruuje kopii šablony, takže musí projít validací."""

    example = Path(__file__).resolve().parents[2] / "config" / "lab.example.json"
    config = load_lab_config(example)
    assert config.environment == "lab"
    assert config.database.startswith("jll_")
    assert config.allowed_categories
    assert all(len(value) <= 5 for value in config.allowed_categories)


def test_config_fails_closed_for_empty_scope(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    path.write_text(
        """
        {
          "site_name": "LAB",
          "site_id": "DEMO",
          "instance_id": "DEMO-LAB01",
          "allowed_categories": [],
          "host": "127.0.0.1",
          "port": 5433,
          "database": "jll_test",
          "user": "postgres",
          "environment": "lab",
          "expected_system_identifier": "1000000000000000001",
          "business_timezone": "Europe/Prague",
          "strict_config_lock": true
        }
        """,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="allowed_categories"):
        load_lab_config(path)


def test_config_rejects_production_target() -> None:
    with pytest.raises(OrderBusinessError) as captured:
        LabConfig(
            site_name="invalid",
            site_id="DEMO",
            instance_id="DEMO-LAB01",
            allowed_categories=frozenset({"KAT2"}),
            host="db.example.test",
            port=5432,
            database="production",
            user="postgres",
            environment="prod",
            expected_system_identifier="1000000000000000001",
            business_timezone="Europe/Prague",
            strict_config_lock=True,
        )
    assert captured.value.code is ErrorCode.LAB_GUARD_FAILED


def test_stale_search_result_cannot_replace_newer_result(qtbot: Any) -> None:
    window = build_window(qtbot)
    old = [DinerSummary(1, "Starý výsledek", "KAT2", "")]
    new = [DinerSummary(2, "Nový výsledek", "KAT2", "")]

    window._search_generation = 2
    window._search_succeeded(1, old, 1.0)
    assert window.results.rowCount() == 0
    window._search_succeeded(2, new, 1.0)
    assert window.results.rowCount() == 1
    assert window.results.item(0, 0).text() == "Nový výsledek"
    assert window.date_edit.date() == QDate(2026, 9, 3)
    window._render_day(day_view())
    assert window.month_table.rowCount() == 4
    assert window.month_table.columnCount() == 30
    assert window.month_table.item(0, 3).text() == "1"
    assert any(
        button.text() == "Odhlásit 1"
        for button in window.findChildren(QPushButton)
    )


def test_database_worker_does_not_run_in_gui_thread(qtbot: Any) -> None:
    application = QApplication.instance()
    assert application is not None
    worker = FunctionWorker(
        7,
        lambda: QThread.currentThread() is application.thread(),
    )
    with qtbot.waitSignal(worker.signals.succeeded, timeout=2_000) as received:
        QThreadPool.globalInstance().start(worker)
    assert received.args[0] == 7
    assert received.args[1] is False


def test_search_keyboard_workflow_and_selected_diner_persistence(
    qtbot: Any,
) -> None:
    window = build_window(qtbot)
    diners = [
        DinerSummary(123, "První LAB", "KAT2", "1.A"),
        DinerSummary(456, "Druhý LAB", "KAT2", "2.A"),
    ]
    window._fill_results(diners)
    window.search_edit.setText("lab")
    window.search_edit.setFocus()
    qtbot.keyClick(window.search_edit, Qt.Key_Down)
    qtbot.waitUntil(lambda: window.results.currentRow() == 0)
    qtbot.keyClick(window.results, Qt.Key_Return)
    qtbot.waitUntil(lambda: window._current_diner is not None)
    selected = window._current_diner

    window._fill_results(list(reversed(diners)))
    assert window._current_diner == selected
    assert window.results.currentRow() == 1
    qtbot.keyClick(window, Qt.Key_F, Qt.ControlModifier)
    assert window.search_edit.hasFocus()
    qtbot.keyClick(window, Qt.Key_Escape)
    assert window.search_edit.text() == ""


def test_month_cell_immediately_selects_day(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view())
    window.date_edit.setDate(QDate(2026, 9, 4))
    window._month_cell_clicked(0, 9)
    assert window.date_edit.date() == QDate(2026, 9, 10)


def test_order_actions_are_disabled_without_permission(qtbot: Any) -> None:
    window = build_window(
        qtbot,
        policy=session_policy(
            frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW})
        ),
    )
    window._render_day(day_view())
    buttons = window.findChildren(QPushButton)
    unavailable = [button for button in buttons if button.text() == "Nedostupné"]
    assert unavailable
    assert all(not button.isEnabled() for button in unavailable)


def test_non_proven_chip_and_diner_writes_stay_disabled(qtbot: Any) -> None:
    window = build_window(qtbot, policy=session_policy(frozenset(Permission)))
    assert not window.new_diner_button.isEnabled()
    assert "PARTIAL" in window.new_diner_button.toolTip()
    assert not window.edit_diner_button.isEnabled()
    assert "BLOCKED" in window.edit_diner_button.toolTip()
    assert all(
        not button.isEnabled()
        and button.property("contractStatus") in {"PARTIAL", "BLOCKED"}
        for button in window.chip_action_buttons.values()
    )


def visible_rect(widget: QWidget) -> tuple[int, int, int, int]:
    top_left = widget.mapTo(widget.window(), widget.rect().topLeft())
    return (
        top_left.x(),
        top_left.y(),
        top_left.x() + widget.width(),
        top_left.y() + widget.height(),
    )


def settle(qtbot: Any, window: MainWindow) -> None:
    """Nechá Qt dokončit layout, aby měření nešlo z rozpracovaného stavu."""

    qtbot.waitUntil(lambda: window.month_table.viewport().width() > 0)
    qtbot.wait(30)


def assert_inside_window(window: MainWindow, widget: QWidget) -> None:
    left, top, right, bottom = visible_rect(widget)
    assert left >= 0 and top >= 0
    assert right <= window.width()
    assert bottom <= window.height()


@pytest.mark.parametrize(
    "size",
    [(1366, 728), (1440, 860), (1920, 1040)],
)
def test_layout_smoke_keeps_work_area_inside_supported_resolutions(
    qtbot: Any,
    size: tuple[int, int],
) -> None:
    window = build_window(qtbot, size=size)
    window._render_day(day_view())
    settle(qtbot, window)

    assert_inside_window(window, window.results)
    assert_inside_window(window, window.month_table)
    assert_inside_window(window, window.meals_scroll)
    assert_inside_window(window, window.diagnostic_group)

    # Celý měsíc bez vodorovného posuvu.
    assert not window.month_table.horizontalScrollBar().isVisible()
    assert (
        window.month_table.columnViewportPosition(29)
        + window.month_table.columnWidth(29)
        <= window.month_table.viewport().width()
    )

    # Akce jídelníčku musí zůstat ve viewportu scroll oblasti.
    viewport_width = window.meals_scroll.viewport().width()
    actions = [
        button
        for button in window.meals_scroll.widget().findChildren(QPushButton)
        if button.text() != ""
    ]
    assert actions
    for button in actions:
        position = button.mapTo(window.meals_scroll.widget(), button.rect().topLeft())
        assert position.x() + button.width() <= viewport_width

    # Žádný horizontální scroll celé aplikace.
    assert window.centralWidget().sizeHint().width() <= window.width()


def test_left_panel_stays_within_designed_width(qtbot: Any) -> None:
    window = build_window(qtbot, size=(1920, 1040))
    settle(qtbot, window)
    left = window.splitter.sizes()[0]
    assert MainWindow.LEFT_PANEL_MIN_WIDTH <= left <= MainWindow.LEFT_PANEL_MAX_WIDTH
    assert window.splitter.sizes()[1] > left


def test_manual_splitter_position_survives_resize(qtbot: Any) -> None:
    window = build_window(qtbot, size=(1920, 1040))
    settle(qtbot, window)
    window.splitter.setSizes([340, window.splitter.width() - 340])
    window._remember_panel_width(340, 1)

    window.resize(1366, 728)
    settle(qtbot, window)

    assert window.splitter.sizes()[0] == 340


@pytest.mark.parametrize(
    ("target", "days"),
    [
        (date(2026, 2, 1), 28),
        (date(2024, 2, 1), 29),
        (date(2026, 9, 1), 30),
        (date(2026, 12, 1), 31),
    ],
)
def test_month_grid_renders_every_day_without_horizontal_scroll(
    qtbot: Any,
    target: date,
    days: int,
) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(target))
    settle(qtbot, window)
    assert window.month_table.columnCount() == days
    assert window.month_table.horizontalHeaderItem(days - 1).text() == str(days)
    assert not window.month_table.horizontalScrollBar().isVisible()
    for column in range(days):
        assert (
            window.month_table.columnWidth(column)
            >= MainWindow.MIN_DAY_COLUMN_WIDTH
        )


def test_month_grid_shows_menu_number_and_business_tooltip(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view())
    ordered = window.month_table.item(0, 3)
    assert ordered.text() == "1"
    assert ordered.toolTip().splitlines() == [
        "Oběd-A",
        "04.09.2026",
        "Menu 1",
    ]
    empty = window.month_table.item(1, 3)
    assert empty.text() == ""
    assert empty.toolTip().splitlines()[-1] == "Bez objednávky"


def test_month_grid_and_daily_menu_do_not_overlap(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view())
    settle(qtbot, window)
    _, _, _, month_bottom = visible_rect(window.month_table)
    _, day_top, _, day_bottom = visible_rect(window.meals_scroll)
    _, diagnostics_top, _, _ = visible_rect(window.diagnostic_group)
    assert month_bottom <= day_top
    assert day_bottom <= diagnostics_top
    assert window.meals_scroll.height() > 0


def test_menu_numbers_come_from_service_capability_not_gui(qtbot: Any) -> None:
    read = FakeReadService(day_view(lunch_menus=(1, 2, 3)))
    window = build_window(qtbot, read=read)
    window._render_day(read.view)
    numbers = [
        label.text()
        for label in window.meals_scroll.widget().findChildren(QLabel)
        if label.objectName() == "menuNumber"
    ]
    assert numbers == ["1", "2", "3"] * 4
    assert sorted(window._menu_rows) == [
        (meal_type, menu)
        for meal_type in ("Oběd-A", "Oběd-B", "Oběd-C", "Oběd-D")
        for menu in (1, 2, 3)
    ]


def test_meal_type_is_not_menu_number(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(lunch_menus=(1, 2)))
    labels = {
        label.text()
        for label in window.meals_scroll.widget().findChildren(QLabel)
        if label.objectName() == "mealTypeTitle"
    }
    assert labels == {"Oběd-A", "Oběd-B", "Oběd-C", "Oběd-D"}
    assert ("Oběd-C", 2) in window._menu_rows
    assert window._menu_rows[("Oběd-C", 2)].toolTip().endswith("menu 2")


def test_menu_add_by_number_uses_order_service(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window._menu_rows[("Oběd-C", 2)].action_button.click()
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    command = write.commands[0]
    assert command.action is OrderAction.MENU_ADD
    assert command.typstravy == "Oběd-C"
    assert command.menu == 2


def test_menu_change_by_number_stays_single_intent(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window._menu_rows[("Oběd-A", 2)].action_button.click()
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    command = write.commands[0]
    assert command.action is OrderAction.MENU_CHANGE
    assert command.typstravy == "Oběd-A"
    assert command.menu == 2
    assert len(write.commands) == 1


def test_exclusive_group_change_is_delegated_as_single_target_intent(
    qtbot: Any,
) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view())
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    assert window._menu_rows[("Oběd-B", 1)].action_button.text() == "Změnit 1"
    window._menu_rows[("Oběd-B", 1)].action_button.click()
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    command = write.commands[0]
    assert command.action is OrderAction.MENU_ADD
    assert command.typstravy == "Oběd-B"
    assert command.menu == 1


def test_keyboard_digit_orders_active_meal_type(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window.month_table.setCurrentCell(2, 3)
    window._month_cell_clicked(2, 3)
    assert window._active_meal_type == "Oběd-C"

    window.results.setFocus()
    qtbot.keyClick(window, Qt.Key_2)
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    assert write.commands[0].typstravy == "Oběd-C"
    assert write.commands[0].menu == 2


def test_keyboard_digit_never_steals_text_input(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window._set_active_meal_type("Oběd-C")
    window.search_edit.setFocus()
    qtbot.keyClicks(window.search_edit, "12")
    assert window.search_edit.text() == "12"
    assert write.commands == []


def test_keyboard_digit_ignores_menu_outside_capability(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1,)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window._set_active_meal_type("Oběd-C")
    window.results.setFocus()
    qtbot.keyClick(window, Qt.Key_3)
    assert write.commands == []


def test_resize_preserves_diner_day_and_search(qtbot: Any) -> None:
    read = FakeReadService()
    window = build_window(qtbot, read=read)
    window._fill_results([DinerSummary(123, "První LAB", "KAT2", "1.A")])
    window.search_edit.setText("lab")
    window.results.selectRow(0)
    qtbot.waitUntil(lambda: window._current_diner is not None)
    window.date_edit.setDate(QDate(2026, 9, 4))
    window._render_day(day_view())
    window._set_active_meal_type("Oběd-C")

    window.resize(1024, 600)
    qtbot.waitUntil(lambda: window.width() == 1024)
    window.resize(1920, 1040)
    qtbot.waitUntil(lambda: window.width() == 1920)

    assert window.search_edit.text() == "lab"
    assert window._current_diner is not None
    assert window._current_diner.evidcislo == 123
    assert window.date_edit.date() == QDate(2026, 9, 4)
    assert window._active_meal_type == "Oběd-C"
    assert window.month_table.columnCount() == 30
    assert not window.month_table.horizontalScrollBar().isVisible()


@pytest.mark.parametrize("point_size", [10, 12, 15])
def test_layout_survives_windows_font_scaling(
    qtbot: Any,
    point_size: int,
) -> None:
    application = QApplication.instance()
    assert application is not None
    original = application.font()
    scaled = QFont(original)
    scaled.setPointSize(point_size)
    application.setFont(scaled)
    try:
        window = build_window(qtbot, size=(1366, 728))
        window._render_day(day_view())
        settle(qtbot, window)
        assert_inside_window(window, window.month_table)
        assert_inside_window(window, window.meals_scroll)
        assert window.meals_scroll.height() > 0
        row_height = window.month_table.verticalHeader().defaultSectionSize()
        assert row_height >= QFontMetrics(scaled).height()
    finally:
        application.setFont(original)


def test_unpublished_menu_is_reported_once_per_group(qtbot: Any) -> None:
    window = build_window(qtbot)
    empty = DinerDay(
        diner=DinerDetail(123, "LAB Test", "KAT2", "8.A", Decimal("100")),
        target_date=date(2026, 9, 4),
        server_now=datetime(2026, 9, 3, 8),
        meals=tuple(
            MealDay(
                code=code,
                meal_type=f"Oběd-{code}",
                display_order=1,
                current_state="N",
                options=(),
                availability=availability(),
                exclusive_codes=frozenset(),
                allowed_menus=(1,),
                month_states=tuple("N" for _ in range(30)),
                cooking_days=frozenset(range(1, 31)),
            )
            for code in ("A", "B", "C", "D")
        ),
    )
    window._render_day(empty)
    messages = [
        label.text()
        for label in window.meals_scroll.widget().findChildren(QLabel)
        if "není zveřejněn" in label.text()
    ]
    assert messages == ["Jídelníček pro tento den není zveřejněn."]


ALL_SEPTEMBER = frozenset(range(1, 31))


def month_cell(window: MainWindow, day_number: int, row: int = 0) -> Any:
    return window.month_table.item(row, day_number - 1)


def test_non_cooking_workday_renders_star(qtbot: Any) -> None:
    window = build_window(qtbot)
    # 10. 9. 2026 je čtvrtek, ve kterém se podle varnedny nevaří.
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER - {10}))
    cell = month_cell(window, 10)
    assert cell.text() == MainWindow.NON_COOKING_MARK
    assert cell.toolTip().splitlines()[-1] == "Nevaří se"


def test_non_cooking_weekend_renders_star(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER - {5, 6}))
    assert month_cell(window, 5).text() == MainWindow.NON_COOKING_MARK
    assert month_cell(window, 6).text() == MainWindow.NON_COOKING_MARK


def test_cooking_weekend_does_not_render_star(qtbot: Any) -> None:
    window = build_window(qtbot)
    # 5. 9. 2026 je sobota; víkend sám o sobě nesmí vyrobit `*`.
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER))
    cell = month_cell(window, 5)
    assert date(2026, 9, 5).weekday() == 5
    assert cell.text() == ""
    assert cell.toolTip().splitlines()[-1] == "Bez objednávky"


def test_cooking_workday_has_no_star(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER))
    assert month_cell(window, 10).text() == ""


def test_ordered_menu_number_wins_over_non_cooking_mark(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER - {4}))
    cell = month_cell(window, 4)
    assert cell.text() == "1"
    assert cell.toolTip().splitlines()[-1] == "Menu 1"


def test_month_markers_do_not_hide_menu_number_or_star(qtbot: Any) -> None:
    window = build_window(qtbot)
    # 3. 9. 2026 je "dnes" podle FakeReadService, 4. 9. je vybraný den.
    window._render_day(day_view(cooking_days=ALL_SEPTEMBER - {5}))
    selected = month_cell(window, 4)
    today = month_cell(window, 3)
    weekend = month_cell(window, 5)

    assert selected.text() == "1"
    assert weekend.text() == MainWindow.NON_COOKING_MARK
    plain_selected = month_cell(window, 4, row=1)
    assert plain_selected.text() == ""
    assert plain_selected.background().color() == QColor(
        theme.COLORS["selected"]
    )
    for cell in (selected, plain_selected):
        assert (
            cell.background().color().lightnessF()
            < today.background().color().lightnessF()
        )
    assert today.background().color() == QColor(theme.COLORS["today"])
    assert weekend.background().color() == QColor(theme.COLORS["non_cooking"])


def color_distance(first: QColor, second: QColor) -> int:
    return (
        abs(first.red() - second.red())
        + abs(first.green() - second.green())
        + abs(first.blue() - second.blue())
    )


def test_selected_day_is_more_prominent_than_today_marker(qtbot: Any) -> None:
    window = build_window(qtbot)
    # target_date je 4. 9. 2026, server_now 3. 9. 2026.
    window._render_day(day_view())
    selected = window.month_table.item(1, 3).background().color()
    today = window.month_table.item(1, 2).background().color()
    surface = QColor(theme.COLORS["surface"])

    assert selected.name() == theme.COLORS["selected"]
    assert today.name() == theme.COLORS["today"]
    assert color_distance(selected, surface) > color_distance(today, surface)
    # Marker nesmí přebít obsah buňky.
    assert window.month_table.item(0, 3).text() == "1"


def row_center_click(qtbot: Any, row: Any, target: QLabel) -> None:
    """Klik do textu řádku; popisky nesmí hit-area ukrojit."""

    assert target.testAttribute(Qt.WA_TransparentForMouseEvents)
    qtbot.mouseClick(row, Qt.LeftButton, pos=target.geometry().center())


def test_whole_row_click_on_dish_name_orders_menu_add(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    row = window._menu_rows[("Oběd-C", 2)]
    row_center_click(qtbot, row, row.dish_label)
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    assert write.commands[0].action is OrderAction.MENU_ADD
    assert write.commands[0].typstravy == "Oběd-C"
    assert write.commands[0].menu == 2


def test_whole_row_click_on_price_changes_ordered_menu(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    row = window._menu_rows[("Oběd-A", 2)]
    row_center_click(qtbot, row, row.price_label)
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    assert write.commands[0].action is OrderAction.MENU_CHANGE
    assert write.commands[0].menu == 2


def test_whole_row_click_on_empty_area_orders_menu_add(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    row = window._menu_rows[("Oběd-C", 1)]
    qtbot.mouseClick(row, Qt.LeftButton, pos=row.rect().center())
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    assert write.commands[0].action is OrderAction.MENU_ADD
    assert write.commands[0].menu == 1


def test_click_on_ordered_row_never_deletes_order(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    row = window._menu_rows[("Oběd-A", 1)]
    assert row.ordered
    assert not row.clickable
    row_center_click(qtbot, row, row.dish_label)
    qtbot.mouseClick(row, Qt.LeftButton, pos=row.rect().center())
    row_center_click(qtbot, row, row.number_label)
    qtbot.wait(50)
    assert write.commands == []
    assert row.action_button.text() == "Odhlásit 1"


def test_explicit_delete_button_still_removes_order(
    qtbot: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    asked: list[str] = []

    def confirm(*args: Any, **_kwargs: Any) -> Any:
        asked.append(str(args[2]))
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    window._menu_rows[("Oběd-A", 1)].action_button.click()
    qtbot.waitUntil(lambda: len(write.commands) == 1)
    assert write.commands[0].action is OrderAction.MENU_DELETE
    assert asked and "Oběd-A" in asked[0] and "menu 1" in asked[0]


def test_keyboard_digit_does_not_delete_ordered_menu(qtbot: Any) -> None:
    write = FakeOrderService()
    read = FakeReadService(day_view(lunch_menus=(1, 2)))
    window = build_window(qtbot, read=read, write=write)
    window._render_day(read.view)
    window._set_active_meal_type("Oběd-A")
    window.results.setFocus()
    qtbot.keyClick(window, Qt.Key_1)
    qtbot.wait(50)
    assert write.commands == []


def test_ordered_row_uses_full_row_ordered_state(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(lunch_menus=(1, 2)))
    ordered = window._menu_rows[("Oběd-A", 1)]
    plain = window._menu_rows[("Oběd-A", 2)]

    assert ordered.property("ordered") is True
    assert plain.property("ordered") is False
    assert "✓ OBJEDNÁNO" in ordered.dish_label.text()
    assert "OBJEDNÁNO" not in plain.dish_label.text()
    assert ordered.dish_label.property("tone") == "ordered"
    assert ordered.dish_label.font().bold()
    assert not plain.dish_label.font().bold()
    assert ordered.number_label.property("ordered") is True

    background = QColor(theme.COLORS["ordered_background"])
    text = QColor(theme.COLORS["ordered_text"])
    assert background.lightnessF() > 0.85
    assert text.lightnessF() < 0.2
    assert ordered.height() >= theme.ROW_HEIGHT


def test_typography_uses_only_four_central_roles(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(day_view(lunch_menus=(1, 2)))
    expected = {role.value for role in TextRole}
    assert len(theme.BASE_ROLES) == 4
    assert len(theme.role_point_sizes()) == 4

    seen: set[str] = set()
    styled = window.centralWidget().findChildren(
        QLabel
    ) + window.centralWidget().findChildren(QPushButton)
    for widget in styled:
        if widget.window() is not window:
            continue
        role = widget.property("textRole")
        assert role in expected, (type(widget).__name__, widget.text())
        seen.add(role)
        assert round(widget.font().pointSizeF(), 1) == theme.point_size(
            TextRole(role)
        )
    assert seen == expected


def test_gui_modules_have_no_local_font_or_color_styling() -> None:
    gui_directory = Path(main_window_module.__file__).parent
    offenders: list[str] = []
    for path in sorted(gui_directory.glob("*.py")):
        if path.name == "theme.py":
            continue
        source = path.read_text(encoding="utf-8")
        for needle in ("setStyleSheet", "font-size", "setPointSize", "QFont("):
            if needle in source:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == []


def snack_day(state: str = "N", menus: tuple[int, ...] = (1,)) -> DinerDay:
    return DinerDay(
        diner=DinerDetail(123, "LAB Test", "KAT2", "8.A", Decimal("100")),
        target_date=date(2026, 9, 4),
        server_now=datetime(2026, 9, 3, 8),
        meals=(
            MealDay(
                code="X",
                meal_type="Svačina",
                display_order=1,
                current_state=state,
                options=tuple(
                    MenuOption(menu, f"Svačina {menu}", Decimal("12"))
                    for menu in menus
                ),
                availability=availability(),
                exclusive_codes=frozenset(),
                allowed_menus=menus,
                month_states=tuple("N" for _ in range(30)),
                cooking_days=ALL_SEPTEMBER,
            ),
        ),
    )


def test_action_buttons_distinguish_primary_secondary_and_destructive(
    qtbot: Any,
) -> None:
    window = build_window(qtbot)
    window._render_day(snack_day("N", (1, 2)))
    assert (
        window._menu_rows[("Svačina", 1)].action_button.property("variant")
        == "primary"
    )

    window._render_day(snack_day("1", (1, 2)))
    assert (
        window._menu_rows[("Svačina", 1)].action_button.property("variant")
        == "destructive"
    )
    assert (
        window._menu_rows[("Svačina", 2)].action_button.property("variant")
        == "secondary"
    )


def test_single_type_group_does_not_repeat_its_name(qtbot: Any) -> None:
    window = build_window(qtbot)
    window._render_day(snack_day())
    titles = [
        label.text()
        for label in window.meals_scroll.widget().findChildren(QLabel)
        if label.objectName() == "mealTypeTitle"
    ]
    assert titles == []
    groups = [
        group.title()
        for group in window.meals_scroll.widget().findChildren(QGroupBox)
    ]
    assert groups == ["SVAČINA"]

    window._render_day(day_view())
    assert [
        group.title()
        for group in window.meals_scroll.widget().findChildren(QGroupBox)
    ] == ["OBĚD"]
