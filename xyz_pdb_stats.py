#!/usr/bin/env python3
"""Analyze distance, angle, or dihedral variation across multi-frame XYZ/PDB trajectories."""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

GNUPLOT_COMMAND = "gnuplot"

GEOMETRY_TYPES = {
    "B": ("Distance", 2, "Angstrom", (1, 1)),
    "A": ("Angle", 3, "degree", (1, 1, 1)),
    "D": ("Dihedral", 4, "degree", (1, 1, 1, 1)),
    "FP": ("Fragment-Plane Distance", 2, "Angstrom", (1, 3)),
    "PA": ("Plane-Plane Angle", 2, "degree", (3, 3)),
    "PB": ("Plane-Plane Distance", 2, "Angstrom", (3, 3)),
}


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


@dataclass
class AnalysisResult:
    geometry_key: str
    geometry_name: str
    unit: str
    fragments: list[list[int]]
    frame_indices: list[int]
    values: list[float]
    source_path: Path


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
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = [line.strip() for line in text if line.strip()]

    frames: list[Frame] = []
    index = 0
    while index < len(lines):
        try:
            natoms = int(lines[index])
        except ValueError as exc:
            raise ValueError(f"Invalid atom count at line {index + 1}: {lines[index]!r}") from exc

        if index + 1 >= len(lines):
            raise ValueError(f"Missing comment line after atom count at line {index + 1}.")
        comment = lines[index + 1]

        if index + 2 + natoms > len(lines):
            raise ValueError(
                f"Frame starting at line {index + 1} expects {natoms} atoms, "
                "but the file ends prematurely."
            )

        atoms: list[Atom] = []
        for offset in range(natoms):
            parts = lines[index + 2 + offset].split()
            if len(parts) < 4:
                raise ValueError(
                    f"Invalid atom line at file line {index + 3 + offset}: {lines[index + 2 + offset]!r}"
                )
            atoms.append(Atom(parts[0], float(parts[1]), float(parts[2]), float(parts[3])))

        frames.append(Frame(comment=comment, atoms=atoms))
        index += 2 + natoms

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


def load_frames_from_path(path: Path) -> list[Frame]:
    suffix = path.suffix.lower()
    if suffix == ".xyz":
        return parse_xyz(path)
    if suffix == ".pdb":
        return parse_pdb(path)
    raise ValueError(f"Unsupported structure format: {suffix}. Use .xyz or .pdb.")


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


def parse_atom_indices(text: str, max_atoms: int) -> list[int]:
    indices: list[int] = []
    for token in text.replace(",", " ").split():
        if "-" in token:
            parts = token.split("-", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"Invalid atom index or range: {token!r}")
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid atom index or range: {token!r}") from exc
            low, high = (start, end) if start <= end else (end, start)
            for idx in range(low, high + 1):
                if idx < 1 or idx > max_atoms:
                    raise ValueError(f"Atom index {idx} is out of range (1-{max_atoms}).")
                indices.append(idx)
            continue

        try:
            idx = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid atom index: {token!r}") from exc
        if idx < 1 or idx > max_atoms:
            raise ValueError(f"Atom index {idx} is out of range (1-{max_atoms}).")
        indices.append(idx)

    if not indices:
        raise ValueError("At least one atom index is required for each fragment.")

    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return unique


def prompt_fragments(
    num_fragments: int,
    max_atoms: int,
    min_atoms: Sequence[int],
) -> list[list[int]]:
    fragments: list[list[int]] = []
    print(
        "Enter atom indices for each fragment (1-based). "
        "Separate multiple indices with spaces or commas; "
        "use a hyphen to specify a continuous range (e.g. 40-44)."
    )
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
                break
            except ValueError as exc:
                print(f"Error: {exc}")
    return fragments


def fragment_coords(frame: Frame, atom_indices: Sequence[int]) -> list[tuple[float, float, float]]:
    return [frame.atoms[i - 1].coords for i in atom_indices]


def fragment_centroid(frame: Frame, atom_indices: Sequence[int]) -> tuple[float, float, float]:
    coords = [frame.atoms[i - 1].coords for i in atom_indices]
    return centroid(coords)


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
        _, normal1 = fit_plane(fragment_coords(frame, fragments[0]))
        _, normal2 = fit_plane(fragment_coords(frame, fragments[1]))
        return calc_plane_plane_angle(normal1, normal2)
    if geometry_key == "PB":
        center1, normal1 = fit_plane(fragment_coords(frame, fragments[0]))
        center2, normal2 = fit_plane(fragment_coords(frame, fragments[1]))
        return calc_plane_plane_distance(center1, normal1, center2, normal2)
    raise ValueError(f"Unsupported geometry type: {geometry_key}")


def analyze_frames(
    frames: list[Frame],
    geometry_key: str,
    fragments: list[list[int]],
    source_path: Path,
) -> AnalysisResult:
    geometry_name, _, unit, _ = GEOMETRY_TYPES[geometry_key]
    natoms_ref = len(frames[0].atoms)
    frame_indices: list[int] = []
    values: list[float] = []

    for frame_id, frame in enumerate(frames, start=1):
        if len(frame.atoms) != natoms_ref:
            raise ValueError(
                f"Frame {frame_id} contains {len(frame.atoms)} atoms, "
                f"but frame 1 contains {natoms_ref} atoms."
            )
        value = compute_geometry_value(geometry_key, frame, fragments)
        frame_indices.append(frame_id)
        values.append(value)

    return AnalysisResult(
        geometry_key=geometry_key,
        geometry_name=geometry_name,
        unit=unit,
        fragments=fragments,
        frame_indices=frame_indices,
        values=values,
        source_path=source_path,
    )


