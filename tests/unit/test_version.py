from __future__ import annotations

import tomllib
from pathlib import Path

from jll import __version__
from jll.session import SessionManager
from jll.version import (
    AUDIT_VERSION_LIMIT,
    application_version,
    audit_client_version,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def canonical_version() -> str:
    data = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return str(data["project"]["version"])


def test_canonical_version_has_single_source_of_truth() -> None:
    assert application_version() == canonical_version()
    assert __version__ == canonical_version()


def test_audit_client_version_fits_documented_column_limit() -> None:
    value = audit_client_version()
    assert value == application_version()[:AUDIT_VERSION_LIMIT]
    assert 1 <= len(value) <= AUDIT_VERSION_LIMIT


def test_session_manager_defaults_to_canonical_client_version() -> None:
    manager = SessionManager.__new__(SessionManager)
    SessionManager.__init__(
        manager,
        config=None,  # type: ignore[arg-type]
        identity_store=None,  # type: ignore[arg-type]
    )
    assert manager.client_version == audit_client_version()


def test_sources_do_not_duplicate_the_version_literal() -> None:
    literal = canonical_version()
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        if literal in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
