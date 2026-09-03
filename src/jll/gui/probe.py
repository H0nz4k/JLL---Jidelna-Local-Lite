from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_lab_config
from ..policy import Permission, SessionPolicy
from ..read_service import OrderReadService


def main() -> int:
    parser = argparse.ArgumentParser(description="Ověření JLL LAB GUI targetu")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = load_lab_config(args.config)
    service = OrderReadService(
        config.connection_factory,
        config.order_settings,
        SessionPolicy(
            "LAB preflight",
            config.allowed_categories,
            frozenset({Permission.DINERS_VIEW, Permission.ORDERS_VIEW}),
        ),
        search_limit=config.search_limit,
    )
    identity = service.verify_lab()
    print(
        f"LAB guard OK: {identity.server_address}:{identity.server_port}/"
        f"{identity.database_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
