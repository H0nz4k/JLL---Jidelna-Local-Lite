"""First-run setup viewmodel (LAB | PRODUCTION, no PIN)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from ...business_session import BusinessSession
from ...config import JllConfig, save_config
from ...identity_store import IdentityStore
from ...setup_probe import (
    DatabaseProbe,
    StationOption,
    derive_site_id,
    probe_lab_database,
    probe_production_database,
)
from ...sup_secret import SupSecretStore
from ..state import AppState


@dataclass
class SetupDraft:
    environment: str = "lab"  # lab | production
    host: str = "127.0.0.1"
    port: str = "5433"
    database: str = "jll_demo_lab"
    user: str = "postgres"
    password: str = ""
    probe: DatabaseProbe | None = None
    site_name: str = ""
    station: StationOption | None = None
    categories: list[str] = field(default_factory=list)
    sup_password: str = ""
    sup_password_confirm: str = ""
    step: int = 0
    error: str = ""


class SetupViewModel:
    STEPS = (
        "Režim",
        "Databáze",
        "Provozovna a stanice",
        "Povolené kategorie",
        "SUP heslo",
        "Souhrn",
    )

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.draft = SetupDraft()

    @property
    def is_production(self) -> bool:
        return self.draft.environment.strip().lower() == "production"

    def test_database(self) -> DatabaseProbe:
        port = int(self.draft.port)
        if self.is_production:
            probe = probe_production_database(
                host=self.draft.host.strip(),
                port=port,
                database=self.draft.database.strip(),
                user=self.draft.user.strip(),
                password=self.draft.password,
            )
        else:
            probe = probe_lab_database(
                host=self.draft.host.strip(),
                port=port,
                database=self.draft.database.strip(),
                user=self.draft.user.strip(),
                password=self.draft.password,
            )
        self.draft.probe = probe
        if probe.subject_name:
            self.draft.site_name = probe.subject_name
        self.draft.error = ""
        return probe

    def validate_sup(self) -> None:
        if len(self.draft.sup_password.strip()) < 4:
            raise ValueError("SUP heslo musí mít alespoň 4 znaky.")
        if self.draft.sup_password != self.draft.sup_password_confirm:
            raise ValueError("Hesla SUP se neshodují.")

    def finish(self) -> JllConfig:
        if self.draft.probe is None:
            raise RuntimeError("Nejprve ověřte databázi.")
        if self.draft.station is None:
            raise RuntimeError("Vyberte stanici.")
        if not self.draft.station.usable_as_instance_id:
            raise RuntimeError("Vybraná stanice nemá platný identifikátor.")
        if not self.draft.categories:
            raise RuntimeError("Vyberte alespoň jednu kategorii.")
        site_name = self.draft.site_name.strip()
        if not site_name:
            raise RuntimeError("Zadejte název provozovny.")
        self.validate_sup()
        probe = self.draft.probe
        environment = "production" if self.is_production else "lab"
        if self.is_production and not self.draft.password:
            raise RuntimeError(
                "Production setup vyžaduje databázové heslo uložené do keyringu."
            )
        config = JllConfig(
            site_name=site_name,
            site_id=derive_site_id(site_name),
            instance_id=self.draft.station.name,
            allowed_categories=frozenset(self.draft.categories),
            host=self.draft.host.strip(),
            port=int(self.draft.port),
            database=self.draft.database.strip(),
            user=self.draft.user.strip(),
            environment=environment,
            expected_system_identifier=probe.system_identifier,
            business_timezone="Europe/Prague",
            strict_config_lock=True,
            search_limit=30,
        )
        save_config(config, self.state.config_path)
        if self.draft.password:
            try:
                keyring.set_password(
                    "JidelnaLocalLite",
                    f"{config.instance_id}:{config.user}",
                    self.draft.password,
                )
            except KeyringError as exc:
                # Fail-closed: config už je zapsán → smaž a ohlas.
                try:
                    self.state.config_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise RuntimeError(
                    "Credential store selhal. Production setup nebyl dokončen."
                ) from exc
            stored = keyring.get_password(
                "JidelnaLocalLite",
                f"{config.instance_id}:{config.user}",
            )
            if self.is_production and not stored:
                try:
                    self.state.config_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise RuntimeError(
                    "Credential store neuložil heslo. Production setup nebyl dokončen."
                )
        identity = IdentityStore(self.state.identity_path)
        fallback = self.state.config_path.parent / "secrets"
        sup = SupSecretStore(config.instance_id, fallback_dir=fallback)
        if not identity.exists:
            ved_name = "Vedoucí"
            pool = config.create_pool()
            try:
                with pool.connection() as connection:
                    from ...legacy_users import LegacyUserRepository

                    ved = LegacyUserRepository(connection).get_user("VED")
                    if ved is None:
                        raise RuntimeError(
                            "V databázi chybí uživatel VED. "
                            "Setup nelze dokončit bez schváleného identity kontraktu."
                        )
                    ved_name = ved.display_name
            finally:
                pool.close()
            BusinessSession(
                config=config,
                identity_store=identity,
                connection_factory=config.connection_factory,
                sup_store=sup,
            ).seed_identity_for_setup(ved_display_name=ved_name)
        try:
            sup.set_password(self.draft.sup_password.strip())
        except Exception as exc:
            raise RuntimeError(
                "SUP heslo se nepodařilo bezpečně uložit. Setup nebyl dokončen."
            ) from exc
        self.state.config = config
        self.state.identity_store = identity
        return config
