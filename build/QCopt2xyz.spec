# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Lib/QCopt2xyz.exe (console onefile).
# Built from Lib/qc_out_to_xyz.py — place the exe beside other Lib helpers.

import os

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ENTRY = os.path.join(PROJECT_ROOT, "Lib", "qc_out_to_xyz.py")
LIB_DIR = os.path.join(PROJECT_ROOT, "Lib")

a = Analysis(
    [ENTRY],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="QCopt2xyz",
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
)
