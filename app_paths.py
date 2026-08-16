#!/usr/bin/env python3
"""User-facing vs bundled resource paths for Geom-Stats (source and frozen)."""

from __future__ import annotations

import sys
from pathlib import Path

_EDITABLE_LIB_FILES = ("settings.ini", "gview_element_colors.tcl")


def user_app_dir() -> Path:
    """Directory beside the exe (frozen) or project/release root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    here = Path(__file__).resolve().parent
    if here.name.lower() == "lib":
        return here.parent
    if here.name.lower() == "source" and (here.parent / "Lib").is_dir():
        return here.parent
    return here


def user_lib_dir() -> Path:
    return user_app_dir() / "Lib"


def bundled_dir() -> Path:
    """PyInstaller extract dir, else the source Lib/ folder."""
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            return Path(mei)
    return user_lib_dir()


def bundled_lib_dir() -> Path:
    if getattr(sys, "frozen", False):
        candidate = bundled_dir() / "Lib"
        if candidate.is_dir():
            return candidate
        return bundled_dir()
    return user_lib_dir()


def enable_lib_module_path() -> None:
    """Allow `import qc_out_to_xyz` from Lib/ in source runs."""
    candidates = [user_lib_dir()]
    if getattr(sys, "frozen", False):
        candidates.insert(0, bundled_lib_dir())
        candidates.insert(0, bundled_dir())
    else:
        candidates.insert(0, Path(__file__).resolve().parent / "Lib")
    for path in candidates:
        if path.is_dir():
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)


def bundled_native(name: str) -> Path:
    """Locate a native extra such as GauIRC2xyz.exe."""
    for folder in (bundled_lib_dir(), bundled_dir(), user_lib_dir()):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return user_lib_dir() / name


def ensure_editable_lib() -> Path:
    """Copy bundled defaults into exe-side Lib/ when missing (do not overwrite)."""
    dest = user_lib_dir()
    dest.mkdir(parents=True, exist_ok=True)
    src_lib = bundled_lib_dir()
    if src_lib.resolve() == dest.resolve():
        return dest
    for name in _EDITABLE_LIB_FILES:
        target = dest / name
        if target.exists():
            continue
        source = src_lib / name
        if source.is_file():
            target.write_bytes(source.read_bytes())
    return dest
