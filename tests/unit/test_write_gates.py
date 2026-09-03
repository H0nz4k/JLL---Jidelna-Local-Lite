from __future__ import annotations

import pytest

from jll.write_gates import (
    CHIP_WRITE_GATES,
    DINER_WRITE_GATES,
    ContractStatus,
    WriteContractNotProven,
    require_proven,
)


def test_phase_3a_chip_write_gates_are_fail_closed() -> None:
    assert CHIP_WRITE_GATES["assign"].status is ContractStatus.PARTIAL
    assert {
        operation
        for operation, gate in CHIP_WRITE_GATES.items()
        if gate.status is ContractStatus.BLOCKED
    } == {"return", "block", "lost", "unblock", "transfer"}
    assert not any(gate.enabled for gate in CHIP_WRITE_GATES.values())


def test_phase_3a_diner_write_gates_are_fail_closed() -> None:
    assert DINER_WRITE_GATES["create"].status is ContractStatus.PARTIAL
    assert DINER_WRITE_GATES["edit_personal"].status is ContractStatus.BLOCKED
    assert DINER_WRITE_GATES["category_change"].status is ContractStatus.PARTIAL
    assert not any(gate.enabled for gate in DINER_WRITE_GATES.values())


def test_non_proven_gate_cannot_be_used_as_write_authorization() -> None:
    with pytest.raises(WriteContractNotProven, match="PARTIAL"):
        require_proven(CHIP_WRITE_GATES, "assign")
    with pytest.raises(WriteContractNotProven, match="BLOCKED"):
        require_proven(DINER_WRITE_GATES, "edit_personal")
