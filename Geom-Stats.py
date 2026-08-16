#!/usr/bin/env python3
"""Analyze distance, angle, or dihedral variation across multi-frame XYZ/PDB/quantum-chemistry outputs."""

from __future__ import annotations

import math
import multiprocessing
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import mol_preview
import plot_gnuplot
import vmd_viewer
from app_paths import bundled_native, ensure_editable_lib, user_app_dir, user_lib_dir

VERSION = "1.6.0"
PROGRAM_NAME = "Geom-Stats"
PB_PARALLEL_ANGLE_LIMIT_DEG = 20.0

APP_DIR = user_app_dir()
LIB_DIR = user_lib_dir()
SETTINGS_INI = LIB_DIR / "settings.ini"
# Back-compat aliases (all point to the unified Lib/settings.ini).
PLOT_SETTINGS = SETTINGS_INI
VMD_SETTINGS = SETTINGS_INI
PREVIEW_SETTINGS = SETTINGS_INI
GAUIRC2XYZ_EXE = bundled_native("GauIRC2xyz.exe")
GAUIRC_DOWNLOAD_URL = "http://sobereva.com/285"
X_AXIS_LABEL = "Step"
NEGATIVE_DECIMAL_RE = re.compile(r"-\d+\.\d+(?:[eE][+-]?\d+)?")

