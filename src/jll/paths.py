"""Compatibility shim — prefer ``jll.runtime_paths``."""

from __future__ import annotations

from .runtime_paths import (  # noqa: F401
    APP_DIR_NAME,
    RuntimePaths,
    is_frozen,
    program_data_root,
    resolve_runtime_paths,
)

__all__ = [
    "APP_DIR_NAME",
    "RuntimePaths",
    "is_frozen",
    "program_data_root",
    "resolve_runtime_paths",
]
