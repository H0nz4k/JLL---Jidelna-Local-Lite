"""Runtime cesty pro LAB vs production (ProgramData)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "JidelnaLocalLite"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    config_path: Path
    identity_path: Path
    log_path: Path
    reset_backup_root: Path
    environment_hint: str  # "lab" | "production"


def program_data_root() -> Path:
    base = os.environ.get("PROGRAMDATA") or os.environ.get("ProgramData")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def resolve_runtime_paths(
    *,
    config: Path | None = None,
    identity: Path | None = None,
    log: Path | None = None,
    force_lab: bool = False,
) -> RuntimePaths:
    """Vybere LAB (repo) nebo production (ProgramData) layout."""

    if force_lab or (not is_frozen() and config is None and identity is None):
        root = PROJECT_ROOT
        cfg = config or (root / "config" / "lab.json")
        return RuntimePaths(
            config_path=cfg,
            identity_path=identity or (root / "config" / "users.lab.json"),
            log_path=log or (root / "logs" / "jll-lab.log"),
            reset_backup_root=cfg.parent / "reset-backups",
            environment_hint="lab",
        )

    data = program_data_root()
    cfg = config or (data / "config" / "jll.json")
    return RuntimePaths(
        config_path=cfg,
        identity_path=identity or (data / "config" / "users.json"),
        log_path=log or (data / "logs" / "jll.log"),
        reset_backup_root=data / "reset-backups",
        environment_hint="production",
    )
