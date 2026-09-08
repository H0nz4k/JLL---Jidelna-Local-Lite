"""Unit tests: IdleHomeController."""

from __future__ import annotations

from jll.flet_ui.idle_home import DINER_IDLE_HOME_SECONDS, IdleHomeController


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_idle_returns_home_at_timeout() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.set_diner_open(True)
    clock.advance(DINER_IDLE_HOME_SECONDS - 1)
    assert ctrl.should_return_home() is False
    clock.advance(1)
    assert ctrl.should_return_home() is True


def test_activity_resets_timer() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.set_diner_open(True)
    clock.advance(50)
    ctrl.note_activity()
    clock.advance(50)
    assert ctrl.should_return_home() is False
    clock.advance(10)
    assert ctrl.should_return_home() is True


def test_modal_suppresses_idle() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.set_diner_open(True)
    ctrl.modal_open = True
    clock.advance(120)
    assert ctrl.should_return_home() is False


def test_dirty_and_write_suppress() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.set_diner_open(True)
    ctrl.dirty_form = True
    clock.advance(120)
    assert ctrl.should_return_home() is False
    ctrl.dirty_form = False
    ctrl.write_in_flight = True
    assert ctrl.should_return_home() is False


def test_non_diners_route_suppresses() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.set_diner_open(True)
    ctrl.route_is_diners = False
    clock.advance(120)
    assert ctrl.should_return_home() is False


def test_home_without_diner_never_fires() -> None:
    clock = FakeClock()
    ctrl = IdleHomeController(clock=clock)
    ctrl.diner_open = False
    clock.advance(120)
    assert ctrl.should_return_home() is False