def format_fragment_summary(fragments: Sequence[Sequence[int]]) -> str:
    parts = []
    for idx, group in enumerate(fragments, start=1):
        atom_text = ", ".join(str(i) for i in group)
        parts.append(f"Fragment {idx}: [{atom_text}]")
    return "; ".join(parts)


def write_statistics_file(result: AnalysisResult, output_path: Path) -> None:
    minimum = min(result.values)
    maximum = max(result.values)
    mean = sum(result.values) / len(result.values)

    lines = [
        "# Molecular geometry statistics",
        f"# Source file: {result.source_path}",
        f"# Quantity: {result.geometry_name}",
        f"# Fragment definition: {format_fragment_summary(result.fragments)}",
        f"# Unit: {result.unit}",
        "#",
        "# Frame    Value",
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


def resolve_gnuplot_executable() -> str | None:
    return shutil.which(GNUPLOT_COMMAND)


def escape_gnuplot_text(text: str) -> str:
    return text.replace("'", "''")


def build_gnuplot_script(result: AnalysisResult, data_path: Path, png_path: Path) -> Path:
    plt_path = data_path.with_suffix(".plt")
    ylabel = f"{result.geometry_name} ({result.unit})"
    title = f"{result.geometry_name} vs Frame"
    data_name = data_path.name
    png_name = png_path.name

    script = f"""# Auto-generated by xyz_geometry_stats.py
reset
set terminal pngcairo size 1200,750 enhanced font "Arial,12"
set output '{escape_gnuplot_text(png_name)}'
set title '{escape_gnuplot_text(title)}'
set xlabel 'Frame'
set ylabel '{escape_gnuplot_text(ylabel)}'
set tics nomirror
set border lw 1.5
set grid lw 0.5 lc rgb '#CCCCCC'
plot '{escape_gnuplot_text(data_name)}' using 1:2 with lines lw 2 title '{escape_gnuplot_text(result.geometry_name)}'
set output
"""
    plt_path.write_text(script, encoding="utf-8")
    return plt_path


def run_gnuplot_plot(gnuplot_exe: str, plt_path: Path, png_path: Path) -> None:
    result = subprocess.run(
        [gnuplot_exe, plt_path.name],
        cwd=str(plt_path.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gnuplot failed (code {result.returncode}):\n{result.stderr or result.stdout}"
        )
    if not png_path.exists() or png_path.stat().st_size == 0:
        raise RuntimeError(
            f"Plot image was not created: {png_path}\n{result.stderr or result.stdout}"
        )


def wait_for_exit() -> None:
    input("Press ENTER to exit.")


def choose_geometry_type() -> str:
    print("\nAvailable geometric quantities:")
    print("  B  - Distance")
    print("  A  - Angle")
    print("  D  - Dihedral angle")
    print("  FP - Fragment-Plane distance")
    print("  PA - Plane-Plane angle")
    print("  PB - Plane-Plane distance")
    while True:
        choice = input("Select quantity to analyze (B/A/D/FP/PA/PB): ").strip().upper()
        if choice in GEOMETRY_TYPES:
            return choice
        print("Invalid choice. Please enter B, A, D, FP, PA, or PB.")


def load_structure_file() -> tuple[Path, list[Frame]]:
    while True:
        raw_path = prompt_nonempty("\nEnter path to the structure file (.xyz or .pdb): ")
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = (Path.cwd() / source_path).resolve()
        if not source_path.exists():
            print(f"Error: File not found: {source_path}")
            continue
        try:
            frames = load_frames_from_path(source_path)
            print(f"Loaded {len(frames)} frame(s) from: {source_path}")
            print(f"Format: {source_path.suffix.lower()}")
            print(f"Atoms per frame: {len(frames[0].atoms)}")
            return source_path, frames
        except ValueError as exc:
            print(f"Error while reading structure file: {exc}")


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


def run_analysis_round(source_path: Path, frames: list[Frame], round_index: int) -> None:
    geometry_key = choose_geometry_type()
    geometry_name, num_fragments, unit, min_atoms = GEOMETRY_TYPES[geometry_key]
    print(f"\nSelected quantity: {geometry_name} ({unit})")
    fragments = prompt_fragments(num_fragments, len(frames[0].atoms), min_atoms)

    print("\nComputing geometry across all frames...")
    result = analyze_frames(frames, geometry_key, fragments, source_path)

    output_path = prompt_output_path(source_path, round_index)
    write_statistics_file(result, output_path)
    print(f"\nStatistics saved to: {output_path}")

    gnuplot_exe = resolve_gnuplot_executable()
    gnuplot_label = gnuplot_exe or GNUPLOT_COMMAND
    if prompt_yes_no(f"\nPlot the results with gnuplot ({gnuplot_label})? [y/n]: "):
        if gnuplot_exe is None:
            print(
                f"Error: gnuplot executable not found in PATH. "
                f"Please ensure '{GNUPLOT_COMMAND}' is available."
            )
        else:
            png_path = output_path.with_suffix(".png")
            plt_path = build_gnuplot_script(result, output_path, png_path)
            try:
                run_gnuplot_plot(gnuplot_exe, plt_path, png_path)
                print(f"Plot saved to: {png_path}")
                print(f"Gnuplot script saved to: {plt_path}")
            except RuntimeError as exc:
                print(f"Plotting failed: {exc}")


def main() -> int:
    print("=== Molecular Geometry Statistics ===")

    try:
        source_path, frames = load_structure_file()

        round_index = 1
        while True:
            run_analysis_round(source_path, frames, round_index)
            round_index += 1
            if not prompt_yes_no(
                "\nAnalyze another geometric quantity with the same structure file? [y/n]: "
            ):
                break

        wait_for_exit()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 1
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        wait_for_exit()
        return 1


if __name__ == "__main__":
    sys.exit(main())
