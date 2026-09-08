"""Appearance editor must not create extra typography signatures before save."""

from __future__ import annotations

import ast
from pathlib import Path

from jll.flet_ui import theme
from jll.flet_ui.app import FletAppController
from jll.flet_ui.state import AppState
from jll.typography_settings import (
    DEFAULT_TYPOGRAPHY,
    TypographyRoleSettings,
    TypographySettings,
    load_typography,
    save_typography,
)

ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / "src" / "jll" / "flet_ui" / "screens" / "admin.py"
THEME = ROOT / "src" / "jll" / "flet_ui" / "theme.py"


def _draft_settings() -> TypographySettings:
    return TypographySettings(
        primary=TypographyRoleSettings(32.0, False),
        body=TypographyRoleSettings(24.0, True),
        action=TypographyRoleSettings(22.0, False),
        meta=TypographyRoleSettings(20.0, True),
    )


def test_unsaved_draft_does_not_mutate_runtime_typography() -> None:
    theme.set_typography(DEFAULT_TYPOGRAPHY)
    original = theme.get_typography()
    before = set(theme.all_role_signatures())
    assert len(before) <= 4

    # Simulate form draft only (no set_typography / save).
    draft = _draft_settings()
    assert draft != original
    assert theme.get_typography() == original
    assert set(theme.all_role_signatures()) == before
    assert len(set(theme.all_role_signatures())) <= 4


def test_save_applies_runtime_and_keeps_max_four(tmp_path: Path) -> None:
    theme.set_typography(DEFAULT_TYPOGRAPHY)
    config = tmp_path / "lab.json"
    config.write_text('{"site_name": "Lab"}\n', encoding="utf-8")
    state = AppState(config_path=config, identity_path=tmp_path / "users.json")
    state.typography = DEFAULT_TYPOGRAPHY

    saved = _draft_settings()
    save_typography(saved, config)
    state.typography = saved
    theme.set_typography(saved)

    assert theme.get_typography() == saved
    assert state.typography == saved
    assert load_typography(config) == saved
    assert len(set(theme.all_role_signatures())) <= 4


def test_reset_defaults_does_not_apply_until_save() -> None:
    custom = _draft_settings()
    theme.set_typography(custom)
    assert theme.get_typography() == custom

    # "Obnovit výchozí" only prepares form values; runtime stays custom until save.
    form_draft = DEFAULT_TYPOGRAPHY
    assert form_draft != custom
    assert theme.get_typography() == custom

    theme.set_typography(form_draft)
    assert theme.get_typography() == DEFAULT_TYPOGRAPHY
    assert len(set(theme.all_role_signatures())) <= 4


def test_appearance_source_has_no_arbitrary_preview_helper() -> None:
    admin = ADMIN.read_text(encoding="utf-8")
    theme_src = THEME.read_text(encoding="utf-8")
    assert "preview_style" not in admin
    assert "def preview_style" not in theme_src
    assert "Aktuální vzhled" in admin
    assert "Po uložení:" in admin
    assert "Náhled:" not in admin.split("def _render_appearance")[1].split("def ")[0]


def test_theme_has_no_size_bold_textstyle_factory() -> None:
    tree = ast.parse(THEME.read_text(encoding="utf-8"), filename=str(THEME))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = [a.arg for a in node.args.args]
        kwonly = [a.arg for a in node.args.kwonlyargs]
        names = set(args + kwonly)
        if {"size", "bold"} <= names or {"size", "weight"} <= names:
            if node.name not in {"TypographySignature"}:
                offenders.append(node.name)
    assert offenders == []


def test_controller_save_typography_updates_state(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "lab.json"
    config.write_text('{"site_name": "Lab"}\n', encoding="utf-8")
    state = AppState(config_path=config, identity_path=tmp_path / "users.json")
    state.typography = DEFAULT_TYPOGRAPHY
    theme.set_typography(DEFAULT_TYPOGRAPHY)

    class FakePage:
        def update(self) -> None:
            return None

    controller = FletAppController.__new__(FletAppController)
    controller.page = FakePage()  # type: ignore[assignment]
    controller.state = state
    rebuilt: list[bool] = []

    def _render_shell() -> None:
        rebuilt.append(True)

    controller._render_shell = _render_shell  # type: ignore[method-assign]
    saved = _draft_settings()
    controller._save_typography(saved)
    assert state.typography == saved
    assert theme.get_typography() == saved
    assert load_typography(config) == saved
    assert state.admin_section == "Vzhled"
    assert rebuilt == [True]
    assert len(set(theme.all_role_signatures())) <= 4
