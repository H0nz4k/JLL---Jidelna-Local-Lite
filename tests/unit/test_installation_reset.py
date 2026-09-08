"""Unit tests: InstallationResetService (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jll.installation_reset import (
    InstallationResetError,
    InstallationResetService,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_happy_path_moves_active_files_and_keeps_backup(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "lab.json"
    identity = tmp_path / "users.lab.json"
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    fallback = secrets / "sup.DEMO.hash"
    fallback.write_text("hash\n", encoding="utf-8")
    _write_json(
        config,
        {
            "site_name": "Demo",
            "instance_id": "DEMO",
            "database": "jll_scio_lab",
            "user": "postgres",
            "reader_mode": "auto_elatec",
            "host": "127.0.0.1",
            "port": 5433,
            "site_id": "X",
            "allowed_categories": ["1JARO"],
            "environment": "lab",
            "expected_system_identifier": "1",
            "business_timezone": "Europe/Prague",
            "strict_config_lock": True,
        },
    )
    _write_json(identity, {"schema_version": 1, "users": [], "audit_events": []})

    store = {"DEMO:postgres": "db", "jll-sup:DEMO": "sup"}
    deleted: list[str] = []

    class _KR:
        @staticmethod
        def get_password(service, username):
            return store.get(username)

        @staticmethod
        def delete_password(service, username):
            deleted.append(username)
            store.pop(username, None)

    monkeypatch.setattr("jll.installation_reset.keyring", _KR)
    monkeypatch.setattr("jll.sup_secret.keyring", _KR)

    service = InstallationResetService()
    plan = service.build_plan(config_path=config, identity_path=identity)
    result = service.execute(plan)

    assert result.moved_config is True
    assert result.moved_identity is True
    assert not config.exists()
    assert not identity.exists()
    assert not fallback.exists()
    assert (result.backup_dir / "lab.json").is_file()
    assert (result.backup_dir / "users.lab.json").is_file()
    manifest = json.loads((result.backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "password" not in json.dumps(manifest).casefold()
    assert manifest["instance_id"] == "DEMO"
    assert "DEMO:postgres" in deleted
    assert "jll-sup:DEMO" in deleted


def test_backup_failure_keeps_active_files(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "lab.json"
    identity = tmp_path / "users.lab.json"
    _write_json(config, {"instance_id": "DEMO", "user": "postgres", "site_name": "X", "database": "db", "reader_mode": "manual"})
    _write_json(identity, {"schema_version": 1})

    service = InstallationResetService()
    plan = service.build_plan(config_path=config, identity_path=identity)

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("jll.installation_reset.shutil.copy2", _boom)
    with pytest.raises(InstallationResetError) as exc:
        service.execute(plan)
    assert "zálohu" in str(exc.value).casefold() or "zaloh" in str(exc.value).casefold()
    assert config.is_file()
    assert identity.is_file()


def test_already_clean_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "missing-lab.json"
    identity = tmp_path / "missing-users.json"
    service = InstallationResetService()
    plan = service.build_plan(config_path=config, identity_path=identity)
    result = service.execute(plan)
    assert result.already_clean is True
    assert result.moved_config is False


def test_custom_paths_are_used(tmp_path: Path, monkeypatch) -> None:
    custom = tmp_path / "custom"
    config = custom / "my-lab.json"
    identity = custom / "my-users.json"
    _write_json(
        config,
        {
            "instance_id": "CUST",
            "user": "postgres",
            "site_name": "C",
            "database": "db",
            "reader_mode": "manual",
        },
    )
    _write_json(identity, {"schema_version": 1})

    class _KR:
        @staticmethod
        def get_password(service, username):
            return None

        @staticmethod
        def delete_password(service, username):
            return None

    monkeypatch.setattr("jll.installation_reset.keyring", _KR)
    monkeypatch.setattr("jll.sup_secret.keyring", _KR)

    plan = InstallationResetService().build_plan(
        config_path=config, identity_path=identity
    )
    assert plan.config_path == config
    assert "lab.json" not in str(plan.config_path.name) or plan.config_path.name == "my-lab.json"
    result = InstallationResetService().execute(plan)
    assert (result.backup_dir / "my-lab.json").is_file()
    assert not config.exists()


def test_module_has_no_db_imports() -> None:
    source = Path("src/jll/installation_reset.py").read_text(encoding="utf-8")
    assert "psycopg" not in source
    assert "OrderRepository" not in source
    assert "PaymentService" not in source
    assert "DinerService" not in source
