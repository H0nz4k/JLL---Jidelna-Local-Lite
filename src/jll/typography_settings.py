"""Editable four-role typography settings (Flet appearance)."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROLE_KEYS = ("primary", "body", "action", "meta")

ROLE_LABELS_CS: dict[str, str] = {
    "primary": "Hlavní nadpis",
    "body": "Běžný text",
    "action": "Akce a sekce",
    "meta": "Doplňkový text",
}

SIZE_MIN = 10.0
SIZE_MAX = 40.0
SIZE_STEP = 0.5

# Historical BASE_ROLES × EXTRA_LARGE (1.3) from JLL 0.5.1 defaults.
_DEFAULT_PRIMARY_SIZE = 28.6
_DEFAULT_BODY_SIZE = 19.5
_DEFAULT_ACTION_SIZE = 18.2
_DEFAULT_META_SIZE = 16.25


def validate_role_size(size: Any) -> float:
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        raise ValueError("size musí být číslo.")
    value = float(size)
    if not math.isfinite(value):
        raise ValueError("size musí být konečné číslo.")
    if value < SIZE_MIN or value > SIZE_MAX:
        raise ValueError(f"size musí být v rozsahu {SIZE_MIN}..{SIZE_MAX}.")
    return value


@dataclass(frozen=True, slots=True)
class TypographyRoleSettings:
    size: float
    bold: bool

    def __post_init__(self) -> None:
        validate_role_size(self.size)
        if not isinstance(self.bold, bool):
            raise ValueError("bold musí být boolean.")


@dataclass(frozen=True, slots=True)
class TypographySettings:
    primary: TypographyRoleSettings
    body: TypographyRoleSettings
    action: TypographyRoleSettings
    meta: TypographyRoleSettings

    def for_key(self, key: str) -> TypographyRoleSettings:
        if key not in ROLE_KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def replace_role(self, key: str, role: TypographyRoleSettings) -> TypographySettings:
        data = {item: self.for_key(item) for item in ROLE_KEYS}
        data[key] = role
        return TypographySettings(**data)


DEFAULT_TYPOGRAPHY = TypographySettings(
    primary=TypographyRoleSettings(_DEFAULT_PRIMARY_SIZE, True),
    body=TypographyRoleSettings(_DEFAULT_BODY_SIZE, False),
    action=TypographyRoleSettings(_DEFAULT_ACTION_SIZE, True),
    meta=TypographyRoleSettings(_DEFAULT_META_SIZE, False),
)


def parse_typography(raw: Any | None) -> TypographySettings:
    if raw is None:
        return DEFAULT_TYPOGRAPHY
    if not isinstance(raw, Mapping):
        raise ValueError("typography musí být objekt.")
    roles: dict[str, TypographyRoleSettings] = {}
    for key in ROLE_KEYS:
        if key not in raw:
            raise ValueError(f"typography chybí role '{key}'.")
        item = raw[key]
        if not isinstance(item, Mapping):
            raise ValueError(f"typography.{key} musí být objekt.")
        if "size" not in item or "bold" not in item:
            raise ValueError(f"typography.{key} musí obsahovat size a bold.")
        bold = item["bold"]
        if not isinstance(bold, bool):
            raise ValueError(f"typography.{key}.bold musí být boolean.")
        roles[key] = TypographyRoleSettings(validate_role_size(item["size"]), bold)
    unknown = sorted(set(raw.keys()) - set(ROLE_KEYS))
    if unknown:
        raise ValueError(f"typography obsahuje neznámé klíče: {', '.join(unknown)}")
    return TypographySettings(**roles)


def typography_to_dict(settings: TypographySettings) -> dict[str, Any]:
    return {
        key: {"size": settings.for_key(key).size, "bold": settings.for_key(key).bold}
        for key in ROLE_KEYS
    }


def load_typography(path: str | Path) -> TypographySettings:
    config_path = Path(path)
    if not config_path.is_file():
        return DEFAULT_TYPOGRAPHY
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Config nelze načíst pro typography: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Kořen configu musí být objekt.")
    return parse_typography(raw.get("typography"))


def save_typography(settings: TypographySettings, path: str | Path) -> None:
    """Atomic merge of `typography` into existing lab.json (or create minimal object)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Config nelze načíst pro typography save: {target}") from exc
        if not isinstance(raw, dict):
            raise ValueError("Kořen configu musí být objekt.")
    else:
        raw = {}
    raw["typography"] = typography_to_dict(settings)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(raw, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def typography_from_legacy_scale(multiplier: float) -> TypographySettings:
    """Convert historical TextScale multiplier to absolute role sizes (no double apply)."""

    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("legacy scale multiplier musí být kladné konečné číslo.")
    return TypographySettings(
        primary=TypographyRoleSettings(round(22.0 * multiplier, 2), True),
        body=TypographyRoleSettings(round(15.0 * multiplier, 2), False),
        action=TypographyRoleSettings(round(14.0 * multiplier, 2), True),
        meta=TypographyRoleSettings(round(12.5 * multiplier, 2), False),
    )
