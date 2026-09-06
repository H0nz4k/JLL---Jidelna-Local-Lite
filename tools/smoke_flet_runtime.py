"""Headless Flet runtime smoke against LAB config (no GUI window)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jll.business_session import BusinessSession
from jll.chip_reader import build_chip_reader
from jll.config import load_lab_config
from jll.identity_store import IdentityStore
from jll.read_service import OrderReadService
from jll.sup_secret import SupSecretStore


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config" / "lab.json"
    identity_path = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "config" / "users.lab.json"
    )
    if not config_path.is_file():
        print("SKIP: missing config")
        return 0
    config = load_lab_config(config_path)
    identity = IdentityStore(identity_path)
    if not identity.exists:
        print("SKIP: missing identity store – run Flet setup first")
        return 0
    pool = config.create_pool()
    try:
        business = BusinessSession(
            config=config,
            identity_store=identity,
            connection_factory=pool.connection,
            sup_store=SupSecretStore(
                config.instance_id, fallback_dir=config_path.parent / "secrets"
            ),
        )
        ved = business.bootstrap_ved()
        assert ved.code.upper() == "VED"
        read = OrderReadService(
            pool.connection,
            config.order_settings,
            business.current_policy,
            search_limit=config.search_limit,
        )
        diag = read.verify_lab()
        results = read.search_diners("al")
        reader = build_chip_reader(config.reader_port)
        print(
            "SMOKE OK",
            f"actor={business.current_actor().short_code}",
            f"db={diag.database_name}",
            f"search={len(results)}",
            f"reader={type(reader).__name__}",
        )
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
