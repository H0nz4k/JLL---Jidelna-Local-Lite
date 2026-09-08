"""Náhled verzí z kořenového CHANGELOG.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VERSION_HEADING = re.compile(
    r"^## \[([^\]]+)\](?:\s*[–—-]\s*(\d{4}-\d{2}-\d{2}))?\s*$"
)
_BULLET = re.compile(r"^[-*]\s+(.+)$")


@dataclass(frozen=True, slots=True)
class ChangelogEntry:
    version: str
    date: str | None
    summary_lines: tuple[str, ...]

    @property
    def title(self) -> str:
        if self.date:
            return f"{self.version} · {self.date}"
        return self.version


def default_changelog_path() -> Path:
    """Repo root CHANGELOG.md (src/jll → parents[2])."""

    return Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def parse_changelog(
    text: str,
    *,
    limit: int = 6,
    skip_unreleased_empty: bool = True,
) -> tuple[ChangelogEntry, ...]:
    """Vrátí nejnovější verze (shora CHANGELOGu) s krátkým souhrnem."""

    entries: list[ChangelogEntry] = []
    current_version: str | None = None
    current_date: str | None = None
    summary: list[str] = []
    collecting_summary = False

    def _flush() -> None:
        nonlocal current_version, current_date, summary, collecting_summary
        if current_version is None:
            return
        if (
            skip_unreleased_empty
            and current_version.casefold() == "unreleased"
            and not summary
        ):
            current_version = None
            current_date = None
            summary = []
            collecting_summary = False
            return
        entries.append(
            ChangelogEntry(
                version=current_version,
                date=current_date,
                summary_lines=tuple(summary[:6]),
            )
        )
        current_version = None
        current_date = None
        summary = []
        collecting_summary = False

    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _VERSION_HEADING.match(line)
        if heading:
            _flush()
            if len(entries) >= limit:
                break
            current_version = heading.group(1).strip()
            current_date = heading.group(2)
            collecting_summary = True
            continue
        if current_version is None or not collecting_summary:
            continue
        if line.startswith("### "):
            # Po souhrnném bloku bereme jen úvodní odrážky / odstavec.
            if summary:
                collecting_summary = False
            continue
        bullet = _BULLET.match(line)
        if bullet:
            summary.append(bullet.group(1).strip())
            continue
        if line and not line.startswith("#") and not summary:
            summary.append(line.strip())

    if len(entries) < limit:
        _flush()
    return tuple(entries[:limit])


def load_changelog_preview(
    path: Path | None = None,
    *,
    limit: int = 6,
) -> tuple[ChangelogEntry, ...]:
    target = path or default_changelog_path()
    if not target.is_file():
        return ()
    return parse_changelog(target.read_text(encoding="utf-8"), limit=limit)
