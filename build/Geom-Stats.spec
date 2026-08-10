# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Geom-Stats (console onefile).
# Lib/ stays external beside the exe — do not bundle it as datas.

import os

# SPECPATH is injected by PyInstaller as the directory containing this .spec
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ENTRY = os.path.join(PROJECT_ROOT, "Geom-Stats.py")
ICON = os.path.join(PROJECT_ROOT, "Lib", "geom-stats-app-icon.ico")

a = Analysis(
    [ENTRY],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["configparser", "argparse"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Geom-Stats",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
