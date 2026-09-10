"""Version metadata consistency for Windows release artefacts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_windows_version_metadata_matches_project_version() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    assert match is not None
    version = match.group(1)
    assert version == "0.6.0"

    version_info = (ROOT / "packaging/windows/version_info.txt").read_text(
        encoding="utf-8"
    )
    assert "StringStruct('ProductName', 'JLL')" in version_info
    assert "StringStruct('CompanyName', 'Altisima')" in version_info
    assert "StringStruct('ProductVersion', '0.6.0')" in version_info
    assert "StringStruct('FileVersion', '0.6.0.0')" in version_info
    assert "JLL \\u2013 J\\u00eddelna Lokal Lite" in version_info
    assert "Copyright \\u00a9 2026 Altisima" in version_info
    assert "filevers=(0, 6, 0, 0)" in version_info

    iss = (ROOT / "packaging/windows/JidelnaLocalLite.iss").read_text(encoding="utf-8")
    assert '#define MyAppVersion "0.6.0"' in iss
    assert '#define MyFileVersion "0.6.0.0"' in iss
    assert '#define MyProductName "JLL"' in iss
    assert '#define MyCompany "Altisima"' in iss
    assert "VersionInfoProductName={#MyProductName}" in iss
    assert "JLL – Jídelna Lokal Lite Setup" in iss or "JLL \\u2013" in iss.encode(
        "unicode_escape"
    ).decode()

    spec = (ROOT / "packaging/windows/JidelnaLocalLite.spec").read_text(encoding="utf-8")
    assert 'version=str(Path(SPECPATH).resolve() / "version_info.txt")' in spec
