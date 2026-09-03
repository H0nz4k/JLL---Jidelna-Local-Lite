from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .policy import Permission

SCHEMA_VERSION = 1
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
PIN_MIN_LENGTH = 4
PIN_MAX_LENGTH = 128


class IdentityStoreError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    display_name: str
    short_code: str
    pin_hash: str
    permissions: frozenset[Permission]
    active: bool = True

    def __post_init__(self) -> None:
        if not USER_ID_PATTERN.fullmatch(self.user_id):
            raise ValueError("user_id nemá platný formát.")
        if not USER_ID_PATTERN.fullmatch(self.short_code):
            raise ValueError("short_code nemá platný formát.")
        if not self.display_name.strip() or len(self.display_name) > 80:
            raise ValueError("display_name nemá platný formát.")
        if not self.pin_hash.startswith("$argon2id$"):
            raise ValueError("PIN není uložen jako Argon2id hash.")

    @property
    def is_admin(self) -> bool:
        return Permission.ADMIN_USERS in self.permissions


def create_password_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


class IdentityStore:
    def __init__(
        self,
        path: str | Path,
        *,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self.path = Path(path)
        self.password_hasher = password_hasher or create_password_hasher()
        self._dummy_hash = self.password_hasher.hash("JLL-invalid-user-dummy")

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def initialize(
        self,
        users: list[tuple[str, str, str, str, frozenset[Permission]]],
        *,
        actor: str = "SETUP",
    ) -> None:
        if self.exists:
            raise IdentityStoreError("Identity store již existuje.")
        if not users:
            raise IdentityStoreError("Musí existovat alespoň první administrátor.")
        records = [
            self._new_user_record(user_id, display_name, short_code, pin, permissions)
            for user_id, display_name, short_code, pin, permissions in users
        ]
        if (
            len({record.user_id for record in records}) != len(records)
            or len({record.short_code for record in records}) != len(records)
        ):
            raise IdentityStoreError("User ID a krátké kódy musí být jedinečné.")
        if sum(record.active and record.is_admin for record in records) < 1:
            raise IdentityStoreError("Chybí aktivní administrátor.")
        now = self._timestamp()
        data = {
            "schema_version": SCHEMA_VERSION,
            "revision": 1,
            "users": [self._serialize_user(record) for record in records],
            "audit_events": [
                {
                    "timestamp": now,
                    "actor": actor,
                    "action": "identity_store.initialized",
                    "target": None,
                    "result": "committed",
                }
            ],
        }
        self._atomic_write(data)

    def revision(self) -> int:
        return int(self._load()["revision"])

    def list_users(self, *, active_only: bool = False) -> list[UserRecord]:
        users = [self._parse_user(item) for item in self._load()["users"]]
        if active_only:
            users = [item for item in users if item.active]
        return sorted(users, key=lambda item: (item.display_name.casefold(), item.user_id))

    def get_user(self, user_id: str) -> UserRecord | None:
        return next(
            (item for item in self.list_users() if item.user_id == user_id),
            None,
        )

    def authenticate(self, user_id: str, pin: str) -> UserRecord:
        user = self.get_user(user_id)
        candidate_hash = user.pin_hash if user is not None else self._dummy_hash
        try:
            valid = self.password_hasher.verify(candidate_hash, pin)
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if user is None or not user.active or not valid:
            raise AuthenticationError("Neplatný uživatel nebo PIN.")
        return user

    def add_user(
        self,
        *,
        actor: str,
        user_id: str,
        display_name: str,
        short_code: str,
        pin: str,
        permissions: frozenset[Permission],
    ) -> UserRecord:
        data = self._load()
        if any(item["user_id"] == user_id for item in data["users"]):
            raise IdentityStoreError("Uživatel již existuje.")
        record = self._new_user_record(
            user_id,
            display_name,
            short_code,
            pin,
            permissions,
        )
        data["users"].append(self._serialize_user(record))
        self._commit(data, actor, "user.created", user_id)
        return record

    def set_permissions(
        self,
        *,
        actor: str,
        user_id: str,
        permissions: frozenset[Permission],
    ) -> None:
        data = self._load()
        raw = self._raw_user(data, user_id)
        raw["permissions"] = sorted(item.value for item in permissions)
        self._assert_active_admin(data)
        self._commit(data, actor, "user.permissions_changed", user_id)

    def update_access(
        self,
        *,
        actor: str,
        user_id: str,
        permissions: frozenset[Permission],
        active: bool,
    ) -> None:
        data = self._load()
        raw = self._raw_user(data, user_id)
        raw["permissions"] = sorted(item.value for item in permissions)
        raw["active"] = bool(active)
        self._assert_active_admin(data)
        self._commit(data, actor, "user.access_changed", user_id)

    def set_active(self, *, actor: str, user_id: str, active: bool) -> None:
        data = self._load()
        raw = self._raw_user(data, user_id)
        raw["active"] = bool(active)
        self._assert_active_admin(data)
        self._commit(
            data,
            actor,
            "user.activated" if active else "user.deactivated",
            user_id,
        )

    def change_pin(
        self,
        *,
        actor: str,
        user_id: str,
        new_pin: str,
    ) -> None:
        self._validate_pin(new_pin)
        data = self._load()
        raw = self._raw_user(data, user_id)
        raw["pin_hash"] = self.password_hasher.hash(new_pin)
        self._commit(data, actor, "user.pin_changed", user_id)

    def read_audit(self, *, limit: int = 200) -> list[dict[str, Any]]:
        events = list(self._load()["audit_events"])
        return events[-max(1, min(limit, 1_000)) :]

    def _new_user_record(
        self,
        user_id: str,
        display_name: str,
        short_code: str,
        pin: str,
        permissions: frozenset[Permission],
    ) -> UserRecord:
        self._validate_pin(pin)
        return UserRecord(
            user_id=user_id.strip(),
            display_name=display_name.strip(),
            short_code=short_code.strip().upper(),
            pin_hash=self.password_hasher.hash(pin),
            permissions=frozenset(permissions),
            active=True,
        )

    @staticmethod
    def _validate_pin(pin: str) -> None:
        if not isinstance(pin, str) or not PIN_MIN_LENGTH <= len(pin) <= PIN_MAX_LENGTH:
            raise ValueError(
                f"PIN musí mít {PIN_MIN_LENGTH} až {PIN_MAX_LENGTH} znaků."
            )

    @staticmethod
    def _serialize_user(user: UserRecord) -> dict[str, Any]:
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "short_code": user.short_code,
            "pin_hash": user.pin_hash,
            "permissions": sorted(item.value for item in user.permissions),
            "active": user.active,
        }

    @staticmethod
    def _parse_user(raw: dict[str, Any]) -> UserRecord:
        try:
            permissions = frozenset(
                Permission(value) for value in raw["permissions"]
            )
            return UserRecord(
                user_id=str(raw["user_id"]),
                display_name=str(raw["display_name"]),
                short_code=str(raw["short_code"]),
                pin_hash=str(raw["pin_hash"]),
                permissions=permissions,
                active=raw["active"] is True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityStoreError("Identity store obsahuje neplatného uživatele.") from exc

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityStoreError("Identity store nelze bezpečně načíst.") from exc
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != SCHEMA_VERSION
            or not isinstance(data.get("revision"), int)
            or not isinstance(data.get("users"), list)
            or not isinstance(data.get("audit_events"), list)
        ):
            raise IdentityStoreError("Identity store nemá podporované schéma.")
        parsed = [self._parse_user(item) for item in data["users"]]
        if (
            len({item.user_id for item in parsed}) != len(parsed)
            or len({item.short_code for item in parsed}) != len(parsed)
        ):
            raise IdentityStoreError("Identity store obsahuje duplicitní identity.")
        if not parsed or not any(item.active and item.is_admin for item in parsed):
            raise IdentityStoreError("Identity store nemá aktivního administrátora.")
        return data

    @staticmethod
    def _raw_user(data: dict[str, Any], user_id: str) -> dict[str, Any]:
        for item in data["users"]:
            if item.get("user_id") == user_id:
                return item
        raise IdentityStoreError("Uživatel neexistuje.")

    def _assert_active_admin(self, data: dict[str, Any]) -> None:
        users = [self._parse_user(item) for item in data["users"]]
        if not any(item.active and item.is_admin for item in users):
            raise IdentityStoreError(
                "Posledního aktivního administrátora nelze deaktivovat."
            )

    def _commit(
        self,
        data: dict[str, Any],
        actor: str,
        action: str,
        target: str | None,
    ) -> None:
        data["revision"] = int(data["revision"]) + 1
        data["audit_events"].append(
            {
                "timestamp": self._timestamp(),
                "actor": actor,
                "action": action,
                "target": target,
                "result": "committed",
            }
        )
        self._atomic_write(data)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
