from __future__ import annotations

import pytest

from jll.write_gates import (
    CHIP_WRITE_GATES,
    DINER_WRITE_GATES,
    ContractStatus,
    WriteContractNotProven,
    require_proven,
)


def test_chip_write_gates_fail_closed_for_unproven() -> None:
    assert CHIP_WRITE_GATES["return"].status is ContractStatus.BLOCKED
    assert CHIP_WRITE_GATES["transfer"].status is ContractStatus.BLOCKED
    with pytest.raises(WriteContractNotProven, match="bezpečnostně blokována"):
        require_proven(CHIP_WRITE_GATES, "return")


def test_diner_category_change_remains_partial() -> None:
    assert DINER_WRITE_GATES["category_change"].status is ContractStatus.PARTIAL
    with pytest.raises(WriteContractNotProven):
        require_proven(DINER_WRITE_GATES, "category_change")


def test_proven_gates_are_enabled() -> None:
    assert DINER_WRITE_GATES["create"].enabled
    assert DINER_WRITE_GATES["edit_personal"].enabled
    assert CHIP_WRITE_GATES["assign"].enabled
