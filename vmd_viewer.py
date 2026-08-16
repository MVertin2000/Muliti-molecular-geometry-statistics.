#!/usr/bin/env python3
"""Launch local VMD to visualize Geom-Stats structure / trajectory files.

Mirrors plot_gnuplot.py: settings ini + callable API + standalone CLI.

    python vmd_viewer.py --structure traj.xyz
    python vmd_viewer.py --structure job.out
"""

from __future__ import annotations

import argparse
import configparser
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from app_paths import enable_lib_module_path, user_app_dir, user_lib_dir

VERSION = "1.6.0"
APP_DIR = user_app_dir()
LIB_DIR = user_lib_dir()
DEFAULT_SETTINGS = LIB_DIR / "settings.ini"

enable_lib_module_path()

DISPLAY_STYLES = ("Lines", "CPK", "Licorice", "VDW")


@dataclass
class VmdSettings:
    executable: str
    extra_args: list[str]
    temp_directory: str
    style: str
    lines_thickness: float
    cpk_sphere_scale: float
    cpk_bond_radius: float
    cpk_sphere_resolution: int
    cpk_bond_resolution: int
    licorice_bond_radius: float
    licorice_sphere_resolution: int
    licorice_bond_resolution: int
    vdw_sphere_scale: float
    vdw_sphere_resolution: int
    use_gview_element: bool
    gview_palette: str


def tcl_quote(path: Path | str) -> str:
    """Quote a filesystem path for Tcl (escape backslashes and braces)."""
    text = str(path)
    text = text.replace("\\", "/")
    text = text.replace("{", "\\{").replace("}", "\\}")
    return "{" + text + "}"


