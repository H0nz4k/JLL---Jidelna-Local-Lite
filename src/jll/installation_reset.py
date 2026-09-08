"""Bezpečný reset lokální instalace JLL (bez DB mutací)."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from .sup_secret import SupSecretStore
from .version import application_version

LOGGER = logging.getLogger(__name__)
DB_SERVICE_NAME = "JidelnaLocalLite"


class InstallationResetError(RuntimeError):
    """Reset nelze bezpečně dokončit; aktivní stav má zůstat / být obnoven."""


@dataclass(frozen=True, slots=True)
class InstallationResetPlan:
    config_path: Path
    identity_path: Path
    instance_id: str
    db_user: str
    site_name: str
    database: str
    reader_mode: str
    db_keyring_username: str
    sup_keyring_username: str
    sup_fallback_path: Path | None
    backup_dir: Path
    config_exists: bool
    identity_exists: bool


@dataclass(frozen=True, slots=True)
class InstallationResetResult:
    backup_dir: Path
    already_clean: bool
    moved_config: bool
    moved_identity: bool
    cleared_db_credential: bool
    cleared_sup_secret: bool


class InstallationResetService:
    """Oddělená služba: žádná DB connection, žádné business write API."""

    def build_plan(self, *, config_path: Path, identity_path: Path) -> InstallationResetPlan:
        config_path = Path(config_path)
        identity_path = Path(identity_path)
        instance_id = ""
        db_user = ""
        site_name = ""
        database = ""
        reader_mode = ""
        if config_path.is_file():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise InstallationResetError("Aktivní config není platný JSON objekt.")
            instance_id = str(raw.get("instance_id") or "").strip()
            db_user = str(raw.get("user") or "").strip()
            site_name = str(raw.get("site_name") or "").strip()
            database = str(raw.get("database") or "").strip()
            reader_mode = str(raw.get("reader_mode") or "").strip()
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_root = config_path.parent / "reset-backups"
        backup_dir = backup_root / stamp
        fallback = (
            (config_path.parent / "secrets" / f"sup.{instance_id}.hash")
            if instance_id
            else None
        )
        return InstallationResetPlan(
            config_path=config_path,
            identity_path=identity_path,
            instance_id=instance_id or "LAB",
            db_user=db_user or "postgres",
            site_name=site_name,
            database=database,
            reader_mode=reader_mode,
            db_keyring_username=(
                f"{instance_id}:{db_user}" if instance_id and db_user else ""
            ),
            sup_keyring_username=f"jll-sup:{instance_id}" if instance_id else "",
            sup_fallback_path=fallback,
            backup_dir=backup_dir,
            config_exists=config_path.is_file(),
            identity_exists=identity_path.is_file(),
        )

    def execute(self, plan: InstallationResetPlan) -> InstallationResetResult:
        if not plan.config_exists and not plan.identity_exists:
            LOGGER.info(
                "installation reset requested: already clean config=%s identity=%s",
                plan.config_path,
                plan.identity_path,
            )
            return InstallationResetResult(
                backup_dir=plan.backup_dir,
                already_clean=True,
                moved_config=False,
                moved_identity=False,
                cleared_db_credential=False,
                cleared_sup_secret=False,
            )

        LOGGER.info(
            "installation reset requested config=%s identity=%s",
            plan.config_path,
            plan.identity_path,
        )
        self._create_backup(plan)
        moved_config = False
        moved_identity = False
        try:
            if plan.config_exists:
                self._remove_active(plan.config_path)
                moved_config = True
            if plan.identity_exists:
                self._remove_active(plan.identity_path)
                moved_identity = True
            cleared_db = self._clear_db_credential(plan)
            cleared_sup = self._clear_sup_secret(plan)
        except Exception as exc:
            LOGGER.exception("installation reset failed; attempting file rollback")
            self._rollback_files(plan, moved_config=moved_config, moved_identity=moved_identity)
            raise InstallationResetError(
                "Obnovení se nepodařilo a stav instalace vyžaduje servisní kontrolu."
                f" Záloha: {plan.backup_dir}"
            ) from exc

        if plan.config_path.is_file() or plan.identity_path.is_file():
            raise InstallationResetError(
                "Aktivní konfigurace stále existuje po resetu."
            )

        LOGGER.info(
            "local artifacts reset backup=%s moved_config=%s moved_identity=%s",
            plan.backup_dir,
            moved_config,
            moved_identity,
        )
        return InstallationResetResult(
            backup_dir=plan.backup_dir,
            already_clean=False,
            moved_config=moved_config,
            moved_identity=moved_identity,
            cleared_db_credential=cleared_db,
            cleared_sup_secret=cleared_sup,
        )

    def _create_backup(self, plan: InstallationResetPlan) -> None:
        try:
            plan.backup_dir.mkdir(parents=True, exist_ok=False)
            secrets_dir = plan.backup_dir / "secrets"
            secrets_dir.mkdir(parents=True, exist_ok=True)
            if plan.config_exists:
                shutil.copy2(plan.config_path, plan.backup_dir / plan.config_path.name)
            if plan.identity_exists:
                shutil.copy2(
                    plan.identity_path, plan.backup_dir / plan.identity_path.name
                )
            if plan.sup_fallback_path is not None and plan.sup_fallback_path.is_file():
                shutil.copy2(
                    plan.sup_fallback_path,
                    secrets_dir / plan.sup_fallback_path.name,
                )
            manifest: dict[str, Any] = {
                "timestamp": plan.backup_dir.name,
                "application_version": application_version(),
                "original_config_path": str(plan.config_path),
                "original_identity_path": str(plan.identity_path),
                "site_name": plan.site_name,
                "instance_id": plan.instance_id,
                "database": plan.database,
                "db_user": plan.db_user,
                "reader_mode": plan.reader_mode,
            }
            (plan.backup_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            if plan.backup_dir.exists():
                shutil.rmtree(plan.backup_dir, ignore_errors=True)
            raise InstallationResetError(
                "Počáteční nastavení nebylo obnoveno. "
                "Nepodařilo se vytvořit bezpečnostní zálohu. "
                "Původní nastavení zůstalo aktivní."
            ) from exc
        # Verify backup completeness before touching active files.
        if plan.config_exists and not (plan.backup_dir / plan.config_path.name).is_file():
            raise InstallationResetError(
                "Počáteční nastavení nebylo obnoveno. "
                "Nepodařilo se vytvořit bezpečnostní zálohu. "
                "Původní nastavení zůstalo aktivní."
            )
        if plan.identity_exists and not (
            plan.backup_dir / plan.identity_path.name
        ).is_file():
            raise InstallationResetError(
                "Počáteční nastavení nebylo obnoveno. "
                "Nepodařilo se vytvořit bezpečnostní zálohu. "
                "Původní nastavení zůstalo aktivní."
            )

    @staticmethod
    def _remove_active(path: Path) -> None:
        path.unlink()

    def _rollback_files(
        self,
        plan: InstallationResetPlan,
        *,
        moved_config: bool,
        moved_identity: bool,
    ) -> None:
        try:
            if moved_config:
                src = plan.backup_dir / plan.config_path.name
                if src.is_file() and not plan.config_path.is_file():
                    shutil.copy2(src, plan.config_path)
            if moved_identity:
                src = plan.backup_dir / plan.identity_path.name
                if src.is_file() and not plan.identity_path.is_file():
                    shutil.copy2(src, plan.identity_path)
        except Exception:
            LOGGER.exception("file rollback after failed reset also failed")

    def _clear_db_credential(self, plan: InstallationResetPlan) -> bool:
        if not plan.db_keyring_username:
            return False
        return self._delete_keyring_username(plan.db_keyring_username)

    def _clear_sup_secret(self, plan: InstallationResetPlan) -> bool:
        store = SupSecretStore(
            plan.instance_id,
            fallback_dir=(
                plan.sup_fallback_path.parent
                if plan.sup_fallback_path is not None
                else None
            ),
        )
        store.clear_strict()
        return True

    @staticmethod
    def _delete_keyring_username(username: str) -> bool:
        try:
            existing = keyring.get_password(DB_SERVICE_NAME, username)
        except KeyringError as exc:
            raise InstallationResetError(
                "Obnovení se nepodařilo: keyring není dostupný pro DB credential."
            ) from exc
        if not existing:
            return False
        try:
            keyring.delete_password(DB_SERVICE_NAME, username)
        except PasswordDeleteError:
            # Race: already gone.
            return True
        except KeyringError as exc:
            raise InstallationResetError(
                "Obnovení se nepodařilo: DB credential v keyring nelze smazat."
            ) from exc
        try:
            if keyring.get_password(DB_SERVICE_NAME, username):
                raise InstallationResetError(
                    "Obnovení se nepodařilo: DB credential v keyring stále existuje."
                )
        except KeyringError as exc:
            raise InstallationResetError(
                "Obnovení se nepodařilo: keyring nelze ověřit po smazání DB credential."
            ) from exc
        return True
