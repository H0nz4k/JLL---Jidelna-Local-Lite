# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for JidelnaLocalLite (Flet production desktop).

Entry: python -m jll → jll.flet_ui.app:main
PySide6 GUI remains in source as reference/legacy and is excluded from the bundle.
reportlab is collected when installed (pdf/production extra).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

block_cipher = None

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"

datas: list = []
binaries: list = []
hiddenimports: list[str] = [
    "jll",
    "jll.__main__",
    "jll.flet_ui",
    "jll.flet_ui.app",
    "jll.paths",
    "jll.runtime_paths",
    "keyring.backends",
    "keyring.backends.Windows",
]

for package in ("flet", "flet_desktop", "flet_core"):
    if importlib.util.find_spec(package) is not None:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden

# Keep importlib.metadata version() working in the frozen EXE.
datas += copy_metadata("jidelna-local-lite")

if importlib.util.find_spec("reportlab") is not None:
    hiddenimports += collect_submodules("reportlab")
    rl_datas, rl_binaries, rl_hidden = collect_all("reportlab")
    datas += rl_datas
    binaries += rl_binaries
    hiddenimports += rl_hidden

a = Analysis(
    [str(Path(SPECPATH).resolve() / "run_jll.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "shiboken6",
        "jll.gui",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JidelnaLocalLite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(Path(SPECPATH).resolve() / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JidelnaLocalLite",
)
