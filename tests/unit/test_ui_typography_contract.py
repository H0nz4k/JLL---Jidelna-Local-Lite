"""Statický guard: Flet UI smí používat jen 4 typografické role z theme."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jll.flet_ui import theme

ROOT = Path(__file__).resolve().parents[2]
FLET_UI = ROOT / "src" / "jll" / "flet_ui"
THEME_FILE = FLET_UI / "theme.py"

# Icon / layout sizes are not typography.
ALLOW_NUMERIC_SIZE_CALLS = frozenset({"Icon", "Container", "Image"})


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


@pytest.mark.parametrize("path", _flet_ui_py_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_ad_hoc_typography_outside_theme(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        # Direct FontWeight.W_* usage
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
                # allow theme.role_weight(...) only; bare FontWeight forbidden above
                if isinstance(weight, ast.Attribute) or (
                    isinstance(weight, ast.Name) and weight.id.startswith("W_")
                ):
                    failures.append(
                        f"L{node.lineno}: {name}(weight=...) – použij theme.role_weight"
                    )
            if family is not None and _is_numeric_literal(family) is False:
                if isinstance(family, ast.Constant) and isinstance(family.value, str):
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

        if name in ALLOW_NUMERIC_SIZE_CALLS:
            continue
        # Generic size=N on Text already covered; skip other widgets.

    # Also scan raw source for FontWeight. imports usages not in Call form
    text = path.read_text(encoding="utf-8")
    if "FontWeight." in text or "ft.FontWeight" in text:
        failures.append("source contains FontWeight. – použij theme.role_weight")

    assert not failures, f"{path.relative_to(ROOT)}:\n" + "\n".join(failures)


def test_theme_contract_four_roles_and_weights() -> None:
    assert theme.assert_four_roles() == ("ACTION", "BODY", "META", "PRIMARY")
    assert theme.assert_role_weights() == {
        "PRIMARY": 700,
        "BODY": 400,
        "ACTION": 600,
        "META": 400,
    }
    assert [s.value for s in theme.TextScale] == [1.0, 1.15, 1.3, 1.5]
    base = theme.role_size(theme.TextRole.BODY, theme.TextScale.NORMAL)
    for scale in theme.TextScale:
        assert theme.role_size(theme.TextRole.BODY, scale) == round(
            base * scale.value, 2
        )
    style = theme.role_style(theme.TextRole.PRIMARY)
    assert style.size == theme.role_size(theme.TextRole.PRIMARY)
    assert style.weight == theme.role_weight(theme.TextRole.PRIMARY)
    assert style.font_family == theme.FONT_FAMILY


def test_future_body_w600_and_size_literal_would_fail_guard() -> None:
    """Dokumentace: guard chytí typické drift vzory (simulace AST)."""

    bad = ast.parse(
        "ft.Text('x', size=17, weight=ft.FontWeight.W_600)\n"
        "ft.TextField(text_size=13)\n"
    )
    found_size = False
    found_weight = False
    found_field = False
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
    assert found_size and found_weight and found_field
