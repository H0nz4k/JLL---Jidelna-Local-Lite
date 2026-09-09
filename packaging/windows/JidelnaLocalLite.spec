# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for JidelnaLocalLite (PySide6 GUI).

Entry: python -m jll → jll.__main__ → jll.gui.app:main
Flet is excluded from the production bundle.
reportlab is collected when installed (pdf/production extra).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"

datas: list = []
binaries: list = []
hiddenimports: list[str] = [
    "jll",
    "jll.__main__",
    "jll.gui.app",
    "jll.paths",
    "jll.runtime_paths",
    "keyring.backends",
    "keyring.backends.Windows",
]

for package in ("PySide6", "shiboken6"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

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
        "flet",
        "flet_core",
        "flet_desktop",
        "flet_runtime",
        "jll.flet_ui",
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
