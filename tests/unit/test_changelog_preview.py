"""Unit tests: changelog preview parser."""

from __future__ import annotations

from jll.changelog_preview import parse_changelog


def test_parse_changelog_skips_empty_unreleased_and_keeps_summaries() -> None:
    text = """# Changelog

## [Unreleased]

## [0.5.0] – 2026-09-08

HOME overview:

- first bullet
- second bullet

### Added

- ignored after summary

## [0.4.4] – 2026-09-08

Typography:

- role_style
"""
    entries = parse_changelog(text, limit=3)
    assert len(entries) == 2
    assert entries[0].version == "0.5.0"
    assert entries[0].date == "2026-09-08"
    assert "first bullet" in entries[0].summary_lines
    assert entries[1].version == "0.4.4"
