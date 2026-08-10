#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convert multi-frame XYZ trajectories into fake Gaussian geometry-optimization
output files readable by GaussView (OfakeG-style, opt-only).

Reference: http://sobereva.com/498
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

GRAD_MARKER = "GradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGrad"
PLACEHOLDER = "0.000100"
VERSION = "1.0.0"

# Negative floating-point literal (must contain a decimal point).
NEGATIVE_DECIMAL_RE = re.compile(r"-\d+\.\d+(?:[eE][+-]?\d+)?")

# Atomic numbers for common elements in quantum-chemistry XYZ files.
ATOMIC_NUMBERS: dict[str, int] = {
    "H": 1,
    "He": 2,
    "Li": 3,
    "Be": 4,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
    "Ne": 10,
    "Na": 11,
    "Mg": 12,
    "Al": 13,
    "Si": 14,
    "P": 15,
    "S": 16,
    "Cl": 17,
    "Ar": 18,
    "K": 19,
    "Ca": 20,
    "Sc": 21,
    "Ti": 22,
    "V": 23,
    "Cr": 24,
    "Mn": 25,
    "Fe": 26,
    "Co": 27,
    "Ni": 28,
    "Cu": 29,
    "Zn": 30,
    "Ga": 31,
    "Ge": 32,
    "As": 33,
    "Se": 34,
    "Br": 35,
    "Kr": 36,
    "Rb": 37,
    "Sr": 38,
    "Y": 39,
    "Zr": 40,
    "Nb": 41,
    "Mo": 42,
    "Tc": 43,
    "Ru": 44,
    "Rh": 45,
    "Pd": 46,
    "Ag": 47,
    "Cd": 48,
    "In": 49,
    "Sn": 50,
    "Sb": 51,
    "Te": 52,
    "I": 53,
    "Xe": 54,
    "Cs": 55,
    "Ba": 56,
    "La": 57,
    "Ce": 58,
    "Pr": 59,
    "Nd": 60,
    "Pm": 61,
    "Sm": 62,
    "Eu": 63,
    "Gd": 64,
    "Tb": 65,
    "Dy": 66,
    "Ho": 67,
    "Er": 68,
    "Tm": 69,
    "Yb": 70,
    "Lu": 71,
    "Hf": 72,
    "Ta": 73,
    "W": 74,
    "Re": 75,
    "Os": 76,
    "Ir": 77,
    "Pt": 78,
    "Au": 79,
    "Hg": 80,
    "Tl": 81,
    "Pb": 82,
    "Bi": 83,
    "Po": 84,
    "At": 85,
    "Rn": 86,
    "Fr": 87,
    "Ra": 88,
    "Ac": 89,
    "Th": 90,
    "Pa": 91,
    "U": 92,
    "Np": 93,
    "Pu": 94,
    "Am": 95,
    "Cm": 96,
    "Bk": 97,
    "Cf": 98,
    "Es": 99,
    "Fm": 100,
    "Md": 101,
    "No": 102,
    "Lr": 103,
}


class XYZParseError(ValueError):
    """Raised when an XYZ file cannot be parsed."""


def parse_energy(comment: str) -> str | None:
    """Extract electronic energy from an XYZ comment line, if present.

    Heuristic: the first negative decimal number in the comment is taken as
    the energy (e.g. ``-62.35898197``, ``E = -354.69``, ``energy: -62.35``).
    """
    match = NEGATIVE_DECIMAL_RE.search(comment)
    if not match:
        return None
    return match.group(0)


def atomic_number(symbol: str) -> int:
    key = symbol.strip().title()
    if key not in ATOMIC_NUMBERS:
        raise XYZParseError(f"Unknown element symbol: {symbol!r}")
    return ATOMIC_NUMBERS[key]


