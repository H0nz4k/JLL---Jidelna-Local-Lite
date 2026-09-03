from __future__ import annotations

import time
from collections.abc import Callable

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
    ) -> None:
        self.session = session
        self.auth = auth
        self.store = store
        self.reauth_seconds = reauth_seconds
        self._clock = clock
        self._reauth_until = 0.0

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
