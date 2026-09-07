"""Unit testy diner/chip write gates a legacy PIN."""

from __future__ import annotations

import pytest

from jll.diner_models import FORBIDDEN_PERSONAL_EDIT_FIELDS, PERSONAL_EDIT_FIELDS
from jll.legacy_pin import legacy_get_pin
from jll.read_models import chip_status_label
from jll.write_gates import (
    CHIP_WRITE_GATES,
    DINER_WRITE_GATES,
    ContractStatus,
    WriteContractNotProven,
    require_proven,
)


def test_diner_gates_proven_for_create_and_edit() -> None:
    assert DINER_WRITE_GATES["create"].status is ContractStatus.PROVEN
    assert DINER_WRITE_GATES["edit_personal"].status is ContractStatus.PROVEN
    assert DINER_WRITE_GATES["category_change"].status is ContractStatus.PARTIAL
    require_proven(DINER_WRITE_GATES, "create")
    require_proven(DINER_WRITE_GATES, "edit_personal")
    with pytest.raises(WriteContractNotProven):
        require_proven(DINER_WRITE_GATES, "category_change")


def test_chip_gates_matrix_0_3_0() -> None:
    assert CHIP_WRITE_GATES["assign"].status is ContractStatus.PROVEN
    assert CHIP_WRITE_GATES["block"].status is ContractStatus.PROVEN
    assert CHIP_WRITE_GATES["lost"].status is ContractStatus.PROVEN
    assert CHIP_WRITE_GATES["unblock"].status is ContractStatus.PROVEN
    assert CHIP_WRITE_GATES["return"].status is ContractStatus.BLOCKED
    assert CHIP_WRITE_GATES["transfer"].status is ContractStatus.BLOCKED
    require_proven(CHIP_WRITE_GATES, "assign")
    with pytest.raises(WriteContractNotProven):
        require_proven(CHIP_WRITE_GATES, "return")


def test_personal_edit_whitelist_excludes_sensitive_fields() -> None:
    assert "jmeno" in PERSONAL_EDIT_FIELDS
    assert "trida" in PERSONAL_EDIT_FIELDS
    assert "kategorie" not in PERSONAL_EDIT_FIELDS
    for field in (
        "evidcislo",
        "kategorie",
        "cip",
        "pin",
        "preplatekmm",
        "zpusobplatby",
    ):
        assert field in FORBIDDEN_PERSONAL_EDIT_FIELDS


def test_legacy_get_pin_parity_sample() -> None:
    pin = legacy_get_pin("NOVÁK JAN", "", 29)
    assert len(pin) == 4
    assert pin.isdigit()
    assert int(pin) >= 1000


def test_chip_status_label_includes_free() -> None:
    assert chip_status_label("V") == "Volný"
    assert chip_status_label("P") == "Přidělen"
