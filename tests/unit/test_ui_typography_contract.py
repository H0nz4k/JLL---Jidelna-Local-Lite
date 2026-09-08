"""Statický + runtime guard: Flet UI smí používat jen 4 typografické role z theme."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jll.flet_ui import theme
from jll.typography_settings import DEFAULT_TYPOGRAPHY

ROOT = Path(__file__).resolve().parents[2]
FLET_UI = ROOT / "src" / "jll" / "flet_ui"
THEME_FILE = FLET_UI / "theme.py"

# Icon / layout sizes are not typography.
ALLOW_NUMERIC_SIZE_CALLS = frozenset({"Icon", "Container", "Image"})
BUTTON_TYPES = frozenset({"FilledButton", "OutlinedButton", "TextButton", "ElevatedButton"})


def _flet_ui_py_files() -> list[Path]:
    return sorted(p for p in FLET_UI.rglob("*.py") if p.name != "theme.py")


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_numeric_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))


def _kw(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _uses_button_style(style_node: ast.AST | None) -> bool:
    if style_node is None:
        return False
    if isinstance(style_node, ast.Call) and _call_name(style_node.func) == "button_style":
        return True
    if isinstance(style_node, ast.Name):
        return True  # e.g. _btn_pad = theme.button_style(...)
    if isinstance(style_node, ast.Attribute):
        return style_node.attr == "button_style"
    return False


@pytest.fixture(autouse=True)
def _reset_default_typography() -> None:
    theme.set_typography(DEFAULT_TYPOGRAPHY)
    yield
    theme.set_typography(DEFAULT_TYPOGRAPHY)


@pytest.mark.parametrize("path", _flet_ui_py_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_ad_hoc_typography_outside_theme(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Attribute)
                and child.value.attr == "FontWeight"
            ):
                failures.append(
                    f"L{getattr(node, 'lineno', '?')}: direct FontWeight in Call"
                )
            if (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id == "FontWeight"
            ):
                failures.append(
                    f"L{getattr(node, 'lineno', '?')}: direct FontWeight in Call"
                )

        if name in {"Text", "TextStyle", "TextSpan"}:
            size = _kw(node, "size")
            weight = _kw(node, "weight")
            family = _kw(node, "font_family")
            if size is not None and _is_numeric_literal(size):
                failures.append(
                    f"L{node.lineno}: {name}(size=<literal>) – použij theme.role_size/role_style"
                )
            if weight is not None and not (
                isinstance(weight, ast.Call)
                and _call_name(weight.func) == "role_weight"
            ):
                if isinstance(weight, ast.Attribute) or (
                    isinstance(weight, ast.Name) and weight.id.startswith("W_")
                ):
                    failures.append(
                        f"L{node.lineno}: {name}(weight=...) – použij theme.role_weight"
                    )
            if family is not None and isinstance(family, ast.Constant) and isinstance(
                family.value, str
            ):
                if family.value != theme.FONT_FAMILY:
                    failures.append(
                        f"L{node.lineno}: {name}(font_family=...) mimo theme.FONT_FAMILY"
                    )

        if name == "TextField":
            text_size = _kw(node, "text_size")
            if text_size is not None and _is_numeric_literal(text_size):
                failures.append(
                    f"L{node.lineno}: TextField(text_size=<literal>) – použij theme.field_text_size()"
                )

        if name in BUTTON_TYPES:
            style = _kw(node, "style")
            if style is None or not _uses_button_style(style):
                failures.append(
                    f"L{node.lineno}: {name} bez theme.button_style() / odvozeného style"
                )

        if name in ALLOW_NUMERIC_SIZE_CALLS:
            continue

    text = path.read_text(encoding="utf-8")
    if "FontWeight." in text or "ft.FontWeight" in text:
        failures.append("source contains FontWeight. – použij theme.role_weight")
    for banned in ("W_500", "W_600", "FontWeight.BOLD", "FontWeight.NORMAL"):
        if banned in text:
            failures.append(f"source contains banned {banned}")

    assert not failures, f"{path.relative_to(ROOT)}:\n" + "\n".join(failures)


def test_theme_contract_four_roles_and_weights() -> None:
    assert theme.assert_four_roles() == ("ACTION", "BODY", "META", "PRIMARY")
    assert theme.assert_role_weights() == {
        "PRIMARY": 700,
        "BODY": 400,
        "ACTION": 700,
        "META": 400,
    }
    assert theme.assert_max_four_signatures() <= 4
    assert len(set(theme.all_role_signatures())) == 4
    assert [s.value for s in theme.TextScale] == [1.0, 1.15, 1.3, 1.5]
    # Legacy scale helper still converts, but is not an active multiplier on defaults.
    assert theme.role_size(theme.TextRole.BODY) == DEFAULT_TYPOGRAPHY.body.size
    assert theme.role_size(theme.TextRole.BODY, theme.TextScale.NORMAL) == 15.0
    style = theme.role_style(theme.TextRole.PRIMARY)
    assert style.size == theme.role_size(theme.TextRole.PRIMARY)
    assert style.weight == theme.role_weight(theme.TextRole.PRIMARY)
    assert style.font_family == theme.FONT_FAMILY


def test_runtime_signatures_never_exceed_four() -> None:
    from jll.typography_settings import TypographyRoleSettings, TypographySettings

    theme.set_typography(
        TypographySettings(
            primary=TypographyRoleSettings(30.0, True),
            body=TypographyRoleSettings(30.0, True),
            action=TypographyRoleSettings(30.0, True),
            meta=TypographyRoleSettings(30.0, True),
        )
    )
    assert len(set(theme.all_role_signatures())) == 1
    theme.set_typography(DEFAULT_TYPOGRAPHY)
    assert len(set(theme.all_role_signatures())) == 4


def test_theme_has_no_w500_w600() -> None:
    text = THEME_FILE.read_text(encoding="utf-8")
    assert "W_500" not in text
    assert "W_600" not in text
    assert "w600" not in text
    assert "w500" not in text


def test_home_has_no_all_caps_section_heading() -> None:
    home = (FLET_UI / "components" / "home_overview.py").read_text(encoding="utf-8")
    assert "DNEŠNÍ OBJEDNÁVKY" not in home
    assert "Dnešní objednávky" in home


def test_future_body_w600_and_size_literal_would_fail_guard() -> None:
    """Dokumentace: guard chytí typické drift vzory (simulace AST)."""

    bad = ast.parse(
        "ft.Text('x', size=17, weight=ft.FontWeight.W_600)\n"
        "ft.TextField(text_size=13)\n"
        "ft.FilledButton('x')\n"
    )
    found_size = False
    found_weight = False
    found_field = False
    found_button = False
    for node in ast.walk(bad):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            size = _kw(node, "size")
            weight = _kw(node, "weight")
            text_size = _kw(node, "text_size")
            if name == "Text" and size is not None and _is_numeric_literal(size):
                found_size = True
            if name == "Text" and weight is not None:
                found_weight = True
            if name == "TextField" and text_size is not None and _is_numeric_literal(text_size):
                found_field = True
            if name == "FilledButton" and _kw(node, "style") is None:
                found_button = True
    assert found_size and found_weight and found_field and found_button
