#!/usr/bin/env python3
"""Built-in first-frame molecular preview for Geom-Stats (Multiwfn-style window).

Runs as a sidecar process with Tk + Matplotlib mplot3d. The parent CLI sends
JSON-lines on stdin (load / highlight / close). Mouse drag rotates; scroll or
toolbar zooms; press Q or click Quit to exit without affecting the CLI.

    python mol_preview.py --viewer
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app_paths import user_app_dir, user_lib_dir

VERSION = "1.6.0"
APP_DIR = user_app_dir()
LIB_DIR = user_lib_dir()
DEFAULT_SETTINGS = LIB_DIR / "settings.ini"
PREVIEW_SCRIPT = Path(__file__).resolve()

# Compact CPK-like element colors (RGB 0–1).
ELEMENT_COLORS: dict[str, tuple[float, float, float]] = {
    "H": (0.90, 0.90, 0.90),
    "C": (0.30, 0.30, 0.30),
    "N": (0.20, 0.20, 0.90),
    "O": (0.90, 0.15, 0.15),
    "F": (0.20, 0.90, 0.20),
    "P": (1.00, 0.60, 0.00),
    "S": (1.00, 0.85, 0.15),
    "CL": (0.15, 0.90, 0.15),
    "BR": (0.65, 0.20, 0.20),
    "I": (0.55, 0.10, 0.55),
    "B": (1.00, 0.70, 0.70),
    "SI": (0.85, 0.70, 0.45),
    "FE": (0.85, 0.45, 0.15),
    "CU": (0.80, 0.45, 0.20),
    "ZN": (0.50, 0.50, 0.70),
}
DEFAULT_COLOR = (0.75, 0.75, 0.75)

# Approximate covalent radii (Angstrom) for bond inference.
COVALENT_RADII: dict[str, float] = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "CL": 1.02,
    "BR": 1.20,
    "I": 1.39,
    "B": 0.84,
    "SI": 1.11,
    "FE": 1.32,
    "CU": 1.32,
    "ZN": 1.22,
}
DEFAULT_RADIUS = 1.0

HIGHLIGHT_COLORS = (
    (1.00, 0.25, 0.45),
    (0.00, 0.75, 0.85),
    (1.00, 0.65, 0.00),
    (0.55, 0.30, 0.90),
    (0.20, 0.85, 0.35),
    (0.95, 0.85, 0.15),
)


@dataclass
class PreviewSettings:
    show_bonds: bool = True
    show_labels: bool = True
    show_coordinates: bool = True
    label_fontsize: int = 8
    bond_cutoff_scale: float = 1.15
    atom_size: float = 60.0
    highlight_size: float = 140.0
    window_title: str = "Geom-Stats Preview (selected frame)"


@dataclass
class AtomRecord:
    index: int
    element: str
    xyz: tuple[float, float, float]


@dataclass
class PreviewSession:
    """Parent-side handle to a running preview process."""

    process: subprocess.Popen
    stderr_path: Path | None = None
    _closed: bool = field(default=False, init=False)

    def is_alive(self) -> bool:
        return (not self._closed) and self.process.poll() is None

    def send(self, payload: dict[str, Any]) -> bool:
        if not self.is_alive() or self.process.stdin is None:
            self._closed = True
            return False
        try:
            line = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
            self.process.stdin.write(line)
            self.process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            self._closed = True
            return False

    def set_highlights(self, groups: Sequence[Sequence[int]]) -> bool:
        payload_groups = [
            {
                "name": f"Fragment {i + 1}",
                "indices": [int(x) for x in group],
                "color": list(HIGHLIGHT_COLORS[i % len(HIGHLIGHT_COLORS)]),
            }
            for i, group in enumerate(groups)
            if group
        ]
        return self.send({"v": 1, "cmd": "highlight", "mode": "replace", "groups": payload_groups})

    def read_stderr(self) -> str:
        if self.stderr_path is None or not self.stderr_path.exists():
            return ""
        try:
            return self.stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    def close(self) -> None:
        if self._closed:
            return
        self.send({"v": 1, "cmd": "close"})
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        self._closed = True
        if self.stderr_path is not None:
            try:
                self.stderr_path.unlink(missing_ok=True)
            except OSError:
                pass


def resolve_viewer_command(settings_path: Path) -> list[str]:
    """Build argv to launch the Tk preview sidecar.

    Frozen builds re-enter the same executable with --preview-viewer.
    Source runs use pythonw/python plus this script.
    """
    settings_args = ["--settings", str(settings_path)]
    frozen = bool(getattr(sys, "frozen", False))

    if frozen:
        return [str(sys.executable), "--preview-viewer", *settings_args]

    python_exe = Path(sys.executable)
    if sys.platform == "win32":
        for candidate in (
            python_exe.with_name("pythonw.exe"),
            python_exe.parent / "pythonw.exe",
        ):
            if candidate.is_file():
                return [str(candidate), str(PREVIEW_SCRIPT), "--viewer", *settings_args]
    return [str(python_exe), str(PREVIEW_SCRIPT), "--viewer", *settings_args]


def parse_bool(value: str, *, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def load_preview_settings(path: Path) -> PreviewSettings:
    settings = PreviewSettings()
    if not path.exists():
        return settings
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["preview"] if parser.has_section("preview") else {}
    settings.show_bonds = parse_bool(section.get("show_bonds", "yes"), default=True)
    settings.show_labels = parse_bool(section.get("show_labels", "yes"), default=True)
    settings.show_coordinates = parse_bool(section.get("show_coordinates", "yes"), default=True)
    settings.label_fontsize = int(section.get("label_fontsize", "8"))
    settings.bond_cutoff_scale = float(section.get("bond_cutoff_scale", "1.15"))
    settings.atom_size = float(section.get("atom_size", "60"))
    settings.highlight_size = float(section.get("highlight_size", "140"))
    settings.window_title = (section.get("window_title") or settings.window_title).strip()
    return settings


def element_color(symbol: str) -> tuple[float, float, float]:
    return ELEMENT_COLORS.get(symbol.upper(), DEFAULT_COLOR)


def covalent_radius(symbol: str) -> float:
    return COVALENT_RADII.get(symbol.upper(), DEFAULT_RADIUS)


def infer_bonds(atoms: Sequence[AtomRecord], cutoff_scale: float) -> list[tuple[int, int]]:
    bonds: list[tuple[int, int]] = []
    n = len(atoms)
    for i in range(n):
        xi, yi, zi = atoms[i].xyz
        ri = covalent_radius(atoms[i].element)
        for j in range(i + 1, n):
            xj, yj, zj = atoms[j].xyz
            rj = covalent_radius(atoms[j].element)
            dx = xi - xj
            dy = yi - yj
            dz = zi - zj
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if dist <= (ri + rj) * cutoff_scale:
                bonds.append((i, j))
    return bonds


def atoms_from_frame_like(frame: Any) -> list[AtomRecord]:
    """Accept Geom-Stats Frame or a sequence of atom-like objects."""
    atom_list = getattr(frame, "atoms", frame)
    records: list[AtomRecord] = []
    for offset, atom in enumerate(atom_list, start=1):
        if hasattr(atom, "element"):
            element = str(atom.element).strip()
        else:
            element = str(atom[0]).strip()
        if hasattr(atom, "coords"):
            x, y, z = atom.coords
        elif hasattr(atom, "x"):
            x, y, z = float(atom.x), float(atom.y), float(atom.z)
        else:
            x, y, z = float(atom[1]), float(atom[2]), float(atom[3])
        records.append(AtomRecord(index=offset, element=element, xyz=(x, y, z)))
    return records


def start_preview(
    frame: Any,
    settings_path: Path | None = None,
    *,
    source_label: str = "",
) -> PreviewSession | None:
    """Launch the preview sidecar and load one frame of geometry."""
    settings_path = (settings_path or DEFAULT_SETTINGS).resolve()
    atoms = atoms_from_frame_like(frame)
    if not atoms:
        raise ValueError("Cannot preview an empty frame.")

    command = resolve_viewer_command(settings_path)

    # Capture child diagnostics without blocking on a PIPE buffer.
    stderr_file = tempfile.NamedTemporaryFile(
        prefix="geom_stats_preview_",
        suffix=".log",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    stderr_path = Path(stderr_file.name)

    env = os.environ.copy()
    # Force a GUI-capable backend in the sidecar (avoid Agg/headless defaults).
    env.setdefault("MPLBACKEND", "TkAgg")

    creationflags = 0
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        # Hide the extra console that a second Geom-Stats.exe would otherwise open.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            # Binary stdin avoids Windows text-mode pipe Errno 22 with line buffering.
            bufsize=0,
            env=env,
            cwd=str(APP_DIR),
            creationflags=creationflags,
        )
    except OSError as exc:
        stderr_file.close()
        stderr_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to launch molecular preview: {exc}") from exc
    finally:
        try:
            stderr_file.close()
        except OSError:
            pass

    session = PreviewSession(process=process, stderr_path=stderr_path)

    # Brief settle: if the viewer crashes on import, surface stderr clearly.
    time.sleep(0.25)
    if process.poll() is not None:
        detail = session.read_stderr() or f"exit code {process.returncode}"
        session.close()
        raise RuntimeError(f"Preview process exited during startup: {detail}")

    payload = {
        "v": 1,
        "cmd": "load",
        "frame": 1,
        "source": source_label,
        "atoms": [
            {
                "index": atom.index,
                "element": atom.element,
                "xyz": [atom.xyz[0], atom.xyz[1], atom.xyz[2]],
            }
            for atom in atoms
        ],
    }
    if not session.send(payload):
        detail = session.read_stderr() or f"exit code {process.poll()}"
        session.close()
        raise RuntimeError(f"Preview process exited before accepting geometry: {detail}")

    time.sleep(0.15)
    if process.poll() is not None:
        detail = session.read_stderr() or f"exit code {process.returncode}"
        session.close()
        raise RuntimeError(f"Preview process exited after load: {detail}")

    return session


# ---------------------------------------------------------------------------
# Viewer process
# ---------------------------------------------------------------------------


class MoleculePreviewApp:
    def __init__(self, settings: PreviewSettings) -> None:
        self.settings = settings
        self.cmd_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.atoms: list[AtomRecord] = []
        self.bonds: list[tuple[int, int]] = []
        self.highlight_groups: list[dict[str, Any]] = []
        self._artists: list[Any] = []

        import matplotlib

        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title(settings.window_title)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_viewer)
        self.root.bind("<KeyPress-q>", lambda _e: self.quit_viewer())
        self.root.bind("<KeyPress-Q>", lambda _e: self.quit_viewer())

        top = tk.Frame(self.root)
        top.pack(side=tk.TOP, fill=tk.X)
        tk.Label(
            top,
            text="Drag: rotate  |  Scroll/toolbar: zoom  |  Q or Quit: close",
            anchor="w",
        ).pack(side=tk.LEFT, padx=6, pady=4)
        tk.Button(top, text="Quit", command=self.quit_viewer, width=8).pack(
            side=tk.RIGHT, padx=6, pady=4
        )
        self.show_labels_var = tk.BooleanVar(value=settings.show_labels)
        self.show_coordinates_var = tk.BooleanVar(value=settings.show_coordinates)
        tk.Checkbutton(
            top,
            text="Coordinates",
            variable=self.show_coordinates_var,
            command=self._on_display_toggle,
        ).pack(side=tk.RIGHT, padx=4, pady=4)
        tk.Checkbutton(
            top,
            text="Atom numbers",
            variable=self.show_labels_var,
            command=self._on_display_toggle,
        ).pack(side=tk.RIGHT, padx=4, pady=4)

        self.fig = Figure(figsize=(7.2, 6.2), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, self.root)
        toolbar.update()

        self.status = tk.StringVar(value="Waiting for structure from Geom-Stats...")
        tk.Label(self.root, textvariable=self.status, anchor="w").pack(
            side=tk.BOTTOM, fill=tk.X, padx=6, pady=2
        )

        self.root.after(50, self._poll_commands)

    def _on_display_toggle(self) -> None:
        self.settings.show_labels = bool(self.show_labels_var.get())
        self.settings.show_coordinates = bool(self.show_coordinates_var.get())
        self._redraw()

    def _style_axes(self) -> None:
        if self.settings.show_coordinates:
            self.ax.set_axis_on()
            self.ax.set_xlabel("X (Å)")
            self.ax.set_ylabel("Y (Å)")
            self.ax.set_zlabel("Z (Å)")
            self.ax.xaxis.pane.fill = False
            self.ax.yaxis.pane.fill = False
            self.ax.zaxis.pane.fill = False
            self.ax.grid(False)
        else:
            self.ax.set_axis_off()

    def quit_viewer(self) -> None:
        try:
            self.root.quit()
        finally:
            self.root.destroy()

    def _poll_commands(self) -> None:
        try:
            while True:
                payload = self.cmd_queue.get_nowait()
                self._handle_command(payload)
        except queue.Empty:
            pass
        try:
            self.root.after(50, self._poll_commands)
        except self.tk.TclError:
            pass

    def _handle_command(self, payload: dict[str, Any]) -> None:
        cmd = str(payload.get("cmd", "")).lower()
        if cmd == "load":
            raw_atoms = payload.get("atoms") or []
            self.atoms = []
            for item in raw_atoms:
                xyz = item.get("xyz") or [0.0, 0.0, 0.0]
                self.atoms.append(
                    AtomRecord(
                        index=int(item["index"]),
                        element=str(item.get("element", "X")),
                        xyz=(float(xyz[0]), float(xyz[1]), float(xyz[2])),
                    )
                )
            self.bonds = (
                infer_bonds(self.atoms, self.settings.bond_cutoff_scale)
                if self.settings.show_bonds
                else []
            )
            self.highlight_groups = []
            source = payload.get("source") or ""
            self.status.set(
                f"Frame 1 · {len(self.atoms)} atoms"
                + (f" · {source}" if source else "")
                + " · press Q to quit"
            )
            self._redraw()
        elif cmd == "highlight":
            self.highlight_groups = list(payload.get("groups") or [])
            n = sum(len(g.get("indices") or []) for g in self.highlight_groups)
            self.status.set(f"Highlight: {n} atom(s) in {len(self.highlight_groups)} group(s)")
            self._redraw()
        elif cmd == "close":
            self.quit_viewer()

    def _clear_artists(self) -> None:
        for artist in self._artists:
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
        self._artists.clear()
        # Also clear leftover text collections on the axes.
        while self.ax.texts:
            try:
                self.ax.texts[0].remove()
            except (ValueError, NotImplementedError, IndexError):
                break

    def _set_equal_aspect(self) -> None:
        if not self.atoms:
            return
        xs = [a.xyz[0] for a in self.atoms]
        ys = [a.xyz[1] for a in self.atoms]
        zs = [a.xyz[2] for a in self.atoms]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        z0, z1 = min(zs), max(zs)
        cx = 0.5 * (x0 + x1)
        cy = 0.5 * (y0 + y1)
        cz = 0.5 * (z0 + z1)
        span = max(x1 - x0, y1 - y0, z1 - z0, 1.0) * 0.55
        self.ax.set_xlim(cx - span, cx + span)
        self.ax.set_ylim(cy - span, cy + span)
        self.ax.set_zlim(cz - span, cz + span)

    def _redraw(self) -> None:
        elev = self.ax.elev
        azim = self.ax.azim
        self._clear_artists()
        self.ax.cla()
        self._style_axes()
        self.ax.view_init(elev=elev, azim=azim)

        if not self.atoms:
            self.canvas.draw_idle()
            return

        if self.settings.show_bonds:
            for i, j in self.bonds:
                xi, yi, zi = self.atoms[i].xyz
                xj, yj, zj = self.atoms[j].xyz
                (line,) = self.ax.plot(
                    [xi, xj], [yi, yj], [zi, zj], color="0.55", linewidth=1.2, zorder=1
                )
                self._artists.append(line)

        xs = [a.xyz[0] for a in self.atoms]
        ys = [a.xyz[1] for a in self.atoms]
        zs = [a.xyz[2] for a in self.atoms]
        colors = [element_color(a.element) for a in self.atoms]
        scatter = self.ax.scatter(
            xs, ys, zs, c=colors, s=self.settings.atom_size, depthshade=True, zorder=2
        )
        self._artists.append(scatter)

        highlighted: set[int] = set()
        for group in self.highlight_groups:
            indices = [int(i) for i in (group.get("indices") or [])]
            color = group.get("color") or list(HIGHLIGHT_COLORS[0])
            hx, hy, hz = [], [], []
            for index in indices:
                if 1 <= index <= len(self.atoms):
                    highlighted.add(index)
                    x, y, z = self.atoms[index - 1].xyz
                    hx.append(x)
                    hy.append(y)
                    hz.append(z)
            if hx:
                hs = self.ax.scatter(
                    hx,
                    hy,
                    hz,
                    c=[tuple(color)],
                    s=self.settings.highlight_size,
                    depthshade=False,
                    edgecolors="k",
                    linewidths=0.6,
                    zorder=4,
                )
                self._artists.append(hs)

        if self.settings.show_labels:
            for atom in self.atoms:
                weight = "bold" if atom.index in highlighted else "normal"
                color = "0.05" if atom.index in highlighted else "0.2"
                text = self.ax.text(
                    atom.xyz[0],
                    atom.xyz[1],
                    atom.xyz[2],
                    f" {atom.index}",
                    fontsize=self.settings.label_fontsize,
                    color=color,
                    fontweight=weight,
                    zorder=5,
                )
                self._artists.append(text)

        self._set_equal_aspect()
        self.canvas.draw_idle()

    def run(self) -> None:
        self.root.mainloop()


def stdin_reader(cmd_queue: queue.Queue[dict[str, Any]]) -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        cmd_queue.put(payload)
        if str(payload.get("cmd", "")).lower() == "close":
            break


def run_viewer(settings_path: Path) -> int:
    settings = load_preview_settings(settings_path)
    try:
        app = MoleculePreviewApp(settings)
    except ImportError as exc:
        print(
            f"Error: molecular preview requires matplotlib and tkinter ({exc}).",
            file=sys.stderr,
        )
        return 1

    reader = threading.Thread(target=stdin_reader, args=(app.cmd_queue,), daemon=True)
    reader.start()
    app.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Geom-Stats built-in molecular preview.")
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="Run as sidecar GUI (reads JSON-lines from stdin).",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS),
        help=f"Path to settings.ini (default: {DEFAULT_SETTINGS})",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mol_preview.py {VERSION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.viewer:
        build_parser().print_help()
        return 2
    return run_viewer(Path(args.settings))


if __name__ == "__main__":
    raise SystemExit(main())
