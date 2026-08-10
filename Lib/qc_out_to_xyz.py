#!/usr/bin/env python3
"""Convert ORCA / Gaussian geometry-optimization outputs to multi-frame XYZ.

Standalone / source usage:

    python Lib/qc_out_to_xyz.py job.out
    python Lib/qc_out_to_xyz.py job.log -o traj.xyz

Runtime component (preferred): Lib/QCopt2xyz.exe — same CLI, used by
vmd_viewer.py for temporary VMD trajectories.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION = "1.5.5"

ORCA_COORD_MARKER = "CARTESIAN COORDINATES (ANGSTROEM)"
ORCA_CYCLE_RE = re.compile(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", re.IGNORECASE)
ORCA_ENERGY_MARKER = "FINAL SINGLE POINT ENERGY"
GAUSSIAN_ENERGY_MARKER = "SCF Done"
NEGATIVE_DECIMAL_RE = re.compile(r"-\d+\.\d+(?:[eE][+-]?\d+)?")
GAUSSIAN_IRC_ROUTE_RE = re.compile(r"^\s*#\s*.*\bIRC\s*\(", re.IGNORECASE | re.MULTILINE)
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


@dataclass
class Atom:
    element: str
    x: float
    y: float
    z: float


@dataclass
class Frame:
    comment: str
    atoms: list[Atom]


def extract_negative_float_after_marker(text: str, marker: str) -> float | None:
    marker_index = text.find(marker)
    if marker_index == -1:
        return None
    match = NEGATIVE_DECIMAL_RE.search(text[marker_index + len(marker) :])
    if not match:
        return None
    return float(match.group(0))


def is_separator_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"-"}


def symbol_from_atomic_number(atomic_number: int) -> str:
    symbol = ATOMIC_NUMBER_TO_SYMBOL.get(atomic_number)
    if symbol is None:
        raise ValueError(f"Unsupported atomic number in Gaussian output: {atomic_number}")
    return symbol


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


def detect_qc_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in {".out", ".log"}:
        raise ValueError(
            f"Unsupported input for QC→XYZ conversion: {path.name}. "
            "Expected ORCA .out or Gaussian .log/.out."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    orca = is_orca_output(text)
    gaussian = is_gaussian_output(text)
    if orca and not gaussian:
        return "orca"
    if gaussian and not orca:
        return "gaussian"
    if orca:
        return "orca"
    if gaussian:
        return "gaussian"
    raise ValueError(
        f"Unable to identify ORCA/Gaussian optimization data in {path.name}."
    )


def find_orca_cycle_number(lines: list[str], coord_line_index: int) -> int | None:
    for offset in range(coord_line_index, max(coord_line_index - 30, -1), -1):
        match = ORCA_CYCLE_RE.search(lines[offset])
        if match:
            return int(match.group(1))
    return None


def find_orca_energy(lines: list[str], start_index: int) -> float | None:
    limit = min(start_index + 3000, len(lines))
    for index in range(start_index, limit):
        if ORCA_COORD_MARKER in lines[index] and index > start_index:
            break
        if ORCA_ENERGY_MARKER in lines[index]:
            energy = extract_negative_float_after_marker(lines[index], ORCA_ENERGY_MARKER)
            if energy is not None:
                return energy
    return None


def parse_orca_frames(path: Path) -> list[Frame]:
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
        frames.append(Frame(comment=comment, atoms=atoms))

    if not frames:
        raise ValueError("No ORCA Cartesian-coordinate blocks were found.")
    return frames


def read_gaussian_coordinates(lines: list[str], start_index: int) -> tuple[list[Atom], int]:
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
        atoms.append(
            Atom(
                symbol_from_atomic_number(int(match.group(1))),
                float(match.group(2)),
                float(match.group(3)),
                float(match.group(4)),
            )
        )
        index += 1
    return atoms, index


def find_gaussian_energy_after(lines: list[str], start_index: int) -> float | None:
    limit = min(start_index + 5000, len(lines))
    for index in range(start_index, limit):
        if GAUSSIAN_ENERGY_MARKER in lines[index]:
            energy = extract_negative_float_after_marker(lines[index], GAUSSIAN_ENERGY_MARKER)
            if energy is not None:
                return energy
    return None


def parse_gaussian_frames(path: Path) -> list[Frame]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    orientation_indices = [
        index for index, line in enumerate(lines) if "Standard orientation" in line
    ]
    if not orientation_indices:
        raise ValueError("No Gaussian standard-orientation blocks were found.")

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
        frames.append(Frame(comment=comment, atoms=atoms))

    if not frames:
        raise ValueError("No Gaussian standard-orientation blocks were found.")
    return frames


def write_xyz(frames: list[Frame], output_path: Path) -> None:
    chunks: list[str] = []
    for frame in frames:
        chunks.append(str(len(frame.atoms)))
        chunks.append(frame.comment)
        for atom in frame.atoms:
            chunks.append(f"{atom.element:<2} {atom.x:15.8f} {atom.y:15.8f} {atom.z:15.8f}")
    output_path.write_text("\n".join(chunks) + "\n", encoding="utf-8")


def convert_qc_output_to_xyz(input_path: Path, output_path: Path | None = None) -> Path:
    """Convert ORCA/Gaussian optimization output to multi-frame XYZ."""
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    fmt = detect_qc_format(input_path)
    if fmt == "orca":
        frames = parse_orca_frames(input_path)
    else:
        frames = parse_gaussian_frames(input_path)

    if output_path is None:
        output_path = input_path.with_suffix(".xyz")
    else:
        output_path = output_path.resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_xyz(frames, output_path)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert ORCA/Gaussian optimization outputs to multi-frame XYZ."
    )
    parser.add_argument("input", help="ORCA .out or Gaussian .log/.out file")
    parser.add_argument(
        "-o",
        "--output",
        help="Output XYZ path (default: same stem as input with .xyz)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"QCopt2xyz / qc_out_to_xyz.py {VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = convert_qc_output_to_xyz(
            Path(args.input),
            Path(args.output) if args.output else None,
        )
        fmt = detect_qc_format(Path(args.input).resolve())
        text = output.read_text(encoding="utf-8", errors="replace")
        # Count frames by atom-count lines that start frames (approx via blank-line free parse)
        nframes = sum(
            1
            for line in text.splitlines()
            if line.strip().isdigit()
        )
        print(f"Format: {fmt}")
        print(f"Frames written: {nframes}")
        print(f"XYZ saved to: {output}")
        return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
