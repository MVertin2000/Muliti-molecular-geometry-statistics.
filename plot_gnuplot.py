#!/usr/bin/env python3
"""Build and run gnuplot scripts for Geom-Stats statistics files.

Can be invoked by Geom-Stats.py / Geom-Stats.exe (import) or standalone:

    python plot_gnuplot.py --data Geom.txt
    python plot_gnuplot.py --data Geom.txt --format svg
"""

from __future__ import annotations

import argparse
import configparser
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION = "1.5.5"
APP_DIR = Path(__file__).resolve().parent
LIB_DIR = APP_DIR / "Lib"
DEFAULT_SETTINGS = LIB_DIR / "settings.ini"

FORMAT_TERMINALS = {
    "png": "pngcairo",
    "pdf": "pdfcairo",
    "svg": "svg",
    "eps": "epscairo",
}

QUANTITY_RE = re.compile(r"^#\s*Quantity:\s*(.+)\s*$", re.IGNORECASE)
UNIT_RE = re.compile(r"^#\s*Unit:\s*(.+)\s*$", re.IGNORECASE)


@dataclass
class PlotMeta:
    quantity: str
    unit: str

    @property
    def ylabel(self) -> str:
        if self.unit:
            return f"{self.quantity} ({self.unit})"
        return self.quantity


@dataclass
class PlotSettings:
    format: str
    width: int
    height: int
    font_family: str
    base_font_size: int
    label_font_size: int
    key_font_size: int
    line_width: float
    border_line_width: float
    show_grid: bool
    grid_line_width: float
    grid_color: str
    show_key: bool
    xlabel: str
    ylabel: str
    gnuplot_command: str

    @property
    def terminal(self) -> str:
        return FORMAT_TERMINALS[self.format]


def escape_gnuplot_text(text: str) -> str:
    return text.replace("'", "''")


def parse_bool(value: str, *, default: bool = False) -> bool:
    text = value.strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_format(raw: str) -> str:
    fmt = raw.strip().lower().lstrip(".")
    if fmt not in FORMAT_TERMINALS:
        raise ValueError(
            f"Unsupported plot format {raw!r}. "
            f"Choose one of: {', '.join(FORMAT_TERMINALS)}."
        )
    return fmt


def load_plot_settings(path: Path) -> PlotSettings:
    if not path.exists():
        raise FileNotFoundError(f"Plot settings file not found: {path}")

    parser = configparser.ConfigParser()
    read_ok = parser.read(path, encoding="utf-8")
    if not read_ok:
        raise ValueError(f"Failed to read plot settings: {path}")

    output = parser["output"] if parser.has_section("output") else {}
    figure = parser["figure"] if parser.has_section("figure") else {}
    font = parser["font"] if parser.has_section("font") else {}
    style = parser["style"] if parser.has_section("style") else {}
    axes = parser["axes"] if parser.has_section("axes") else {}
    gnuplot = parser["gnuplot"] if parser.has_section("gnuplot") else {}

    fmt = normalize_format(output.get("format", "png"))

    return PlotSettings(
        format=fmt,
        width=int(figure.get("width", "1200")),
        height=int(figure.get("height", "750")),
        font_family=font.get("family", "Arial").strip() or "Arial",
        base_font_size=int(font.get("base_size", "18")),
        label_font_size=int(font.get("label_size", "20")),
        key_font_size=int(font.get("key_size", "18")),
        line_width=float(style.get("line_width", "2")),
        border_line_width=float(style.get("border_line_width", "1.5")),
        show_grid=parse_bool(style.get("show_grid", "true"), default=True),
        grid_line_width=float(style.get("grid_line_width", "0.5")),
        grid_color=style.get("grid_color", "#CCCCCC").strip() or "#CCCCCC",
        show_key=parse_bool(style.get("show_key", "true"), default=True),
        xlabel=axes.get("xlabel", "Step").strip() or "Step",
        ylabel=axes.get("ylabel", "").strip(),
        gnuplot_command=gnuplot.get("command", "gnuplot").strip() or "gnuplot",
    )


def parse_statistics_meta(data_path: Path) -> PlotMeta:
    quantity = "Value"
    unit = ""
    for line in data_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = QUANTITY_RE.match(line)
        if match:
            quantity = match.group(1).strip() or quantity
            continue
        match = UNIT_RE.match(line)
        if match:
            unit = match.group(1).strip()
    return PlotMeta(quantity=quantity, unit=unit)


def resolve_gnuplot_executable(command: str) -> str | None:
    return shutil.which(command)


