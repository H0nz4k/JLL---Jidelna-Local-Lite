"""Canonical verze JLL.

Jediným zdrojem pravdy je `[project].version` v `pyproject.toml`; runtime ji
čte z metadat nainstalovaného balíčku. Ruční kopie verze v kódu neexistuje.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "jidelna-local-lite"
UNKNOWN_VERSION = "0+unknown"

#: `prihlasky_audit.client_version` má doložený limit 10 znaků.
AUDIT_VERSION_LIMIT = 10


def application_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def audit_client_version() -> str:
    return application_version()[:AUDIT_VERSION_LIMIT]
