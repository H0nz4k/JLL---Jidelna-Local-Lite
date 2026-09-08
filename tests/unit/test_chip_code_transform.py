"""Unit tests: IKonverze / Pridat00 reader chip transform."""

from __future__ import annotations

import pytest

from jll.chip_code_transform import (
    apply_ikonverze,
    transform_reader_chip_code,
)
from jll.config import LabConfig


def _lab(**kwargs) -> LabConfig:
    base = dict(
        site_name="DEMO LAB",
        site_id="DEMO",
        instance_id="DEMO-LAB01",
        allowed_categories=frozenset({"KAT1"}),
        host="127.0.0.1",
        port=5433,
        database="jll_test",
        user="postgres",
        environment="lab",
        expected_system_identifier="1000000000000000001",
        business_timezone="Europe/Prague",
        strict_config_lock=True,
    )
    base.update(kwargs)
    return LabConfig(**base)


def test_ikonverze_example_from_legacy_doc() -> None:
    assert apply_ikonverze("0000004900327C3D") == "12903371"


def test_full_pipeline_ikonverze_and_pridat00() -> None:
    assert (
        transform_reader_chip_code(
            "0000004900327C3D",
            ikonverze=True,
            pridat00=True,
        )
        == "0000001290337100"
    )


def test_ikonverze_only_pads_without_trailing_00() -> None:
    assert (
        transform_reader_chip_code(
            "0000004900327C3D",
            ikonverze=True,
            pridat00=False,
        )
        == "0000000012903371"
    )


def test_pridat00_only_appends_and_pads() -> None:
    assert (
        transform_reader_chip_code("12903371", ikonverze=False, pridat00=True)
        == "0000001290337100"
    )


def test_no_flags_only_pads() -> None:
    assert transform_reader_chip_code("ABCD", ikonverze=False, pridat00=False) == (
        "000000000000ABCD"
    )


def test_lab_config_helper_uses_flags() -> None:
    cfg = _lab(reader_ikonverze=True, reader_pridat00=True)
    assert cfg.transform_chip_from_reader("0000004900327C3D") == "0000001290337100"


def test_invalid_empty_fail_closed() -> None:
    with pytest.raises(ValueError):
        transform_reader_chip_code("   ", ikonverze=True, pridat00=False)
