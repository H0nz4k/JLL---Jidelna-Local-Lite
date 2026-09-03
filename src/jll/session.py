from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime

from .config import LabConfig
from .identity import ActorContext, AuthenticatedSession
from .identity_store import AuthenticationError, IdentityStore, UserRecord
from .policy import Permission, SessionPolicy
from .version import audit_client_version


class AuthService:
    def __init__(
        self,
        store: IdentityStore,
        *,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def authenticate(self, user_id: str, pin: str) -> UserRecord:
        key = user_id.strip()
        now = self._clock()
        failures = self._failures[key]
        while failures and now - failures[0] >= self.window_seconds:
            failures.popleft()
        if len(failures) >= self.max_attempts:
            raise AuthenticationError(
                "Příliš mnoho pokusů. Přihlášení je dočasně blokováno."
            )
        try:
            user = self.store.authenticate(key, pin)
        except AuthenticationError:
            failures.append(now)
            raise AuthenticationError("Neplatný uživatel nebo PIN.") from None
        failures.clear()
        return user


class SessionManager:
    def __init__(
        self,
        config: LabConfig,
        identity_store: IdentityStore,
        *,
        client_version: str | None = None,
    ) -> None:
        self.config = config
        self.identity_store = identity_store
        self.client_version = client_version or audit_client_version()
        self._session: AuthenticatedSession | None = None

    @property
    def authenticated(self) -> bool:
        return self._session is not None

    def start(self, user: UserRecord) -> AuthenticatedSession:
        if not user.active:
            raise AuthenticationError("Uživatel není aktivní.")
        self._session = AuthenticatedSession.create(user.user_id)
        return self._session

    def logout(self) -> None:
        self._session = None

    def current_user(self) -> UserRecord:
        if self._session is None:
            raise AuthenticationError("Chybí aktivní přihlášená session.")
        user = self.identity_store.get_user(self._session.user_id)
        if user is None or not user.active:
            self.logout()
            raise AuthenticationError("Session již není platná.")
        return user

    def current_policy(self) -> SessionPolicy:
        user = self.current_user()
        return SessionPolicy(
            user_identity=user.display_name,
            allowed_categories=self.config.allowed_categories,
            permissions=user.permissions,
        )

    def current_actor(self) -> ActorContext:
        if self._session is None:
            raise AuthenticationError("Chybí aktivní přihlášená session.")
        user = self.current_user()
        return ActorContext(
            site_id=self.config.site_id,
            instance_id=self.config.instance_id,
            user_id=user.user_id,
            short_code=user.short_code,
            session_id=self._session.session_id,
            client_version=self.client_version,
        )

    def require(self, permission: Permission) -> None:
        self.current_policy().require(permission)

    def scope_for_order(self, _command: object | None = None) -> frozenset[str]:
        self.require(Permission.ORDERS_CHANGE)
        return self.current_policy().scope()

    @property
    def login_time(self) -> datetime:
        if self._session is None:
            raise AuthenticationError("Chybí aktivní session.")
        return self._session.login_time