def parse_xyz_frames(path: Path) -> list[tuple[str, list[tuple[str, float, float, float]]]]:
    """Return [(comment, [(element, x, y, z), ...]), ...] for all frames."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.rstrip() for line in text.splitlines()]
    frames: list[tuple[str, list[tuple[str, float, float, float]]]] = []
    index = 0

    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        try:
            natoms = int(lines[index].strip())
        except ValueError as exc:
            raise XYZParseError(
                f"{path}: line {index + 1}: expected atom count, got {lines[index]!r}"
            ) from exc

        if natoms <= 0:
            raise XYZParseError(f"{path}: frame at line {index + 1} has invalid atom count")

        if index + 1 >= len(lines):
            raise XYZParseError(f"{path}: missing comment line for frame at line {index + 1}")

        comment = lines[index + 1]
        atoms: list[tuple[str, float, float, float]] = []
        atom_start = index + 2
        atom_end = atom_start + natoms

        if atom_end > len(lines):
            raise XYZParseError(
                f"{path}: frame at line {index + 1} expects {natoms} atoms, "
                f"but only {len(lines) - atom_start} coordinate lines remain"
            )

        for line_no, line in enumerate(lines[atom_start:atom_end], start=atom_start + 1):
            parts = line.split()
            if len(parts) < 4:
                raise XYZParseError(f"{path}: line {line_no}: invalid coordinate line")
            element = parts[0]
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError as exc:
                raise XYZParseError(f"{path}: line {line_no}: invalid coordinates") from exc
            atoms.append((element, x, y, z))

        frames.append((comment, atoms))
        index = atom_end

    if not frames:
        raise XYZParseError(f"{path}: no XYZ frames found")

    return frames


def format_energy(energy: str | None) -> str:
    if energy is None:
        return "0.000000"
    return energy


def write_header(out) -> None:
    out.write(" ! This file was generated by xyz2fakeg.py\n")
    out.write(" ! Inspired by OfakeG: http://sobereva.com/498\n")
    out.write("\n")
    out.write(" 0 basis functions\n")
    out.write(" 0 alpha electrons\n")
    out.write(" 0 beta electrons\n")
    out.write(f"{GRAD_MARKER}\n")
    out.write(f"{GRAD_MARKER}\n")
    out.write("\n")


def write_standard_orientation(out, atoms: list[tuple[str, float, float, float]]) -> None:
    out.write("                         Standard orientation:\n")
    out.write(" ---------------------------------------------------------------------\n")
    out.write(" Center     Atomic      Atomic             Coordinates (Angstroms)\n")
    out.write(" Number     Number       Type             X           Y           Z\n")
    out.write(" ---------------------------------------------------------------------\n")
    for center, (element, x, y, z) in enumerate(atoms, start=1):
        znum = atomic_number(element)
        out.write(
            f"{center:6d}{znum:10d}{0:12d}"
            f"{x:12.6f}{y:12.6f}{z:12.6f}\n"
        )
    out.write(" ---------------------------------------------------------------------\n")
    out.write("\n")


def write_scf_done(out, energy: str | None) -> None:
    out.write(f" SCF Done:      {format_energy(energy)}\n")
    out.write("\n")


def write_convergence_block(out, step: int) -> None:
    out.write(f"{GRAD_MARKER}\n")
    out.write(f" Step number{step:4d}\n")
    out.write("         Item               Value     Threshold  Converged?\n")
    if step >= 2:
        out.write(
            f" Energy change           {PLACEHOLDER:>10s}     {PLACEHOLDER:>10s}     YES\n"
        )
    out.write(
        f" Maximum Force            {PLACEHOLDER:>10s}     {PLACEHOLDER:>10s}     YES\n"
    )
    out.write(
        f" RMS     Force            {PLACEHOLDER:>10s}     {PLACEHOLDER:>10s}     YES\n"
    )
    out.write(
        f" Maximum Displacement     {PLACEHOLDER:>10s}     {PLACEHOLDER:>10s}     YES\n"
    )
    out.write(
        f" RMS     Displacement     {PLACEHOLDER:>10s}     {PLACEHOLDER:>10s}     YES\n"
    )
    out.write(f"{GRAD_MARKER}\n")
    out.write("\n")


def write_fake_out(
    frames: list[tuple[str, list[tuple[str, float, float, float]]]],
    out_path: Path,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    nframes = len(frames)
    energies = [parse_energy(comment) for comment, _ in frames]

    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        write_header(out)

        for index, (comment, atoms) in enumerate(frames, start=1):
            if progress is not None:
                progress(index, nframes)
            if index == 1:
                write_standard_orientation(out, atoms)
                write_scf_done(out, energies[0])
            else:
                write_convergence_block(out, index - 1)
                write_standard_orientation(out, atoms)
                write_scf_done(out, parse_energy(comment))

        write_convergence_block(out, nframes)
        out.write(" Normal termination of Gaussian\n")


def print_banner() -> None:
    print(" xyz2fakeg: Generate fake Gaussian output file based on multi-frame XYZ file")
    print(" Inspired by OfakeG (http://sobereva.com/498)")
    print(f" Version {VERSION}")
    print()


def print_processing_step(step: int, total: int) -> None:
    width = max(len(str(total)), 2)
    print(f" Processing Step{step:>{width + 10}d}")


def convert_xyz(
    path: Path,
    output: Path | None = None,
    *,
    verbose: bool = True,
) -> Path:
    frames = parse_xyz_frames(path)
    nframes = len(frames)
    out_path = output if output is not None else path.with_name(f"{path.stem}_fake.out")

    if verbose:
        print(f" Input file: {path}")
        print(f" Total number of frames: {nframes}")
        print()

    def on_progress(step: int, total: int) -> None:
        if verbose:
            print_processing_step(step, total)

    write_fake_out(frames, out_path, progress=on_progress if verbose else None)

    if verbose:
        print()
        print(f" Output file: {out_path}")
        print()

    return out_path


def collect_inputs(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(path.glob("*.xyz")))
        else:
            files.append(path)
    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert multi-frame XYZ files into fake Gaussian geometry-optimization "
            "output for GaussView visualization."
        ),
        add_help=True,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="XYZ file path (optional; if omitted, you will be prompted)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (only valid when exactly one XYZ input is given)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output (batch mode)",
    )
    return parser


def normalize_path(text: str) -> str:
    return text.strip().strip('"')


def prompt_xyz_path() -> str:
    return normalize_path(input(" Input XYZ file path (or drag file here): "))


def interactive_loop(output: Path | None = None) -> int:
    while True:
        choice = normalize_path(
            input(" Press Enter to quit, or input a new XYZ file path: ")
        )
        if not choice:
            return 0
        try:
            convert_xyz(Path(choice), output)
        except (XYZParseError, OSError) as exc:
            print(f" Error: {exc}", file=sys.stderr)
            print()


def run_file(path: Path, output: Path | None = None, *, verbose: bool = True) -> None:
    convert_xyz(path, output, verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    verbose = not args.quiet

    if args.output and len(args.inputs) != 1:
        parser.error("--output can only be used with a single input XYZ file")

    if verbose:
        print_banner()

    exit_code = 0
    output_path = Path(args.output) if args.output else None

    if args.inputs:
        input_files = collect_inputs(args.inputs)
        if not input_files:
            print("No XYZ files found.", file=sys.stderr)
            return 1
        for xyz_path in input_files:
            try:
                file_output = output_path if len(input_files) == 1 else None
                run_file(xyz_path, file_output, verbose=verbose)
            except (XYZParseError, OSError) as exc:
                print(f" Error processing {xyz_path}: {exc}", file=sys.stderr)
                exit_code = 1
    else:
        try:
            initial = prompt_xyz_path()
            if not initial:
                return 0
            run_file(Path(initial), output_path, verbose=verbose)
        except (XYZParseError, OSError) as exc:
            print(f" Error: {exc}", file=sys.stderr)
            exit_code = 1

    if verbose:
        exit_code = interactive_loop(output_path) or exit_code

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