def build_gnuplot_script(
    data_path: Path,
    plot_path: Path,
    settings: PlotSettings,
    meta: PlotMeta,
) -> Path:
    plt_path = data_path.with_suffix(".plt")
    ylabel = settings.ylabel or meta.ylabel
    font = settings.font_family
    base = settings.base_font_size
    label = settings.label_font_size
    key = settings.key_font_size

    grid_lines = ""
    if settings.show_grid:
        grid_lines = (
            f"set grid lw {settings.grid_line_width} "
            f"lc rgb '{escape_gnuplot_text(settings.grid_color)}'\n"
        )

    key_lines = "unset key\n"
    if settings.show_key:
        key_lines = f'set key font "{escape_gnuplot_text(font)},{key}"\n'

    format_note = (
        "# Format note: set terminal and set output extension must match.\n"
        "#   png -> pngcairo | pdf -> pdfcairo | svg -> svg | eps -> epscairo\n"
        "# Prefer editing settings.ini [output] format (Plot Part), then re-run this script.\n"
    )

    script = f"""# Auto-generated by plot_gnuplot.py (Version {VERSION})
{format_note}reset
set terminal {settings.terminal} size {settings.width},{settings.height} enhanced font "{escape_gnuplot_text(font)},{base}"
set output '{escape_gnuplot_text(plot_path.name)}'
set xtics font "{escape_gnuplot_text(font)},{base}"
set ytics font "{escape_gnuplot_text(font)},{base}"
set xlabel '{escape_gnuplot_text(settings.xlabel)}' font "{escape_gnuplot_text(font)},{label}"
set ylabel '{escape_gnuplot_text(ylabel)}' font "{escape_gnuplot_text(font)},{label}"
set tics nomirror
set border lw {settings.border_line_width}
{grid_lines}{key_lines}plot '{escape_gnuplot_text(data_path.name)}' using 1:2 with lines lw {settings.line_width} title '{escape_gnuplot_text(meta.quantity)}'
set output
"""
    plt_path.write_text(script, encoding="utf-8")
    return plt_path


def run_gnuplot(gnuplot_exe: str, plt_path: Path, plot_path: Path) -> None:
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

    stderr_text = result.stderr or ""
    if "Cannot find or open file" in stderr_text:
        raise RuntimeError(f"gnuplot data file error:\n{stderr_text}")
    if "unknown or ambiguous terminal" in stderr_text.lower():
        raise RuntimeError(
            f"gnuplot terminal is unavailable in this build:\n{stderr_text}"
        )

    if not plot_path.exists() or plot_path.stat().st_size == 0:
        raise RuntimeError(
            f"Plot file was not created: {plot_path}\n{result.stderr or result.stdout}"
        )


def plot_statistics_file(
    data_path: Path,
    settings_path: Path | None = None,
    *,
    format_override: str | None = None,
    output_stem: str | None = None,
) -> tuple[Path, Path]:
    """Create .plt and run gnuplot. Returns (plt_path, plot_path)."""
    data_path = data_path.resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"Statistics data file not found: {data_path}")

    settings = load_plot_settings(settings_path or DEFAULT_SETTINGS)
    if format_override:
        settings.format = normalize_format(format_override)

    meta = parse_statistics_meta(data_path)
    stem = output_stem.strip() if output_stem else data_path.stem
    plot_path = data_path.with_name(f"{stem}.{settings.format}")

    gnuplot_exe = resolve_gnuplot_executable(settings.gnuplot_command)
    if gnuplot_exe is None:
        raise FileNotFoundError(
            f"gnuplot executable not found in PATH "
            f"(command: {settings.gnuplot_command!r})."
        )

    plt_path = build_gnuplot_script(data_path, plot_path, settings, meta)
    run_gnuplot(gnuplot_exe, plt_path, plot_path)
    return plt_path, plot_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot Geom-Stats statistics .txt files with gnuplot."
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to statistics .txt file (e.g. Geom.txt).",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS),
        help=f"Path to settings.ini (default: {DEFAULT_SETTINGS}).",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMAT_TERMINALS),
        help="Override [output] format from settings (png/pdf/svg/eps).",
    )
    parser.add_argument(
        "--output-stem",
        help="Output file stem without extension (default: data file stem).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"plot_gnuplot.py {VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plt_path, plot_path = plot_statistics_file(
            Path(args.data),
            Path(args.settings),
            format_override=args.format,
            output_stem=args.output_stem,
        )
        print(f"Plot saved to: {plot_path}")
        print(f"Gnuplot script saved to: {plt_path}")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
