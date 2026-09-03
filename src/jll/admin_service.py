from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from pathlib import Path

from .config import LabConfig, save_lab_config
from .identity_store import IdentityStore, UserRecord
from .policy import Permission
from .session import AuthService, SessionManager


class AdminReauthenticationRequired(RuntimeError):
    pass


class AdminService:
    def __init__(
        self,
        session: SessionManager,
        auth: AuthService,
        store: IdentityStore,
        *,
        reauth_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
        lab_config: LabConfig | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.session = session
        self.auth = auth
        self.store = store
        self.reauth_seconds = reauth_seconds
        self._clock = clock
        self._reauth_until = 0.0
        self._lab_config = lab_config
        self._config_path = Path(config_path) if config_path else None

    def reauthenticate(self, pin: str) -> None:
        self.session.require(Permission.ADMIN_USERS)
        current = self.session.current_user()
        authenticated = self.auth.authenticate(current.user_id, pin)
        if authenticated.user_id != current.user_id:
            raise AdminReauthenticationRequired("Reauth identita se neshoduje.")
        self._reauth_until = self._clock() + self.reauth_seconds

    def _require(self, permission: Permission) -> str:
        self.session.require(permission)
        if self._clock() >= self._reauth_until:
            raise AdminReauthenticationRequired(
                "Administrace vyžaduje opětovné zadání PINu."
            )
        return self.session.current_actor().audit_actor

    def list_users(self) -> list[UserRecord]:
        self._require(Permission.ADMIN_USERS)
        return self.store.list_users()

    def add_user(
        self,
        *,
        user_id: str,
        display_name: str,
        short_code: str,
        pin: str,
        permissions: frozenset[Permission],
    ) -> UserRecord:
        actor = self._require(Permission.ADMIN_USERS)
        return self.store.add_user(
            actor=actor,
            user_id=user_id,
            display_name=display_name,
            short_code=short_code,
            pin=pin,
            permissions=permissions,
        )

    def set_permissions(
        self,
        user_id: str,
        permissions: frozenset[Permission],
    ) -> None:
        actor = self._require(Permission.ADMIN_PERMISSIONS)
        self.store.set_permissions(
            actor=actor,
            user_id=user_id,
            permissions=permissions,
        )

    def set_active(self, user_id: str, active: bool) -> None:
        actor = self._require(Permission.ADMIN_USERS)
        self.store.set_active(actor=actor, user_id=user_id, active=active)

    def update_access(
        self,
        user_id: str,
        permissions: frozenset[Permission],
        active: bool,
    ) -> None:
        self.session.require(Permission.ADMIN_USERS)
        actor = self._require(Permission.ADMIN_PERMISSIONS)
        self.store.update_access(
            actor=actor,
            user_id=user_id,
            permissions=permissions,
            active=active,
        )

    def audit_events(self) -> list[dict[str, object]]:
        self._require(Permission.ADMIN_AUDIT)
        return self.store.read_audit()

    def require_reader_diagnostics(self) -> None:
        self._require(Permission.ADMIN_READER)

    @property
    def reader_settings_writable(self) -> bool:
        """Zápis nastavení čtečky je možný jen se známým instalačním configem."""

        return self._lab_config is not None and self._config_path is not None

    def save_reader_settings(
        self,
        *,
        port: str | None,
        baud_rate: int,
        line_end: str,
    ) -> LabConfig:
        """Uloží ne-secret nastavení čtečky do instalační konfigurace.

        Vyžaduje `admin.reader` i platný reauth. Operace se nikdy nedotkne
        databáze; validaci hodnot provádí `LabConfig`.
        """

        self._require(Permission.ADMIN_READER)
        if self._lab_config is None or self._config_path is None:
            raise RuntimeError(
                "Instalační konfigurace není dostupná, nastavení nelze uložit."
            )
        updated = dataclasses.replace(
            self._lab_config,
            reader_port=(port.strip() or None) if port else None,
            reader_baud_rate=int(baud_rate),
            reader_line_end=line_end,
        )
        save_lab_config(updated, self._config_path)
        self._lab_config = updated
        return updated
