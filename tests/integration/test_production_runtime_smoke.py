"""Production-like runtime smoke against disposable local DB."""

from __future__ import annotations

import pytest

from jll.business_session import BusinessSession
from jll.config import JllConfig
from jll.identity_store import IdentityStore
from jll.orders.errors import ErrorCode, OrderBusinessError
from jll.payment_history_service import PaymentHistoryService
from jll.policy import Permission, SessionPolicy
from jll.read_service import OrderReadService
from jll.sup_secret import SupSecretStore

from conftest import LabDatabase
from test_orders_postgres import CATEGORY, EVIDCISLO, TARGET

pytestmark = pytest.mark.integration


def _production_config(database: LabDatabase) -> JllConfig:
    """Semanticky production config nad disposable loopback DB (žádný zákazník)."""

    return JllConfig(
        site_name="PROD SMOKE",
        site_id="PRODSMOKE",
        instance_id="PROD-SMOKE-01",
        allowed_categories=frozenset({CATEGORY}),
        host=database.host,
        port=database.port,
        database=database.name,
        user=database.user,
        environment="production",
        expected_system_identifier=database.system_identifier,
        business_timezone="Europe/Prague",
        strict_config_lock=True,
        search_limit=30,
    )


def test_production_runtime_read_path_smoke(lab_database: LabDatabase, tmp_path) -> None:
    """environment=production nesmí failnout LAB_GUARD_FAILED na read cestách."""

    config = _production_config(lab_database)
    assert config.environment == "production"
    settings = config.order_settings
    assert settings.environment == "production"

    policy = SessionPolicy(
        "prod-smoke",
        frozenset({CATEGORY}),
        frozenset(
            {
                Permission.DINERS_VIEW,
                Permission.ORDERS_VIEW,
                Permission.ORDERS_CHANGE,
                Permission.PAYMENTS_VIEW,
                Permission.REPORTS_VIEW,
            }
        ),
    )
    read = OrderReadService(lab_database.connect, settings, policy)

    try:
        diag = read.verify_runtime()
        assert diag.database_name == lab_database.name
        assert diag.system_identifier == lab_database.system_identifier
        today = read.server_today()
        assert today is not None
        calendar = read.load_business_calendar()
        assert calendar is not None
        diners = read.list_diners()
        assert isinstance(diners, list)
        snapshot = read.load_diner_day_snapshot(EVIDCISLO, TARGET)
        assert snapshot.day.diner.evidcislo == EVIDCISLO
        overview = read.load_home_today_overview(
            workplace_name=config.site_name,
            organization_name=config.site_name,
        )
        assert overview is not None
    except OrderBusinessError as exc:
        if exc.code is ErrorCode.LAB_GUARD_FAILED:
            pytest.fail(
                "Production runtime read selhal LAB_GUARD_FAILED — "
                "read path stále používá LAB-only guard."
            )
        raise

    identity = IdentityStore(tmp_path / "users.json")
    sup = SupSecretStore("PROD-SMOKE-01", fallback_dir=tmp_path / "secrets")
    business = BusinessSession(
        config=config,
        identity_store=identity,
        connection_factory=lab_database.connect,
        sup_store=sup,
    )
    business.seed_identity_for_setup(ved_display_name="Vedoucí")
    business.bootstrap_ved()
    assert business.current_policy() is not None

    payments = PaymentHistoryService(
        lab_database.connect,
        lambda: policy,
        settings,
    )
    try:
        page = payments.list_for_diner(EVIDCISLO, limit=5)
        assert page is not None
    except OrderBusinessError as exc:
        if exc.code is ErrorCode.LAB_GUARD_FAILED:
            pytest.fail("PaymentHistoryService production read hit LAB_GUARD_FAILED.")
        raise
