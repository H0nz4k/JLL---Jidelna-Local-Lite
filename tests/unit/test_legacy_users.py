"""Unit testy LegacyUserRepository: šablona a alokace id."""

from __future__ import annotations

from typing import Any

import pytest

from jll.legacy_users import LegacyUserRepository, LegacyUserRow


def test_create_user_from_template_rejects_admin_template() -> None:
    admin_template = LegacyUserRow(
        code="SUP",
        display_name="Admin",
        is_admin=True,
        typ="INTERNI",
        disabled=False,
        prava="",
        prava1="",
        has_password=False,
        legacy_id=1,
    )
    with pytest.raises(ValueError, match="admin"):
        LegacyUserRepository(None).create_user_from_template(  # type: ignore[arg-type]
            code="NOVY",
            display_name="Nový uživatel",
            template=admin_template,
        )


class _CaptureCursor:
    def __init__(self, conn: "_CaptureConnection") -> None:
        self._conn = conn
        self._row: Any = None

    def __enter__(self) -> _CaptureCursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, sql: str, params: object | None = None) -> None:
        text = " ".join(str(sql).split())
        self._conn.statements.append((text, params))
        if "test_new_user_id" in text:
            self._row = (77,)
            return
        if "WHERE btrim(uzivatel)" in text:
            self._row = None
            return
        if "INSERT INTO public.uzivatel" in text:
            assert params is not None
            values = tuple(params)  # type: ignore[arg-type]
            self._conn.insert_sql = text
            self._conn.insert_params = values
            self._row = {
                "uzivatel": values[0],
                "jmeno": values[1],
                "is_admin": False,
                "typ": values[4],
                "disabled": False,
                "prava": values[2],
                "prava1": values[3],
                "heslo": "",
                "id": values[5],
            }
            return
        if "INSERT INTO public.user_role" in text:
            self._row = None
            return
        self._row = None

    def fetchone(self) -> Any:
        return self._row


class _CaptureConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object | None]] = []
        self.insert_sql: str | None = None
        self.insert_params: tuple[object, ...] | None = None

    def cursor(self, row_factory: object | None = None) -> _CaptureCursor:
        return _CaptureCursor(self)


def test_create_user_allocates_id_and_inserts_empty_heslo() -> None:
    conn = _CaptureConnection()
    template = LegacyUserRow(
        code="VED",
        display_name="Vedoucí",
        is_admin=False,
        typ="INTERNI",
        disabled=False,
        prava="ABC",
        prava1="XYZ",
        has_password=True,
        legacy_id=5,
    )
    created = LegacyUserRepository(conn).create_user_from_template(
        code="novy",
        display_name="Nový",
        template=template,
    )
    assert created.code == "NOVY"
    assert created.legacy_id == 77
    assert created.has_password is False
    assert conn.insert_sql is not None
    assert " id" in conn.insert_sql or ", id" in conn.insert_sql
    assert "''" in conn.insert_sql
    assert "heslo" in conn.insert_sql.casefold()
    assert conn.insert_params is not None
    assert conn.insert_params[5] == 77
    assert any("test_new_user_id" in sql for sql, _ in conn.statements)
