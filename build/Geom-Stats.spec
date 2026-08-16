# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Geom-Stats (console onefile).
# Python helpers + matplotlib/tk + GauIRC2xyz are bundled.
# Editable Lib/settings.ini and gview tcl are copied beside the exe at first run.

import os

# SPECPATH is injected by PyInstaller as the directory containing this .spec
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
LIB_DIR = os.path.join(PROJECT_ROOT, "Lib")
ENTRY = os.path.join(PROJECT_ROOT, "Geom-Stats.py")
ICON = os.path.join(LIB_DIR, "geom-stats-app-icon.ico")

a = Analysis(
    [ENTRY],
    pathex=[PROJECT_ROOT, LIB_DIR],
    binaries=[],
    datas=[
        (os.path.join(LIB_DIR, "GauIRC2xyz.exe"), "Lib"),
        (os.path.join(LIB_DIR, "settings.ini"), "Lib"),
        (os.path.join(LIB_DIR, "gview_element_colors.tcl"), "Lib"),
    ],
    hiddenimports=[
        "app_paths",
        "plot_gnuplot",
        "vmd_viewer",
        "mol_preview",
        "qc_out_to_xyz",
        "xyz2fakeg",
        "configparser",
        "argparse",
        "numpy",
        "tkinter",
        "tkinter.ttk",
        "matplotlib",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends.backend_agg",
        "mpl_toolkits.mplot3d",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "sphinx",
        "lxml",
    ],
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
