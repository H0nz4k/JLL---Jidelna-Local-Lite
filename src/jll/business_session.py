"""Business session: VED default, user switch, SUP reauth."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import LabConfig
from .identity import ActorContext
from .identity_store import IdentityStore, UserRecord, generate_user_id
from .legacy_users import LegacyUserRepository, LegacyUserRow
from .policy import Permission, SessionPolicy
from .sup_secret import SupSecretStore
from .version import audit_client_version

LOGGER = logging.getLogger(__name__)
ConnectionFactory = Callable[[], Any]
DEFAULT_VED = "VED"
DEFAULT_SUP = "SUP"
UNUSED_PIN_MARKER = "!JllNoPinLogin"
VED_DEFAULT_PERMISSIONS = frozenset(
    {
        Permission.DINERS_VIEW,
        Permission.DINERS_CREATE,
        Permission.DINERS_EDIT,
        Permission.CHIPS_VIEW,
        Permission.CHIPS_ASSIGN,
        Permission.CHIPS_RETURN,
        Permission.CHIPS_BLOCK,
        Permission.CHIPS_LOST,
        Permission.ORDERS_VIEW,
        Permission.ORDERS_CHANGE,
        Permission.PICKUP_STATUS_VIEW,
        Permission.REPORTS_VIEW,
        Permission.REPORTS_PRINT,
    }
)
SUP_TECHNICAL_PERMISSIONS = frozenset(Permission)


@dataclass
class BusinessSession:
    config: LabConfig
    identity_store: IdentityStore
    connection_factory: ConnectionFactory
    sup_store: SupSecretStore
    client_version: str = field(default_factory=audit_client_version)
    current_code: str = DEFAULT_VED
    _sup_until: float = 0.0
    _session_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def bootstrap_ved(self) -> LegacyUserRow:
        with self.connection_factory() as connection:
            repo = LegacyUserRepository(connection)
            ved = repo.get_user(DEFAULT_VED)
        if ved is None or ved.disabled:
            raise RuntimeError(
                "Uživatel VED není v public.uzivatel dostupný. "
                "Dokončete legacy setup nebo obnovte LAB data."
            )
        self.ensure_jll_profile(ved)
        self.current_code = ved.code
        self._session_id = uuid.uuid4().hex
        self._sup_until = 0.0
        return ved

    def ensure_jll_profile(self, legacy: LegacyUserRow) -> UserRecord:
        existing = self._find_by_short_code(legacy.code)
        if existing is not None:
            return existing
        permissions = self._default_permissions_for(legacy)
        return self.identity_store.add_user(
            actor="system:flet",
            user_id=generate_user_id(
                existing={item.user_id for item in self.identity_store.list_users()}
            ),
            display_name=legacy.display_name,
            short_code=legacy.code.upper()[:20],
            pin=self._unused_pin(),
            permissions=permissions,
        )

    def list_switchable_users(self) -> tuple[LegacyUserRow, ...]:
        with self.connection_factory() as connection:
            users = LegacyUserRepository(connection).list_users(include_disabled=False)
        return tuple(
            user
            for user in users
            if user.code.upper() != DEFAULT_SUP and not user.is_admin
        )

    def switch_user(self, code: str) -> LegacyUserRow:
        with self.connection_factory() as connection:
            user = LegacyUserRepository(connection).get_user(code)
        if user is None or user.disabled:
            raise RuntimeError("Uživatele nelze aktivovat.")
        if user.code.upper() == DEFAULT_SUP or user.is_admin:
            raise RuntimeError("SUP nelze aktivovat jen přes administrátorské ověření.")
        self.ensure_jll_profile(user)
        self.current_code = user.code
        self._session_id = uuid.uuid4().hex
        self._sup_until = 0.0
        return user

    def current_legacy(self) -> LegacyUserRow:
        with self.connection_factory() as connection:
            user = LegacyUserRepository(connection).get_user(self.current_code)
        if user is None or user.disabled:
            raise RuntimeError("Aktuální uživatel není dostupný.")
        return user

    def current_jll_user(self) -> UserRecord:
        return self.ensure_jll_profile(self.current_legacy())

    def current_policy(self) -> SessionPolicy:
        user = self.current_jll_user()
        return SessionPolicy(
            user_identity=user.display_name,
            allowed_categories=self.config.allowed_categories,
            permissions=user.permissions,
        )

    def current_actor(self) -> ActorContext:
        user = self.current_jll_user()
        legacy = self.current_legacy()
        return ActorContext(
            site_id=self.config.site_id,
            instance_id=self.config.instance_id,
            user_id=user.user_id,
            short_code=legacy.code,
            session_id=self._session_id,
            client_version=self.client_version,
        )

    def unlock_sup(self, password: str, *, ttl_seconds: float = 600.0) -> bool:
        if not self.sup_store.verify(password):
            return False
        self._sup_until = time.monotonic() + ttl_seconds
        return True

    def lock_sup(self) -> None:
        self._sup_until = 0.0

    def sup_unlocked(self) -> bool:
        return time.monotonic() < self._sup_until

    def require_sup(self) -> None:
        if not self.sup_unlocked():
            raise PermissionError("Vyžadováno ověření administrátora SUP.")

    def create_business_user(self, code: str, display_name: str) -> LegacyUserRow:
        self.require_sup()
        with self.connection_factory() as connection:
            with connection.transaction():
                repo = LegacyUserRepository(connection)
                ved = repo.get_user(DEFAULT_VED)
                if ved is None:
                    raise RuntimeError("VED šablona chybí.")
                template = LegacyUserRow(
                    code=ved.code,
                    display_name=ved.display_name,
                    is_admin=False,
                    typ=ved.typ or "INTERNI",
                    disabled=False,
                    prava=ved.prava,
                    prava1=ved.prava1,
                    has_password=False,
                )
                created = repo.create_user_from_template(
                    code=code,
                    display_name=display_name,
                    template=template,
                )
        profile = self.ensure_jll_profile(created)
        ved_profile = self._find_by_short_code(DEFAULT_VED)
        if ved_profile is not None and profile.permissions != ved_profile.permissions:
            self.identity_store.set_permissions(
                actor="system:flet",
                user_id=profile.user_id,
                permissions=ved_profile.permissions,
            )
        return created

    def seed_identity_for_setup(self, *, ved_display_name: str = "Vedoucí") -> None:
        """Inicializace JLL identity store bez PIN UX (nepoužitelné PINy)."""

        if self.identity_store.exists:
            return
        existing: set[str] = set()
        ved_id = generate_user_id(existing=existing)
        existing.add(ved_id)
        sup_id = generate_user_id(existing=existing)
        self.identity_store.initialize(
            [
                (
                    ved_id,
                    ved_display_name,
                    DEFAULT_VED,
                    self._unused_pin(),
                    VED_DEFAULT_PERMISSIONS,
                ),
                (
                    sup_id,
                    "Administrátor SUP",
                    DEFAULT_SUP,
                    self._unused_pin(),
                    SUP_TECHNICAL_PERMISSIONS,
                ),
            ],
            actor="SETUP",
        )

    def _default_permissions_for(self, legacy: LegacyUserRow) -> frozenset[Permission]:
        if legacy.is_admin or legacy.code.upper() == DEFAULT_SUP:
            return SUP_TECHNICAL_PERMISSIONS
        ved_profile = self._find_by_short_code(DEFAULT_VED)
        if ved_profile is not None:
            return ved_profile.permissions
        return VED_DEFAULT_PERMISSIONS

    def _find_by_short_code(self, code: str) -> UserRecord | None:
        code = code.casefold()
        for user in self.identity_store.list_users():
            if user.short_code.casefold() == code:
                return user
        return None

    @staticmethod
    def _unused_pin() -> str:
        return uuid.uuid4().hex + UNUSED_PIN_MARKER
