"""Setup finish musí rollbackovat partial local artefacts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from keyring.errors import KeyringError

from jll.flet_ui.state import AppState
from jll.flet_ui.viewmodels.setup import SetupViewModel
from jll.setup_probe import DatabaseProbe, StationOption


def _probe(*, production: bool = False) -> DatabaseProbe:
    return DatabaseProbe(
        system_identifier=(
            "1234567890123456789" if production else "7507291640873906336"
        ),
        categories=("3",),
        subject_name="Demo",
        stations=(StationOption(station_id=1, name="ST01"),),
    )


def _ready_vm(tmp_path: Path, *, production: bool = False) -> SetupViewModel:
    state = AppState(
        config_path=tmp_path / "config" / "lab.json",
        identity_path=tmp_path / "config" / "users.json",
    )
    state.config_path.parent.mkdir(parents=True, exist_ok=True)
    vm = SetupViewModel(
        state,
        environment_hint="production" if production else "lab",
        allow_environment_choice=True,
    )
    vm.draft.environment = "production" if production else "lab"
    vm.draft.host = "db.example.local" if production else "127.0.0.1"
    vm.draft.port = "5432" if production else "5433"
    vm.draft.database = "jidelnasql" if production else "jll_demo_lab"
    vm.draft.user = "jll"
    vm.draft.password = "secret" if production else ""
    station_name = f"ST{tmp_path.name[-8:].upper().replace('-', '')[:8] or 'TEST0001'}"
    if not station_name[0].isalnum():
        station_name = "ST" + station_name[2:]
    vm.draft.probe = DatabaseProbe(
        system_identifier=(
            "1234567890123456789" if production else "7507291640873906336"
        ),
        categories=("3",),
        subject_name="Demo",
        stations=(StationOption(station_id=1, name=station_name),),
    )
    vm.draft.site_name = "Demo Site"
    vm.draft.station = vm.draft.probe.stations[0]
    vm.draft.categories = ["3"]
    vm.draft.sup_password = "sup-secret"
    vm.draft.sup_password_confirm = "sup-secret"
    return vm


def test_frozen_production_setup_skips_mode_keeps_categories(tmp_path: Path) -> None:
    state = AppState(
        config_path=tmp_path / "jll.json",
        identity_path=tmp_path / "users.json",
        environment_hint="production",
        allow_environment_choice=False,
    )
    vm = SetupViewModel(
        state,
        environment_hint="production",
        allow_environment_choice=False,
    )
    assert vm.STEPS == (
        "Databáze",
        "Provozovna a stanice",
        "Povolené kategorie",
        "SUP heslo",
        "Souhrn",
    )
    assert "Režim" not in vm.STEPS
    assert "Povolené kategorie" in vm.STEPS
    assert vm.is_production
    assert vm.draft.host == "127.0.0.1"
    assert vm.draft.database == "jidelna"
    assert vm.draft.user == "postgres"
    assert vm.draft.port == "5432"


def test_production_probe_does_not_auto_select_categories(tmp_path: Path) -> None:
    state = AppState(
        config_path=tmp_path / "jll.json",
        identity_path=tmp_path / "users.json",
        environment_hint="production",
        allow_environment_choice=False,
    )
    vm = SetupViewModel(
        state,
        environment_hint="production",
        allow_environment_choice=False,
    )
    probe = _probe(production=True)
    with patch(
        "jll.flet_ui.viewmodels.setup.probe_production_database",
        return_value=probe,
    ):
        vm.draft.password = "secret"
        result = vm.test_database()
    assert result is probe
    assert vm.draft.categories == []


def test_keyring_set_failure_leaves_no_config(tmp_path: Path) -> None:
    vm = _ready_vm(tmp_path, production=True)
    with patch("jll.flet_ui.viewmodels.setup.psycopg") as psycopg_mod:
        conn = MagicMock()
        psycopg_mod.connect.return_value.__enter__.return_value = conn
        with patch(
            "jll.legacy_users.LegacyUserRepository.get_user",
            return_value=MagicMock(display_name="Vedoucí"),
        ):
            with patch(
                "jll.flet_ui.viewmodels.setup.keyring.set_password",
                side_effect=KeyringError("boom"),
            ):
                with pytest.raises(RuntimeError, match="Credential store"):
                    vm.finish()
    assert not vm.state.config_path.exists()
    assert not vm.state.identity_path.exists()


def test_ved_missing_leaves_no_artefacts(tmp_path: Path) -> None:
    vm = _ready_vm(tmp_path, production=True)
    with patch("jll.flet_ui.viewmodels.setup.psycopg") as psycopg_mod:
        conn = MagicMock()
        psycopg_mod.connect.return_value.__enter__.return_value = conn
        with patch(
            "jll.legacy_users.LegacyUserRepository.get_user",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="VED"):
                vm.finish()
    assert not vm.state.config_path.exists()
    assert not vm.state.identity_path.exists()


def test_sup_store_failure_rolls_back_keyring_and_identity(tmp_path: Path) -> None:
    vm = _ready_vm(tmp_path, production=True)
    deleted: list[str] = []

    def _seed(**_kwargs) -> None:
        vm.state.identity_path.write_text('{"schema_version": 1, "users": []}', encoding="utf-8")

    with patch("jll.flet_ui.viewmodels.setup.psycopg") as psycopg_mod:
        conn = MagicMock()
        psycopg_mod.connect.return_value.__enter__.return_value = conn
        with patch(
            "jll.legacy_users.LegacyUserRepository.get_user",
            return_value=MagicMock(display_name="Vedoucí"),
        ):
            with patch(
                "jll.flet_ui.viewmodels.setup.keyring.set_password",
                return_value=None,
            ):
                with patch(
                    "jll.flet_ui.viewmodels.setup.keyring.get_password",
                    return_value="secret",
                ):
                    with patch(
                        "jll.flet_ui.viewmodels.setup.keyring.delete_password",
                        side_effect=lambda *_a, **_k: deleted.append("keyring"),
                    ):
                        with patch(
                            "jll.business_session.BusinessSession.seed_identity_for_setup",
                            side_effect=_seed,
                        ):
                            with patch(
                                "jll.sup_secret.SupSecretStore.set_password",
                                side_effect=RuntimeError("sup fail"),
                            ):
                                with pytest.raises(RuntimeError, match="SUP"):
                                    vm.finish()
    assert not vm.state.config_path.exists()
    assert not vm.state.identity_path.exists()
    assert "keyring" in deleted


def test_config_save_failure_rolls_back_staged_secrets(tmp_path: Path) -> None:
    vm = _ready_vm(tmp_path, production=True)
    deleted: list[str] = []

    def _seed(**_kwargs) -> None:
        vm.state.identity_path.write_text('{"schema_version": 1, "users": []}', encoding="utf-8")

    with patch("jll.flet_ui.viewmodels.setup.psycopg") as psycopg_mod:
        conn = MagicMock()
        psycopg_mod.connect.return_value.__enter__.return_value = conn
        with patch(
            "jll.legacy_users.LegacyUserRepository.get_user",
            return_value=MagicMock(display_name="Vedoucí"),
        ):
            with patch(
                "jll.flet_ui.viewmodels.setup.keyring.set_password",
                return_value=None,
            ):
                with patch(
                    "jll.flet_ui.viewmodels.setup.keyring.get_password",
                    return_value="secret",
                ):
                    with patch(
                        "jll.flet_ui.viewmodels.setup.keyring.delete_password",
                        side_effect=lambda *_a, **_k: deleted.append("keyring"),
                    ):
                        with patch(
                            "jll.business_session.BusinessSession.seed_identity_for_setup",
                            side_effect=_seed,
                        ):
                            with patch(
                                "jll.sup_secret.SupSecretStore.exists",
                                return_value=False,
                            ):
                                with patch(
                                    "jll.sup_secret.SupSecretStore.set_password",
                                    return_value=None,
                                ):
                                    with patch(
                                        "jll.sup_secret.SupSecretStore.clear",
                                        side_effect=lambda *_a, **_k: deleted.append(
                                            "sup"
                                        ),
                                    ):
                                        with patch(
                                            "jll.flet_ui.viewmodels.setup.save_config",
                                            side_effect=OSError("disk full"),
                                        ):
                                            with pytest.raises(
                                                RuntimeError, match="Konfiguraci"
                                            ):
                                                vm.finish()
    assert not vm.state.config_path.exists()
    assert not vm.state.identity_path.exists()
    assert "keyring" in deleted
    assert "sup" in deleted
