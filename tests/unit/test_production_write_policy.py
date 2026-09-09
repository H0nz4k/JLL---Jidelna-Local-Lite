from __future__ import annotations

from jll.write_gates import (
    CHIP_WRITE_GATES,
    ContractStatus,
    DINER_WRITE_GATES,
    PAYMENT_WRITE_GATES,
    PRODUCTION_DISABLED_MESSAGE,
    SERVING_WRITE_GATES,
    WriteContractNotProven,
    effective_write_gate,
    require_environment_write,
)


def test_lab_keeps_lab_proven_gates() -> None:
    gate = effective_write_gate(
        CHIP_WRITE_GATES, "assign", environment="lab", domain="chip"
    )
    assert gate.status is ContractStatus.PROVEN


def test_production_blocks_lab_proven_chip_writes() -> None:
    gate = effective_write_gate(
        CHIP_WRITE_GATES, "assign", environment="production", domain="chip"
    )
    assert gate.status is ContractStatus.BLOCKED
    try:
        require_environment_write(
            CHIP_WRITE_GATES,
            "assign",
            environment="production",
            domain="chip",
        )
        assert False, "expected WriteContractNotProven"
    except WriteContractNotProven as exc:
        assert str(exc) == PRODUCTION_DISABLED_MESSAGE


def test_production_blocks_serving_and_diner_and_payment() -> None:
    for gates, op, domain in (
        (SERVING_WRITE_GATES, "record_pickup", "serving"),
        (DINER_WRITE_GATES, "create", "diner"),
        (PAYMENT_WRITE_GATES, "manual_payment", "payment"),
    ):
        gate = effective_write_gate(gates, op, environment="production", domain=domain)
        assert gate.status is ContractStatus.BLOCKED
