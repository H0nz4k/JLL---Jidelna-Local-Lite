"""First-run setup viewmodel (LAB | PRODUCTION, no PIN)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import keyring
import psycopg
from keyring.errors import KeyringError, PasswordDeleteError

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
    STEPS_CHOICE = (
        "Režim",
        "Databáze",
        "Provozovna a stanice",
        "Povolené kategorie",
        "SUP heslo",
        "Souhrn",
    )
    STEPS_FIXED = (
        "Databáze",
        "Provozovna a stanice",
        "Povolené kategorie",
        "SUP heslo",
        "Souhrn",
    )

    def __init__(
        self,
        state: AppState,
        *,
        environment_hint: str = "lab",
        allow_environment_choice: bool = True,
    ) -> None:
        self.state = state
        hint = environment_hint.strip().lower()
        if hint not in {"lab", "production"}:
            hint = "lab"
        self.environment_hint = hint
        self.allow_environment_choice = allow_environment_choice
        self.draft = SetupDraft(environment=hint)
        if not allow_environment_choice:
            self.draft.environment = hint
            if hint == "production":
                self.draft.host = ""
                self.draft.port = "5432"
                self.draft.database = ""
                self.draft.user = ""

    @property
    def STEPS(self) -> tuple[str, ...]:
        if self.allow_environment_choice:
            return self.STEPS_CHOICE
        return self.STEPS_FIXED

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

        keyring_username = f"{config.instance_id}:{config.user}"
        created_keyring = False
        created_identity = False
        created_sup = False
        created_config = False
        identity = IdentityStore(self.state.identity_path)
        identity_existed = identity.exists
        fallback = self.state.config_path.parent / "secrets"
        sup = SupSecretStore(config.instance_id, fallback_dir=fallback)
        sup_existed = False
        try:
            sup_existed = bool(sup.exists())
        except Exception:
            sup_existed = False

        def _rollback() -> None:
            if created_config:
                try:
                    self.state.config_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if created_sup and not sup_existed:
                try:
                    sup.clear()
                except Exception:
                    pass
            if created_identity and not identity_existed:
                try:
                    self.state.identity_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if created_keyring:
                try:
                    keyring.delete_password("JidelnaLocalLite", keyring_username)
                except (KeyringError, PasswordDeleteError, Exception):
                    pass

        try:
            # 1) Preflight VED (read-only) — přímé spojení z draftu, bez lokálních artefaktů.
            ved_name = "Vedoucí"
            connect_kwargs: dict = {
                "host": config.host,
                "port": config.port,
                "dbname": config.database,
                "user": config.user,
                "connect_timeout": 5,
                "autocommit": True,
            }
            if self.draft.password:
                connect_kwargs["password"] = self.draft.password

            with psycopg.connect(**connect_kwargs) as connection:
                from ...legacy_users import LegacyUserRepository

                ved = LegacyUserRepository(connection).get_user("VED")
                if ved is None:
                    raise RuntimeError(
                        "V databázi chybí uživatel VED. "
                        "Setup nelze dokončit bez schváleného identity kontraktu."
                    )
                ved_name = ved.display_name

            # 2) Credential backend + stage DB heslo (před config commit).
            if self.draft.password:
                try:
                    keyring.set_password(
                        "JidelnaLocalLite",
                        keyring_username,
                        self.draft.password,
                    )
                    created_keyring = True
                except KeyringError as exc:
                    raise RuntimeError(
                        "Credential store selhal. Setup nebyl dokončen."
                    ) from exc
                stored = keyring.get_password(
                    "JidelnaLocalLite",
                    keyring_username,
                )
                if self.is_production and not stored:
                    raise RuntimeError(
                        "Credential store neuložil heslo. Setup nebyl dokončen."
                    )

            # 3) Stage identity (pokud ještě neexistuje).
            if not identity.exists:
                BusinessSession(
                    config=config,
                    identity_store=identity,
                    connection_factory=config.connection_factory,
                    sup_store=sup,
                ).seed_identity_for_setup(ved_display_name=ved_name)
                created_identity = True
                if not identity.exists:
                    raise RuntimeError(
                        "Inicializace identity selhala. Setup nebyl dokončen."
                    )

            # 4) Stage SUP secret.
            try:
                sup.set_password(self.draft.sup_password.strip())
                created_sup = True
            except Exception as exc:
                raise RuntimeError(
                    "SUP heslo se nepodařilo bezpečně uložit. Setup nebyl dokončen."
                ) from exc

            # 5) Config jako finální commit marker.
            try:
                save_config(config, self.state.config_path)
                created_config = True
            except Exception as exc:
                raise RuntimeError(
                    "Konfiguraci se nepodařilo uložit. Setup nebyl dokončen."
                ) from exc
            if not self.state.config_path.is_file():
                raise RuntimeError(
                    "Konfiguraci se nepodařilo uložit. Setup nebyl dokončen."
                )
        except Exception:
            _rollback()
            raise

        self.state.config = config
        self.state.identity_store = identity
        return config
