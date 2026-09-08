"""Admin viewmodel – users from public.uzivatel + SUP gate."""

from __future__ import annotations

import dataclasses

from ...business_session import BusinessSession
from ...config import save_lab_config
from ...legacy_users import LegacyUserRow
from ...policy import Permission
from ...setup_probe import CategoryOption, list_category_options
from ..state import AppState


class AdminViewModel:
    def __init__(self, state: AppState) -> None:
        self.state = state

    @property
    def business(self) -> BusinessSession:
        assert self.state.business is not None
        return self.state.business

    def require_sup_password(self, password: str) -> bool:
        return self.business.unlock_sup(password)

    def list_db_users(self) -> tuple[LegacyUserRow, ...]:
        self.business.require_sup()
        with self.business.connection_factory() as connection:
            from ...legacy_users import LegacyUserRepository

            return LegacyUserRepository(connection).list_users(include_disabled=True)

    def create_user(self, code: str, display_name: str) -> LegacyUserRow:
        return self.business.create_business_user(code, display_name)

    def ensure_profile(self, user: LegacyUserRow):
        return self.business.ensure_jll_profile(user)

    def set_permissions(self, short_code: str, permissions: frozenset[Permission]) -> None:
        self.business.require_sup()
        profile = None
        for item in self.business.identity_store.list_users():
            if item.short_code.casefold() == short_code.casefold():
                profile = item
                break
        if profile is None:
            raise RuntimeError("Uživatel nemá JLL profil.")
        self.business.identity_store.set_permissions(
            actor=self.business.current_actor().audit_actor,
            user_id=profile.user_id,
            permissions=permissions,
        )

    def list_category_options(self) -> tuple[CategoryOption, ...]:
        """Katalog kategorií z `public.kategor` pro správu scope."""

        self.business.require_sup()
        with self.business.connection_factory() as connection:
            return list_category_options(connection)

    def save_allowed_categories(self, categories: frozenset[str]) -> None:
        """Uloží `allowed_categories` do LAB configu a aktualizuje session.

        Mutace je chráněná SUP reauth (stejně jako správa uživatelů).
        """

        self.business.require_sup()
        cfg = self.state.config
        if cfg is None:
            raise RuntimeError("Config není načten.")
        known = {item.code for item in self.list_category_options()}
        normalized = frozenset(
            value.strip() for value in categories if isinstance(value, str) and value.strip()
        )
        if not normalized:
            raise ValueError("Vyberte alespoň jednu povolenou kategorii.")
        unknown = sorted(normalized - known)
        if unknown:
            raise ValueError(
                "Neznámé kategorie (nejsou v public.kategor): " + ", ".join(unknown)
            )
        updated = dataclasses.replace(cfg, allowed_categories=normalized)
        save_lab_config(updated, self.state.config_path)
        self.state.config = updated
        self.business.config = updated
