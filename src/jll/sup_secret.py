"""SUP admin secret (odděleně od public.uzivatel.heslo)."""

from __future__ import annotations

import logging
from pathlib import Path

import keyring
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

LOGGER = logging.getLogger(__name__)
SERVICE_NAME = "JidelnaLocalLite"
KEY_PREFIX = "jll-sup"


def _hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


class SupSecretStore:
    def __init__(self, instance_id: str, *, fallback_dir: Path | None = None) -> None:
        self.instance_id = instance_id.strip() or "LAB"
        self.fallback_dir = fallback_dir
        self._username = f"{KEY_PREFIX}:{self.instance_id}"

    def exists(self) -> bool:
        return bool(self._load_hash())

    def set_password(self, password: str) -> None:
        password = password.strip()
        if len(password) < 4:
            raise ValueError("SUP heslo musí mít alespoň 4 znaky.")
        digest = _hasher().hash(password)
        try:
            keyring.set_password(SERVICE_NAME, self._username, digest)
        except Exception:
            LOGGER.warning("keyring unavailable; using file fallback for SUP hash")
            self._write_fallback(digest)

    def verify(self, password: str) -> bool:
        digest = self._load_hash()
        if not digest:
            return False
        try:
            return _hasher().verify(digest, password.strip())
        except (VerifyMismatchError, InvalidHashError):
            return False

    def clear(self) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, self._username)
        except Exception:
            pass
        path = self._fallback_path()
        if path is not None and path.exists():
            path.unlink()

    def _load_hash(self) -> str | None:
        try:
            value = keyring.get_password(SERVICE_NAME, self._username)
            if value:
                return value
        except Exception:
            LOGGER.debug("keyring read failed for SUP", exc_info=True)
        path = self._fallback_path()
        if path is not None and path.exists():
            return path.read_text(encoding="utf-8").strip() or None
        return None

    def _fallback_path(self) -> Path | None:
        if self.fallback_dir is None:
            return None
        self.fallback_dir.mkdir(parents=True, exist_ok=True)
        return self.fallback_dir / f"sup.{self.instance_id}.hash"

    def _write_fallback(self, digest: str) -> None:
        path = self._fallback_path()
        if path is None:
            raise RuntimeError("Nelze uložit SUP heslo (keyring i fallback selhaly).")
        path.write_text(digest + "\n", encoding="utf-8")