ORCA_COORD_MARKER = "CARTESIAN COORDINATES (ANGSTROEM)"
ORCA_CYCLE_RE = re.compile(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", re.IGNORECASE)
ORCA_ENERGY_MARKER = "FINAL SINGLE POINT ENERGY"
GAUSSIAN_ENERGY_MARKER = "SCF Done"
ORCA_ATOM_LINE_RE = re.compile(
    r"^\s+([A-Za-z]{1,2})\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*$"
)
GAUSSIAN_ATOM_LINE_RE = re.compile(
    r"^\s*\d+\s+(\d+)\s+\d+\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    r"([-+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*$"
)
GAUSSIAN_IRC_ROUTE_RE = re.compile(r"^\s*#\s*.*\bIRC\s*\(", re.IGNORECASE | re.MULTILINE)

ATOMIC_NUMBER_TO_SYMBOL: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
    11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
    21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
    31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
    41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
    61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
    71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
    81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
    91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm", 
    101: "Md", 102: "No",
}

FORMAT_LABELS = {
    "xyz": "XYZ",
    "pdb": "PDB",
    "orca": "ORCA output",
    "gaussian": "Gaussian output",
}

BASE_GEOMETRY_TYPES = {
    "B": ("Distance", 2, "Angstrom", (1, 1)),
    "A": ("Angle", 3, "degree", (1, 1, 1)),
    "D": ("Dihedral", 4, "degree", (1, 1, 1, 1)),
    "FP": ("Fragment-Plane Distance", 2, "Angstrom", (1, 3)),
    "PA": ("Plane-Plane Angle", 2, "degree", (3, 3)),
    "PB": ("Plane-Plane Distance", 2, "Angstrom", (3, 3)),
}
ENERGY_GEOMETRY_TYPE = ("Energy", 0, "Hartree", ())


@dataclass
class Atom:
    element: str
    x: float
    y: float
    z: float

    @property
    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Frame:
    comment: str
    atoms: list[Atom]
    energy: float | None = None


@dataclass
class AnalysisResult:
    geometry_key: str
    geometry_name: str
    unit: str
    fragments: list[list[int]]
    fragment_inputs: list[str]
    frame_indices: list[int]
    values: list[float]
    source_path: Path


def extract_negative_float_after_marker(text: str, marker: str) -> float | None:
    marker_index = text.find(marker)
    if marker_index == -1:
        return None
    tail = text[marker_index + len(marker) :]
    match = NEGATIVE_DECIMAL_RE.search(tail)
    if not match:
        return None
    return float(match.group(0))


def parse_energy(comment: str) -> float | None:
    """Extract electronic energy from a frame comment line, if present."""
    match = NEGATIVE_DECIMAL_RE.search(comment)
    if not match:
        return None
    return float(match.group(0))


def frame_energy_value(frame: Frame) -> float | None:
    if frame.energy is not None:
        return frame.energy
    return parse_energy(frame.comment)


def count_frames_with_energy(frames: Sequence[Frame]) -> int:
    return sum(1 for frame in frames if frame_energy_value(frame) is not None)


def trajectory_has_energy(frames: Sequence[Frame]) -> bool:
    return bool(frames) and count_frames_with_energy(frames) == len(frames)


def available_geometry_types(frames: Sequence[Frame]) -> dict[str, tuple]:
    geometry_types = dict(BASE_GEOMETRY_TYPES)
    if trajectory_has_energy(frames):
        geometry_types["E"] = ENERGY_GEOMETRY_TYPE
    return geometry_types


def vec_sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_norm(v: Sequence[float]) -> float:
    return math.sqrt(vec_dot(v, v))


def centroid(coords: Iterable[Sequence[float]]) -> tuple[float, float, float]:
    points = list(coords)
    if not points:
        raise ValueError("Cannot compute centroid of an empty atom group.")
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def vec_normalize(v: Sequence[float]) -> tuple[float, float, float]:
    norm = vec_norm(v)
    if norm == 0.0:
        raise ValueError("Cannot normalize a zero-length vector.")
    return (v[0] / norm, v[1] / norm, v[2] / norm)


def smallest_covariance_eigenvector(
    sxx: float,
    sxy: float,
    sxz: float,
    syy: float,
    syz: float,
    szz: float,
) -> tuple[float, float, float]:
    trace = sxx + syy + szz
    vector = (0.0, 0.0, 1.0)
    for _ in range(80):
        vector = (
            (trace - sxx) * vector[0] - sxy * vector[1] - sxz * vector[2],
            -sxy * vector[0] + (trace - syy) * vector[1] - syz * vector[2],
            -sxz * vector[0] - syz * vector[1] + (trace - szz) * vector[2],
        )
        vector = vec_normalize(vector)
    return vector


def fit_plane(points: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    pts = [tuple(p) for p in points]
    if len(pts) < 3:
        raise ValueError("At least 3 atoms are required to define a plane.")

    center = centroid(pts)
    if len(pts) == 3:
        normal = vec_cross(vec_sub(pts[1], pts[0]), vec_sub(pts[2], pts[0]))
        return center, vec_normalize(normal)

    sxx = syy = szz = sxy = sxz = syz = 0.0
    for point in pts:
        dx = point[0] - center[0]
        dy = point[1] - center[1]
        dz = point[2] - center[2]
        sxx += dx * dx
        syy += dy * dy
        szz += dz * dz
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz

    normal = smallest_covariance_eigenvector(sxx, sxy, sxz, syy, syz, szz)
    return center, normal


def calc_point_plane_distance(
    point: Sequence[float],
    plane_point: Sequence[float],
    plane_normal: Sequence[float],
) -> float:
    return abs(vec_dot(vec_sub(point, plane_point), plane_normal))


def calc_plane_plane_angle(
    normal1: Sequence[float],
    normal2: Sequence[float],
) -> float:
    cos_theta = abs(vec_dot(normal1, normal2))
    cos_theta = min(1.0, max(0.0, cos_theta))
    return math.degrees(math.acos(cos_theta))


def calc_plane_plane_distance(
    plane1_point: Sequence[float],
    plane1_normal: Sequence[float],
    plane2_point: Sequence[float],
    _plane2_normal: Sequence[float],
) -> float:
    return abs(vec_dot(vec_sub(plane2_point, plane1_point), plane1_normal))


def calc_distance(p1: Sequence[float], p2: Sequence[float]) -> float:
    return vec_norm(vec_sub(p2, p1))


def calc_angle(p1: Sequence[float], p2: Sequence[float], p3: Sequence[float]) -> float:
    v1 = vec_sub(p1, p2)
    v2 = vec_sub(p3, p2)
    n1 = vec_norm(v1)
    n2 = vec_norm(v2)
    if n1 == 0.0 or n2 == 0.0:
        raise ValueError("Angle calculation failed: zero-length vector.")
    cos_theta = max(-1.0, min(1.0, vec_dot(v1, v2) / (n1 * n2)))
    return math.degrees(math.acos(cos_theta))


def calc_dihedral(
    p1: Sequence[float],
    p2: Sequence[float],
    p3: Sequence[float],
    p4: Sequence[float],
) -> float:
    b1 = vec_sub(p2, p1)
    b2 = vec_sub(p3, p2)
    b3 = vec_sub(p4, p3)
    n1 = vec_cross(b1, b2)
    n2 = vec_cross(b2, b3)
    b2_norm = vec_norm(b2)
    if b2_norm == 0.0:
        raise ValueError("Dihedral calculation failed: central bond has zero length.")
    m1 = vec_cross(n1, (b2[0] / b2_norm, b2[1] / b2_norm, b2[2] / b2_norm))
    x = vec_dot(n1, n2)
    y = vec_dot(m1, n2)
    return math.degrees(math.atan2(y, x))


def parse_xyz(path: Path) -> list[Frame]:
    # Keep blank lines: an empty line after the atom count is a valid (empty) comment.
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total_lines = len(lines)

    frames: list[Frame] = []
    index = 0
    while index < total_lines:
        # Skip blank separators between frames only; never skip the comment slot.
        while index < total_lines and not lines[index].strip():
            index += 1
        if index >= total_lines:
            break

        count_line = lines[index].strip()
        try:
            natoms = int(count_line)
        except ValueError as exc:
            raise ValueError(
                f"Invalid atom count at line {index + 1}: {lines[index]!r}"
            ) from exc

        if index + 1 >= total_lines:
            raise ValueError(f"Missing comment line after atom count at line {index + 1}.")

        comment = lines[index + 1].strip()
        atom_start = index + 2
        if atom_start + natoms > total_lines:
            raise ValueError(
                f"Frame starting at line {index + 1} expects {natoms} atoms, "
                "but the file ends prematurely."
            )

        atoms: list[Atom] = []
        for offset in range(natoms):
            line_number = atom_start + offset + 1
            parts = lines[atom_start + offset].split()
            if len(parts) < 4:
                raise ValueError(
                    f"Invalid atom line at file line {line_number}: "
                    f"{lines[atom_start + offset]!r}"
                )
            atoms.append(Atom(parts[0], float(parts[1]), float(parts[2]), float(parts[3])))

        frames.append(Frame(comment=comment, atoms=atoms))
        index = atom_start + natoms

    if not frames:
        raise ValueError("No frames were found in the XYZ file.")

    return frames


def parse_pdb_atom_line(line: str) -> Atom:
    record = line[:6].strip()
    if record not in {"ATOM", "HETATM"}:
        raise ValueError(f"Not an ATOM/HETATM record: {line!r}")

    padded = line.ljust(80)
    atom_name = padded[12:16].strip()
    element = padded[76:78].strip()
    if not element:
        letters = "".join(ch for ch in atom_name if ch.isalpha())
        if len(letters) >= 2 and letters[1].islower():
            element = letters[:2]
        elif letters:
            element = letters[0]
        else:
            element = "X"

    x = float(padded[30:38])
    y = float(padded[38:46])
    z = float(padded[46:54])
    return Atom(element, x, y, z)


def finalize_pdb_frame(
    frames: list[Frame],
    atoms: list[Atom],
    comment: str,
) -> tuple[list[Atom], str]:
    if atoms:
        frame_comment = comment or f"Frame {len(frames) + 1}"
        frames.append(Frame(comment=frame_comment, atoms=atoms))
    return [], ""


def parse_pdb(path: Path) -> list[Frame]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: list[Frame] = []
    current_atoms: list[Atom] = []
    current_comment = ""

    for line_number, raw_line in enumerate(text, start=1):
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        record = line[:6].strip()

        if record == "MODEL":
            current_atoms, current_comment = finalize_pdb_frame(frames, current_atoms, current_comment)
            model_id = line[6:].strip()
            current_comment = f"MODEL {model_id}" if model_id else f"Frame {len(frames) + 1}"
            continue

        if record == "ENDMDL":
            current_atoms, current_comment = finalize_pdb_frame(frames, current_atoms, current_comment)
            continue

        if record == "REMARK" and not current_atoms:
            current_comment = line[6:].strip()
            continue

        if record in {"ATOM", "HETATM"}:
            try:
                current_atoms.append(parse_pdb_atom_line(line))
            except ValueError as exc:
                raise ValueError(f"Invalid atom record at line {line_number}: {line!r}") from exc
            continue

        if record == "END":
            current_atoms, current_comment = finalize_pdb_frame(frames, current_atoms, current_comment)
            continue

    current_atoms, _ = finalize_pdb_frame(frames, current_atoms, current_comment)

    if not frames:
        raise ValueError("No frames were found in the PDB file.")

    return frames


def symbol_from_atomic_number(atomic_number: int) -> str:
    symbol = ATOMIC_NUMBER_TO_SYMBOL.get(atomic_number)
    if symbol is None:
        raise ValueError(f"Unsupported atomic number in Gaussian output: {atomic_number}")
    return symbol


def is_separator_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"-"}


def find_orca_cycle_number(lines: Sequence[str], coord_line_index: int) -> int | None:
    for offset in range(coord_line_index, max(coord_line_index - 30, -1), -1):
        match = ORCA_CYCLE_RE.search(lines[offset])
        if match:
            return int(match.group(1))
    return None


def find_orca_energy(lines: Sequence[str], start_index: int) -> float | None:
    limit = min(start_index + 3000, len(lines))
    for index in range(start_index, limit):
        if ORCA_COORD_MARKER in lines[index] and index > start_index:
            break
        if ORCA_ENERGY_MARKER in lines[index]:
            energy = extract_negative_float_after_marker(lines[index], ORCA_ENERGY_MARKER)
            if energy is not None:
                return energy
    return None


def parse_orca(path: Path) -> list[Frame]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: list[Frame] = []
    index = 0
    total_lines = len(lines)

    while index < total_lines:
        if ORCA_COORD_MARKER not in lines[index]:
            index += 1
            continue

        coord_line_index = index
        index += 1
        while index < total_lines and is_separator_line(lines[index]):
            index += 1

        atoms: list[Atom] = []
        while index < total_lines:
            match = ORCA_ATOM_LINE_RE.match(lines[index])
            if not match:
                break
            atoms.append(
                Atom(
                    match.group(1),
                    float(match.group(2)),
                    float(match.group(3)),
                    float(match.group(4)),
                )
            )
            index += 1

        if not atoms:
            continue

        cycle = find_orca_cycle_number(lines, coord_line_index) or len(frames) + 1
        energy = find_orca_energy(lines, index)
        if energy is not None:
            comment = f"ORCA cycle {cycle}, E = {energy}"
        else:
            comment = f"ORCA cycle {cycle}"
        frames.append(Frame(comment=comment, atoms=atoms, energy=energy))

    if not frames:
        raise ValueError("No ORCA Cartesian-coordinate blocks were found in the output file.")

    return frames


def read_gaussian_coordinates(lines: Sequence[str], start_index: int) -> tuple[list[Atom], int]:
    index = start_index + 1
    total_lines = len(lines)
    while index < total_lines and not is_separator_line(lines[index]):
        index += 1
    if index >= total_lines:
        return [], index
    index += 1
    while index < total_lines and not GAUSSIAN_ATOM_LINE_RE.match(lines[index]):
        if is_separator_line(lines[index]):
            index += 1
            break
        index += 1

    atoms: list[Atom] = []
    while index < total_lines:
        if is_separator_line(lines[index]):
            break
        match = GAUSSIAN_ATOM_LINE_RE.match(lines[index])
        if not match:
            break
        atomic_number = int(match.group(1))
        atoms.append(
            Atom(
                symbol_from_atomic_number(atomic_number),
                float(match.group(2)),
                float(match.group(3)),
                float(match.group(4)),
            )
        )
        index += 1
    return atoms, index


def find_gaussian_energy_after(lines: Sequence[str], start_index: int) -> float | None:
    limit = min(start_index + 5000, len(lines))
    for index in range(start_index, limit):
        if GAUSSIAN_ENERGY_MARKER in lines[index]:
            energy = extract_negative_float_after_marker(lines[index], GAUSSIAN_ENERGY_MARKER)
            if energy is not None:
                return energy
    return None


def parse_gaussian(path: Path) -> list[Frame]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    orientation_indices = [
        index for index, line in enumerate(lines) if "Standard orientation" in line
    ]
    if not orientation_indices:
        raise ValueError("No Gaussian standard-orientation blocks were found in the output file.")

    frames: list[Frame] = []
    for step, orientation_index in enumerate(orientation_indices, start=1):
        atoms, coord_end = read_gaussian_coordinates(lines, orientation_index)
        if not atoms:
            continue
        energy = find_gaussian_energy_after(lines, coord_end)
        if energy is not None:
            comment = f"Gaussian step {step}, E = {energy}"
        else:
            comment = f"Gaussian step {step}"
        frames.append(Frame(comment=comment, atoms=atoms, energy=energy))

    if not frames:
        raise ValueError("No Gaussian standard-orientation blocks were found in the output file.")

    return frames


def is_orca_output(text: str) -> bool:
    return (
        "* O   R   C   A *" in text
        or (
            ORCA_COORD_MARKER in text
            and "FINAL SINGLE POINT ENERGY" in text
            and "Entering Gaussian System" not in text
        )
    )


def is_gaussian_output(text: str) -> bool:
    if GAUSSIAN_IRC_ROUTE_RE.search(text) or "IRC-IRC-IRC" in text:
        return True
    return "Gaussian" in text and "Standard orientation" in text


def detect_structure_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xyz":
        return "xyz"
    if suffix == ".pdb":
        return "pdb"
    if suffix in {".out", ".log"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        is_orca = is_orca_output(text)
        is_gaussian = is_gaussian_output(text)
        if is_orca and not is_gaussian:
            return "orca"
        if is_gaussian and not is_orca:
            return "gaussian"
        if is_orca:
            return "orca"
        if is_gaussian:
            return "gaussian"
        raise ValueError(
            f"Unable to identify program output format for {path.name}. "
            "Expected ORCA or Gaussian trajectory data."
        )
    raise ValueError(
        f"Unsupported structure format: {suffix}. "
        "Use .xyz, .pdb, ORCA .out, or Gaussian .log/.out."
    )


def is_gaussian_irc_output(text: str) -> bool:
    if GAUSSIAN_IRC_ROUTE_RE.search(text):
        return True
    return "IRC-IRC-IRC" in text


def convert_gaussian_irc_to_xyz(source_path: Path) -> Path:
    exe = bundled_native("GauIRC2xyz.exe")
    if not exe.exists():
        raise FileNotFoundError(
            f"GauIRC2xyz converter not found: {exe}\n"
            f"Please download it from {GAUIRC_DOWNLOAD_URL}"
        )

    print("IRC output file detected.")
    print(f"Converting with {exe.name} ...")

    source_path = source_path.resolve()
    xyz_path = source_path.with_suffix(".xyz")

    # GauIRC2xyz is a legacy console program that cannot open Unicode paths.
    with tempfile.TemporaryDirectory(prefix="gauirc_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        local_input = temp_dir_path / source_path.name
        shutil.copy2(source_path, local_input)

        result = subprocess.run(
            [str(exe)],
            input=f"{local_input}\n\n",
            cwd=str(temp_dir_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        local_xyz = local_input.with_suffix(".xyz")
        if not local_xyz.exists():
            raise RuntimeError(
                "GauIRC2xyz did not create the expected XYZ file.\n"
                f"{result.stderr or result.stdout}"
            )

        shutil.copy2(local_xyz, xyz_path)

    print(f"IRC conversion completed: {xyz_path}")
    return xyz_path.resolve()


def prepare_structure_source(source_path: Path) -> Path:
    structure_format = detect_structure_format(source_path)
    if structure_format != "gaussian":
        return source_path

    text = source_path.read_text(encoding="utf-8", errors="replace")
    if not is_gaussian_irc_output(text):
        return source_path

    return convert_gaussian_irc_to_xyz(source_path)


def load_frames_from_path(path: Path) -> tuple[str, list[Frame]]:
    structure_format = detect_structure_format(path)
    if structure_format == "xyz":
        return structure_format, parse_xyz(path)
    if structure_format == "pdb":
        return structure_format, parse_pdb(path)
    if structure_format == "orca":
        return structure_format, parse_orca(path)
    if structure_format == "gaussian":
        return structure_format, parse_gaussian(path)
    raise ValueError(f"Unsupported structure format: {structure_format}")


DEFAULT_OUTPUT_STEM = "Geom"


def default_output_stem(round_index: int) -> str:
    if round_index <= 1:
        return DEFAULT_OUTPUT_STEM
    return f"{DEFAULT_OUTPUT_STEM}-{round_index}"


def prompt_with_default(prompt: str, default: str) -> str:
    value = input(prompt).strip()
    return value if value else default


def prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Input cannot be empty. Please try again.")


def prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def parse_index_selection(text: str, max_value: int, *, label: str = "index") -> list[int]:
    indices: list[int] = []
    for token in text.replace(",", " ").split():
        if "-" in token:
            parts = token.split("-", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"Invalid {label} or range: {token!r}")
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid {label} or range: {token!r}") from exc
            low, high = (start, end) if start <= end else (end, start)
            for idx in range(low, high + 1):
                if idx < 1 or idx > max_value:
                    raise ValueError(f"{label.capitalize()} {idx} is out of range (1-{max_value}).")
                indices.append(idx)
            continue

        try:
            idx = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid {label}: {token!r}") from exc
        if idx < 1 or idx > max_value:
            raise ValueError(f"{label.capitalize()} {idx} is out of range (1-{max_value}).")
        indices.append(idx)

    if not indices:
        raise ValueError(f"At least one {label} is required.")

    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return unique


def parse_atom_indices(text: str, max_atoms: int) -> list[int]:
    return parse_index_selection(text, max_atoms, label="atom index")


def parse_frame_indices(text: str, max_frames: int) -> list[int]:
    return parse_index_selection(text, max_frames, label="frame")


def prompt_frame_selection(total_frames: int) -> list[int]:
    default = "1" if total_frames == 1 else f"1-{total_frames}"
    print(
        "\nEnter frame indices to analyze (1-based). "
        "Separate multiple indices with spaces or commas; "
        "use a hyphen to specify a continuous range (e.g. 5-20)."
    )
    while True:
        raw = prompt_with_default(f"Frame indices [default: {default}]: ", default)
        try:
            return parse_frame_indices(raw, total_frames)
        except ValueError as exc:
            print(f"Error: {exc}")


def prompt_fragments(
    num_fragments: int,
    max_atoms: int,
    min_atoms: Sequence[int],
    preview_session: object | None = None,
) -> tuple[list[list[int]], list[str], object | None]:
    fragments: list[list[int]] = []
    fragment_inputs: list[str] = []
    print(
        "Enter atom indices for each fragment (1-based). "
        "Separate multiple indices with spaces or commas; "
        "use a hyphen to specify a continuous range (e.g. 40-44)."
    )
    warned_preview_closed = False
    for fragment_id in range(1, num_fragments + 1):
        min_required = min_atoms[fragment_id - 1]
        requirement = ""
        if min_required > 1:
            requirement = f" (at least {min_required} atoms required)"
        while True:
            raw = prompt_nonempty(f"Fragment {fragment_id} atom indices{requirement}: ")
            try:
                indices = parse_atom_indices(raw, max_atoms)
                if len(indices) < min_required:
                    raise ValueError(
                        f"Fragment {fragment_id} requires at least {min_required} atom(s), "
                        f"but only {len(indices)} were provided."
                    )
                fragments.append(indices)
                fragment_inputs.append(raw.strip())
                if preview_session is not None:
                    try:
                        alive = bool(preview_session.is_alive())  # type: ignore[attr-defined]
                        ok = bool(preview_session.set_highlights(fragments))  # type: ignore[attr-defined]
                    except (BrokenPipeError, OSError, AttributeError):
                        alive = False
                        ok = False
                    if not alive or not ok:
                        if not warned_preview_closed:
                            print(
                                "Built-in preview closed; highlight sync disabled "
                                "for remaining fragment prompts."
                            )
                            warned_preview_closed = True
                        preview_session = None
                break
            except ValueError as exc:
                print(f"Error: {exc}")
    return fragments, fragment_inputs, preview_session


def fragment_coords(frame: Frame, atom_indices: Sequence[int]) -> list[tuple[float, float, float]]:
    return [frame.atoms[i - 1].coords for i in atom_indices]


def fragment_centroid(frame: Frame, atom_indices: Sequence[int]) -> tuple[float, float, float]:
    coords = [frame.atoms[i - 1].coords for i in atom_indices]
    return centroid(coords)


def plane_plane_angle_for_fragments(
    frame: Frame,
    fragments: Sequence[Sequence[int]],
) -> float:
    _, normal1 = fit_plane(fragment_coords(frame, fragments[0]))
    _, normal2 = fit_plane(fragment_coords(frame, fragments[1]))
    return calc_plane_plane_angle(normal1, normal2)


def resolve_pb_or_fp(
    frame: Frame,
    fragments: Sequence[Sequence[int]],
) -> tuple[str, float]:
    """Return PB if planes are nearly parallel; otherwise fall back to FP."""
    angle = plane_plane_angle_for_fragments(frame, fragments)
    if angle > PB_PARALLEL_ANGLE_LIMIT_DEG:
        return "FP", angle
    return "PB", angle


def compute_geometry_value(
    geometry_key: str,
    frame: Frame,
    fragments: Sequence[Sequence[int]],
) -> float:
    if geometry_key == "B":
        points = [fragment_centroid(frame, group) for group in fragments]
        return calc_distance(points[0], points[1])
    if geometry_key == "A":
        points = [fragment_centroid(frame, group) for group in fragments]
        return calc_angle(points[0], points[1], points[2])
    if geometry_key == "D":
        points = [fragment_centroid(frame, group) for group in fragments]
        return calc_dihedral(points[0], points[1], points[2], points[3])
    if geometry_key == "FP":
        point = fragment_centroid(frame, fragments[0])
        plane_center, plane_normal = fit_plane(fragment_coords(frame, fragments[1]))
        return calc_point_plane_distance(point, plane_center, plane_normal)
    if geometry_key == "PA":
        return plane_plane_angle_for_fragments(frame, fragments)
    if geometry_key == "PB":
        center1, normal1 = fit_plane(fragment_coords(frame, fragments[0]))
        center2, normal2 = fit_plane(fragment_coords(frame, fragments[1]))
        return calc_plane_plane_distance(center1, normal1, center2, normal2)
    if geometry_key == "E":
        energy = frame_energy_value(frame)
        if energy is None:
            raise ValueError(f"Frame comment does not contain energy information: {frame.comment!r}")
        return energy
    raise ValueError(f"Unsupported geometry type: {geometry_key}")


def analyze_frames(
    frame_numbers: Sequence[int],
    frames: Sequence[Frame],
    geometry_key: str,
    fragments: list[list[int]],
    fragment_inputs: list[str],
    source_path: Path,
    geometry_types: dict[str, tuple],
) -> AnalysisResult:
    geometry_name, _, unit, _ = geometry_types[geometry_key]
    natoms_ref = len(frames[0].atoms)
    frame_indices: list[int] = []
    values: list[float] = []

    for frame_id, frame in zip(frame_numbers, frames):
        if len(frame.atoms) != natoms_ref:
            raise ValueError(
                f"Frame {frame_id} contains {len(frame.atoms)} atoms, "
                f"but frame {frame_numbers[0]} contains {natoms_ref} atoms."
            )
        value = compute_geometry_value(geometry_key, frame, fragments)
        frame_indices.append(frame_id)
        values.append(value)

    return AnalysisResult(
        geometry_key=geometry_key,
        geometry_name=geometry_name,
        unit=unit,
        fragments=fragments,
        fragment_inputs=fragment_inputs,
        frame_indices=frame_indices,
        values=values,
        source_path=source_path,
    )


def format_fragment_summary(fragment_inputs: Sequence[str]) -> str:
    parts = []
    for idx, text in enumerate(fragment_inputs, start=1):
        parts.append(f"Fragment {idx}: [{text}]")
    return "; ".join(parts)


def write_statistics_file(result: AnalysisResult, output_path: Path) -> None:
    minimum = min(result.values)
    maximum = max(result.values)
    mean = sum(result.values) / len(result.values)

    fragment_line = "# Fragment definition: N/A"
    if result.fragment_inputs:
        fragment_line = f"# Fragment definition: {format_fragment_summary(result.fragment_inputs)}"

    lines = [
        "# Molecular geometry statistics",
        f"# Auto-generated by {PROGRAM_NAME}.py (Version {VERSION})",
        f"# Source file: {result.source_path}",
        f"# Quantity: {result.geometry_name}",
        fragment_line,
        f"# Unit: {result.unit}",
        "#",
        f"# {X_AXIS_LABEL:<8} Value",
    ]
    for frame_id, value in zip(result.frame_indices, result.values):
        lines.append(f"{frame_id:6d}    {value: .6f}")

    lines.extend(
        [
            "#",
            "# Summary",
            f"# Minimum: {minimum:.6f} {result.unit}",
            f"# Maximum: {maximum:.6f} {result.unit}",
            f"# Mean:    {mean:.6f} {result.unit}",
            f"# Frames:  {len(result.values)}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def invoke_lib_plot(data_path: Path) -> None:
    """Plot via the bundled plot_gnuplot module."""
    if not SETTINGS_INI.exists():
        raise FileNotFoundError(f"Settings file not found: {SETTINGS_INI}")
    plt_path, plot_path = plot_gnuplot.plot_statistics_file(data_path, PLOT_SETTINGS)
    print(f"Plot saved to: {plot_path}")
    print(f"Gnuplot script saved to: {plt_path}")


def invoke_lib_vmd(structure_path: Path, *, start_frame: int | None = None) -> None:
    """Visualize via the bundled vmd_viewer module."""
    if not SETTINGS_INI.exists():
        raise FileNotFoundError(f"Settings file not found: {SETTINGS_INI}")
    tcl_path = vmd_viewer.visualize_with_vmd(
        structure_path,
        VMD_SETTINGS,
        start_frame=start_frame,
    )
    print(f"VMD launched. Tcl script: {tcl_path}")


def invoke_lib_preview(frame: Frame, *, source_label: str = "") -> object | None:
    """Launch built-in first-frame preview (sidecar Tk/Matplotlib window)."""
    if not SETTINGS_INI.exists():
        raise FileNotFoundError(f"Settings file not found: {SETTINGS_INI}")
    session = mol_preview.start_preview(
        frame,
        PREVIEW_SETTINGS,
        source_label=source_label,
    )
    if session is None or not session.is_alive():
        detail = ""
        if session is not None:
            try:
                detail = session.read_stderr()  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                detail = ""
        raise RuntimeError(
            "Preview process exited immediately after launch."
            + (f" Details: {detail}" if detail else "")
        )
    print(
        "Built-in preview launched (selected analysis frame). "
        "Press Q in the window to quit."
    )
    return session


def prompt_visualization_choice() -> str:
    """Ask how to visualize: F=built-in, V=VMD, N=none."""
    print("\nVisualization options:")
    print("  F - Built-in preview of selected frame (atom indices + CLI highlight)")
    print("  V - VMD multi-frame visualization")
    print("  N - No visualization")
    while True:
        choice = input("Select visualization mode (F/V/N): ").strip().upper()
        if choice in {"F", "V", "N"}:
            return choice
        print("Invalid choice. Please enter F, V, or N.")


def wait_for_exit() -> None:
    try:
        input("Press ENTER to exit.")
    except EOFError:
        pass


GEOMETRY_CHOICE_ORDER = ("B", "A", "D", "FP", "PA", "PB", "E")


def choose_geometry_type(geometry_types: dict[str, tuple]) -> str:
    print("\nAvailable geometric quantities:")
    labels = {
        "B": "Distance",
        "A": "Angle",
        "D": "Dihedral angle",
        "FP": "Fragment-Plane distance",
        "PA": "Plane-Plane angle",
        "PB": "Plane-Plane distance",
        "E": "Energy",
    }
    for key in GEOMETRY_CHOICE_ORDER:
        if key in geometry_types:
            print(f"  {key:<2} - {labels[key]}")
    valid_choices = "/".join(key for key in GEOMETRY_CHOICE_ORDER if key in geometry_types)
    while True:
        choice = input(f"Select quantity to analyze ({valid_choices}): ").strip().upper()
        if choice in geometry_types:
            return choice
        print(f"Invalid choice. Please enter one of: {valid_choices}.")


def load_structure_file() -> tuple[Path, list[Frame], list[int], list[Frame], object | None]:
    while True:
        raw_path = prompt_nonempty(
            "\nEnter path to the structure file (.xyz, .pdb, ORCA .out, Gaussian .log/.out): "
        )
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = (Path.cwd() / source_path).resolve()
        if not source_path.exists():
            print(f"Error: File not found: {source_path}")
            continue
        try:
            effective_path = prepare_structure_source(source_path)
            structure_format, all_frames = load_frames_from_path(effective_path)
            total_frames = len(all_frames)
            print(f"Loaded {total_frames} frame(s) from: {effective_path}")
            print(f"Format: {FORMAT_LABELS.get(structure_format, structure_format)}")
            print(f"Atoms per frame: {len(all_frames[0].atoms)}")
            energy_count = count_frames_with_energy(all_frames)
            if energy_count > 0:
                print(f"Energy information detected in {energy_count}/{total_frames} frame(s).")
            frame_numbers = prompt_frame_selection(total_frames)
            selected_frames = [all_frames[index - 1] for index in frame_numbers]
            print(f"Selected {len(frame_numbers)} frame(s) for analysis.")

            preview_session: object | None = None
            viz_choice = prompt_visualization_choice()
            if viz_choice == "F":
                try:
                    # Use the first selected analysis frame (same context as VMD start_frame).
                    preview_session = invoke_lib_preview(
                        selected_frames[0],
                        source_label=(
                            f"{effective_path.name} (frame {frame_numbers[0]})"
                        ),
                    )
                except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                    print(f"Built-in preview failed: {exc}")
            elif viz_choice == "V":
                try:
                    invoke_lib_vmd(effective_path, start_frame=frame_numbers[0])
                except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                    print(f"VMD visualization failed: {exc}")

            return effective_path, all_frames, frame_numbers, selected_frames, preview_session
        except ValueError as exc:
            print(f"Error while reading structure file: {exc}")
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"Error: {exc}")


def prompt_output_path(source_path: Path, round_index: int) -> Path:
    default_dir = source_path.parent.resolve()
    default_name = default_output_stem(round_index)
    while True:
        directory = prompt_with_default(
            f"\nEnter output directory path [default: {default_dir}]: ",
            str(default_dir),
        )
        out_dir = Path(directory).expanduser()
        if not out_dir.is_absolute():
            out_dir = (Path.cwd() / out_dir).resolve()
        filename = prompt_with_default(
            f"Enter output file name without extension [default: {default_name}]: ",
            default_name,
        )
        safe_name = filename.strip()
        if not safe_name:
            print("File name cannot be empty.")
            continue
        if any(ch in safe_name for ch in r'\/:*?"<>|'):
            print("File name contains invalid characters.")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{safe_name}.txt"


def run_analysis_round(
    source_path: Path,
    all_frames: list[Frame],
    frame_numbers: list[int],
    selected_frames: list[Frame],
    round_index: int,
    preview_session: object | None = None,
) -> object | None:
    geometry_types = available_geometry_types(all_frames)
    geometry_key = choose_geometry_type(geometry_types)
    geometry_name, num_fragments, unit, min_atoms = geometry_types[geometry_key]
    print(f"\nSelected quantity: {geometry_name} ({unit})")
    if geometry_key == "PB":
        print(
            "Note: PB is the point-plane distance along the normal of plane 1 "
            "(centroid of plane 2 to plane 1)."
        )
        print(
            f"If the plane-plane angle exceeds {PB_PARALLEL_ANGLE_LIMIT_DEG:.0f} deg, "
            "the planes are not treated as approximately parallel and the analysis "
            "falls back to fragment-plane distance (FP): centroid of fragment 1 to plane 2."
        )

    fragments: list[list[int]] = []
    fragment_inputs: list[str] = []
    if geometry_key != "E":
        fragments, fragment_inputs, preview_session = prompt_fragments(
            num_fragments,
            len(selected_frames[0].atoms),
            min_atoms,
            preview_session=preview_session,
        )

    if geometry_key == "PB":
        effective_key, angle = resolve_pb_or_fp(selected_frames[0], fragments)
        if effective_key == "FP":
            print(
                f"\nPlane-plane angle on the first selected frame is {angle:.2f} deg "
                f"(> {PB_PARALLEL_ANGLE_LIMIT_DEG:.0f} deg)."
            )
            print(
                "Planes are not approximately parallel; switching to fragment-plane "
                "distance (FP)."
            )
            geometry_key = "FP"
            geometry_name, _, unit, _ = geometry_types[geometry_key]
            print(f"Effective quantity: {geometry_name} ({unit})")
        else:
            print(
                f"\nPlane-plane angle on the first selected frame is {angle:.2f} deg "
                f"(<= {PB_PARALLEL_ANGLE_LIMIT_DEG:.0f} deg); keeping PB."
            )

    print("\nComputing geometry across selected frames...")
    result = analyze_frames(
        frame_numbers,
        selected_frames,
        geometry_key,
        fragments,
        fragment_inputs,
        source_path,
        geometry_types,
    )

    output_path = prompt_output_path(source_path, round_index)
    write_statistics_file(result, output_path)
    print(f"\nStatistics saved to: {output_path}")

    if prompt_yes_no("\nPlot the results with plot_gnuplot.py? [y/n]: "):
        try:
            invoke_lib_plot(output_path)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"Plotting failed: {exc}")
    return preview_session


def dispatch_cli(argv: list[str] | None = None) -> int:
    """Route frozen sidecar / optional xyz2fakeg before the interactive CLI."""
    ensure_editable_lib()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--preview-viewer" in args:
        rest = [item for item in args if item != "--preview-viewer"]
        if "--viewer" not in rest:
            rest = ["--viewer", *rest]
        return mol_preview.main(rest)
    if args and args[0] == "--xyz2fakeg":
        import xyz2fakeg

        return xyz2fakeg.main(args[1:])
    return main()


def main() -> int:
    print(f"=== {PROGRAM_NAME} ===")
    print(" Molecular Geometry Statistics")
    print(f" Version {VERSION}")

    preview_session: object | None = None
    try:
        (
            source_path,
            all_frames,
            frame_numbers,
            selected_frames,
            preview_session,
        ) = load_structure_file()

        round_index = 1
        while True:
            preview_session = run_analysis_round(
                source_path,
                all_frames,
                frame_numbers,
                selected_frames,
                round_index,
                preview_session=preview_session,
            )
            round_index += 1
            if not prompt_yes_no(
                "\nAnalyze another geometric quantity with the same structure file? [y/n]: "
            ):
                break

        if preview_session is not None:
            try:
                preview_session.close()  # type: ignore[attr-defined]
            except (BrokenPipeError, OSError, AttributeError):
                pass
        wait_for_exit()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        if preview_session is not None:
            try:
                preview_session.close()  # type: ignore[attr-defined]
            except (BrokenPipeError, OSError, AttributeError):
                pass
        return 1
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        if preview_session is not None:
            try:
                preview_session.close()  # type: ignore[attr-defined]
            except (BrokenPipeError, OSError, AttributeError):
                pass
        wait_for_exit()
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(dispatch_cli())

