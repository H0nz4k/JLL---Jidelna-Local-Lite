"""Tests for editable typography settings persistence and validation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from jll.typography_settings import (
    DEFAULT_TYPOGRAPHY,
    TypographyRoleSettings,
    TypographySettings,
    load_typography,
    parse_typography,
    save_typography,
    typography_from_legacy_scale,
    typography_to_dict,
    validate_role_size,
)


def test_defaults_match_0_5_1_effective_extra_large() -> None:
    expected = typography_from_legacy_scale(1.3)
    assert DEFAULT_TYPOGRAPHY == expected
    assert DEFAULT_TYPOGRAPHY.primary.bold is True
    assert DEFAULT_TYPOGRAPHY.body.bold is False
    assert DEFAULT_TYPOGRAPHY.action.bold is True
    assert DEFAULT_TYPOGRAPHY.meta.bold is False


def test_old_config_without_typography_loads_defaults(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    path.write_text('{"site_name": "x"}\n', encoding="utf-8")
    assert load_typography(path) == DEFAULT_TYPOGRAPHY


def test_missing_config_file_uses_defaults(tmp_path: Path) -> None:
    assert load_typography(tmp_path / "missing.json") == DEFAULT_TYPOGRAPHY


def test_save_reload_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    path.write_text(
        json.dumps({"site_name": "Lab", "host": "127.0.0.1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    settings = TypographySettings(
        primary=TypographyRoleSettings(30.0, True),
        body=TypographyRoleSettings(18.0, False),
        action=TypographyRoleSettings(17.0, False),
        meta=TypographyRoleSettings(14.0, True),
    )
    save_typography(settings, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["site_name"] == "Lab"
    assert raw["typography"] == typography_to_dict(settings)
    assert load_typography(path) == settings


def test_size_bounds() -> None:
    assert validate_role_size(10.0) == 10.0
    assert validate_role_size(40.0) == 40.0
    with pytest.raises(ValueError):
        validate_role_size(9.9)
    with pytest.raises(ValueError):
        validate_role_size(40.1)
    with pytest.raises(ValueError):
        validate_role_size(float("nan"))
    with pytest.raises(ValueError):
        validate_role_size(float("inf"))
    with pytest.raises(ValueError):
        validate_role_size("19")


def test_non_bool_bold_invalid() -> None:
    with pytest.raises(ValueError):
        TypographyRoleSettings(19.5, "yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        parse_typography(
            {
                "primary": {"size": 28.6, "bold": 1},
                "body": {"size": 19.5, "bold": False},
                "action": {"size": 18.2, "bold": True},
                "meta": {"size": 16.25, "bold": False},
            }
        )


def test_parse_rejects_partial_typography() -> None:
    with pytest.raises(ValueError, match="primary"):
        parse_typography({"body": {"size": 19.5, "bold": False}})


def test_atomic_save_preserves_other_keys(tmp_path: Path) -> None:
    path = tmp_path / "lab.json"
    path.write_text('{"a": 1, "b": [2]}\n', encoding="utf-8")
    save_typography(DEFAULT_TYPOGRAPHY, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["a"] == 1
    assert raw["b"] == [2]
    assert "typography" in raw


def test_legacy_scale_conversion_no_double_multiply() -> None:
    converted = typography_from_legacy_scale(1.3)
    assert converted.body.size == pytest.approx(19.5)
    # Applying conversion again with absolute sizes must not multiply by 1.3.
    assert converted.body.size == DEFAULT_TYPOGRAPHY.body.size
    assert not math.isclose(converted.body.size * 1.3, converted.body.size)