def parse_bool(value: str, *, default: bool = False) -> bool:
    text = (value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_style(raw: str) -> str:
    style = (raw or "CPK").strip()
    lookup = {name.lower(): name for name in DISPLAY_STYLES}
    # Accept common aliases
    lookup["line"] = "Lines"
    lookup["lines"] = "Lines"
    lookup["cpk"] = "CPK"
    lookup["licorice"] = "Licorice"
    lookup["vdw"] = "VDW"
    key = style.lower()
    if key not in lookup:
        raise ValueError(
            f"Unsupported VMD display style {raw!r}. "
            f"Choose one of: {', '.join(DISPLAY_STYLES)}."
        )
    return lookup[key]


def load_vmd_settings(path: Path) -> VmdSettings:
    if not path.exists():
        raise FileNotFoundError(f"VMD settings file not found: {path}")

    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise ValueError(f"Failed to read VMD settings: {path}")

    vmd = parser["vmd"] if parser.has_section("vmd") else {}
    launch = parser["launch"] if parser.has_section("launch") else {}
    temp = parser["temp"] if parser.has_section("temp") else {}
    display = parser["display"] if parser.has_section("display") else {}
    color = parser["color"] if parser.has_section("color") else {}

    extra = launch.get("extra_args", "-nt").strip()
    extra_args = [part for part in extra.split() if part] if extra else []

    return VmdSettings(
        executable=(vmd.get("executable") or "vmd.exe").strip(),
        extra_args=extra_args,
        temp_directory=(temp.get("directory") or "").strip(),
        style=normalize_style(display.get("style", "CPK")),
        lines_thickness=float(display.get("lines_thickness", "1.0")),
        cpk_sphere_scale=float(display.get("cpk_sphere_scale", "1.0")),
        cpk_bond_radius=float(display.get("cpk_bond_radius", "0.3")),
        cpk_sphere_resolution=int(display.get("cpk_sphere_resolution", "12")),
        cpk_bond_resolution=int(display.get("cpk_bond_resolution", "12")),
        licorice_bond_radius=float(display.get("licorice_bond_radius", "0.3")),
        licorice_sphere_resolution=int(display.get("licorice_sphere_resolution", "12")),
        licorice_bond_resolution=int(display.get("licorice_bond_resolution", "12")),
        vdw_sphere_scale=float(display.get("vdw_sphere_scale", "1.0")),
        vdw_sphere_resolution=int(display.get("vdw_sphere_resolution", "12")),
        use_gview_element=parse_bool(color.get("use_gview_element", "yes"), default=True),
        gview_palette=(color.get("gview_palette") or "gview_element_colors.tcl").strip(),
    )


def resolve_vmd_executable(raw: str, settings_path: Path) -> Path:
    candidate = Path(raw).expanduser()
    search_roots = [
        settings_path.parent,
        settings_path.parent.parent,
        Path.cwd(),
    ]

    checked: list[Path] = []
    if candidate.is_absolute():
        checked.append(candidate)
    else:
        for root in search_roots:
            checked.append((root / candidate).resolve())

    for path in checked:
        if path.is_file():
            return path
        if path.is_dir():
            for name in ("vmd.exe", "vmd"):
                exe = path / name
                if exe.is_file():
                    return exe

    which = shutil.which(raw)
    if which:
        return Path(which).resolve()

    raise FileNotFoundError(
        f"VMD executable not found from setting {raw!r}. "
        f"Edit {settings_path} [vmd] executable."
    )


def resolve_palette_path(raw: str, settings_path: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    beside_ini = (settings_path.parent / candidate).resolve()
    if beside_ini.is_file():
        return beside_ini
    raise FileNotFoundError(
        f"GaussView Element palette script not found: {raw!r}. "
        f"Expected beside settings as {beside_ini}."
    )


def run_qcopt2xyz(structure_path: Path, output_xyz: Path) -> None:
    """Convert ORCA/Gaussian opt output → XYZ via bundled qc_out_to_xyz."""
    try:
        import qc_out_to_xyz
    except ImportError as exc:
        raise FileNotFoundError(
            "QC→XYZ converter module qc_out_to_xyz was not found. "
            "Keep Lib/qc_out_to_xyz.py beside settings.ini when running from source."
        ) from exc
    output_xyz.parent.mkdir(parents=True, exist_ok=True)
    try:
        qc_out_to_xyz.convert_qc_output_to_xyz(structure_path, output_xyz)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise RuntimeError(f"QC→XYZ conversion failed: {exc}") from exc
    if not output_xyz.exists():
        raise RuntimeError("qc_out_to_xyz did not create the expected XYZ file.")


def detect_structure_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xyz":
        return "xyz"
    if suffix == ".pdb":
        return "pdb"
    if suffix in {".out", ".log"}:
        return "qc"
    raise ValueError(
        f"Unsupported structure for VMD: {path.name}. "
        "Use .xyz, .pdb, ORCA .out, or Gaussian .log/.out."
    )


def prepare_vmd_structure(
    structure_path: Path,
    *,
    temp_directory: str,
) -> tuple[Path, bool]:
    """Return (path_for_vmd, delete_after_load)."""
    structure_path = structure_path.resolve()
    kind = detect_structure_kind(structure_path)
    if kind in {"xyz", "pdb"}:
        return structure_path, False

    if temp_directory:
        temp_root = Path(temp_directory).expanduser()
        if not temp_root.is_absolute():
            temp_root = (APP_DIR / temp_root).resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_root = Path(tempfile.gettempdir())

    temp_xyz = temp_root / f"geom_stats_vmd_{uuid.uuid4().hex}.xyz"
    run_qcopt2xyz(structure_path, temp_xyz)
    return temp_xyz, True


def representation_tcl(settings: VmdSettings) -> str:
    style = settings.style
    if style == "Lines":
        return f"Lines {settings.lines_thickness:g}"
    if style == "CPK":
        return (
            f"CPK {settings.cpk_sphere_scale:g} {settings.cpk_bond_radius:g} "
            f"{settings.cpk_sphere_resolution} {settings.cpk_bond_resolution}"
        )
    if style == "Licorice":
        return (
            f"Licorice {settings.licorice_bond_radius:g} "
            f"{settings.licorice_sphere_resolution} {settings.licorice_bond_resolution}"
        )
    if style == "VDW":
        return f"VDW {settings.vdw_sphere_scale:g} {settings.vdw_sphere_resolution}"
    raise ValueError(f"Unsupported display style: {style}")


def build_vmd_tcl(
    structure_path: Path,
    settings: VmdSettings,
    *,
    delete_after_load: bool,
    start_frame_1based: int | None,
    settings_path: Path,
    delete_self: bool = True,
) -> str:
    path_tcl = tcl_quote(structure_path)
    suffix = structure_path.suffix.lower().lstrip(".")
    file_type = "pdb" if suffix == "pdb" else "xyz"
    rep = representation_tcl(settings)

    lines = [
        f"# Auto-generated by vmd_viewer.py (Version {VERSION})",
        f"# Display style: {settings.style}",
        f"# Color: {'gview+Element' if settings.use_gview_element else 'VMD default'}",
        f"mol new {path_tcl} type {file_type} waitfor all",
    ]
    if delete_after_load:
        # Coordinates are already in memory after waitfor all.
        lines.append(f"file delete -force -- {path_tcl}")

    # Replace the default representation with the configured style.
    lines.append(f"mol modstyle 0 top {rep}")

    if settings.use_gview_element:
        palette = resolve_palette_path(settings.gview_palette, settings_path)
        lines.append(f"source {tcl_quote(palette)}")
        lines.append("mol modcolor 0 top Element")
    else:
        lines.append("mol modcolor 0 top Name")

    if start_frame_1based is not None and start_frame_1based >= 1:
        zero_based = start_frame_1based - 1
        lines.append(f"animate goto {zero_based}")
    lines.append("display resetview")
    if delete_self:
        # Remove this script after VMD has finished sourcing it.
        lines.append("catch {file delete -force -- [info script]}")
    lines.append("")
    return "\n".join(lines)


def make_tcl_path_beside_structure(structure_path: Path) -> Path:
    """Place temporary Tcl next to the loaded structure file (not system temp)."""
    return structure_path.parent / (
        f"geom_stats_vmd_{structure_path.stem}_{uuid.uuid4().hex[:8]}.tcl"
    )


def write_vmd_tcl(tcl_text: str, tcl_path: Path) -> Path:
    tcl_path = tcl_path.resolve()
    tcl_path.parent.mkdir(parents=True, exist_ok=True)
    tcl_path.write_text(tcl_text, encoding="utf-8", newline="\n")
    return tcl_path


def schedule_tcl_cleanup(tcl_path: Path, *, delay_s: float = 2.0) -> None:
    """Fallback cleanup if the script could not delete itself."""

    def _cleanup() -> None:
        try:
            tcl_path.unlink(missing_ok=True)
        except OSError:
            pass

    timer = threading.Timer(delay_s, _cleanup)
    timer.daemon = True
    timer.start()


def launch_vmd(vmd_exe: Path, tcl_path: Path, extra_args: list[str]) -> subprocess.Popen:
    command = [str(vmd_exe), *extra_args, "-e", str(tcl_path)]
    # Detach on Windows so closing the Geom-Stats console does not EOF-exit VMD.
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    return subprocess.Popen(
        command,
        cwd=str(vmd_exe.parent),
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def visualize_with_vmd(
    structure_path: Path,
    settings_path: Path | None = None,
    *,
    start_frame: int | None = None,
    keep_tcl: bool = False,
) -> Path:
    """Prepare structure (convert QC if needed), write Tcl, launch VMD.

    Tcl is written beside the loaded structure file. After VMD starts
    successfully it is removed (script self-delete + delayed fallback).
    Temporary XYZ from ORCA/Gaussian conversion is deleted by the Tcl
    script immediately after VMD finishes loading it.
    """
    settings_path = (settings_path or DEFAULT_SETTINGS).resolve()
    settings = load_vmd_settings(settings_path)
    vmd_exe = resolve_vmd_executable(settings.executable, settings_path)

    structure_path = structure_path.resolve()
    if not structure_path.exists():
        raise FileNotFoundError(f"Structure file not found: {structure_path}")

    vmd_structure, delete_after_load = prepare_vmd_structure(
        structure_path,
        temp_directory=settings.temp_directory,
    )
    if delete_after_load:
        print(f"Converted QC output to temporary XYZ: {vmd_structure}")
        print("Temporary XYZ will be deleted by VMD right after import.")

    tcl_path = make_tcl_path_beside_structure(structure_path)
    tcl_text = build_vmd_tcl(
        vmd_structure,
        settings,
        delete_after_load=delete_after_load,
        start_frame_1based=start_frame,
        settings_path=settings_path,
        delete_self=not keep_tcl,
    )
    tcl_path = write_vmd_tcl(tcl_text, tcl_path)
    print(f"Display style: {settings.style}")
    print(
        "Color scheme: "
        + ("gview+Element" if settings.use_gview_element else "VMD default")
    )
    print(f"VMD script: {tcl_path}")
    print(f"Launching VMD: {vmd_exe}")

    try:
        launch_vmd(vmd_exe, tcl_path, settings.extra_args)
    except OSError as exc:
        if delete_after_load and vmd_structure.exists():
            vmd_structure.unlink(missing_ok=True)
        if not keep_tcl and tcl_path.exists():
            tcl_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to launch VMD: {exc}") from exc

    if not keep_tcl:
        # Primary cleanup is Tcl self-delete after sourcing; this catches leftovers.
        schedule_tcl_cleanup(tcl_path)
        print("Temporary Tcl will be deleted after VMD starts.")

    return tcl_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Visualize a structure/trajectory with local VMD."
    )
    parser.add_argument(
        "--structure",
        required=True,
        help="Path to .xyz / .pdb / ORCA .out / Gaussian .log|.out",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS),
        help=f"Path to settings.ini (default: {DEFAULT_SETTINGS})",
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        help="1-based frame index to display after load",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"vmd_viewer.py {VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tcl_path = visualize_with_vmd(
            Path(args.structure),
            Path(args.settings),
            start_frame=args.start_frame,
        )
        print(f"VMD launched (Tcl beside structure: {tcl_path})")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
