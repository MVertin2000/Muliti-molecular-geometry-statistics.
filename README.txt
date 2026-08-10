Geom-Stats 1.5.5
================

Interactive multi-frame molecular geometry statistics (B / A / D / FP / PA / PB / E).
Supports XYZ, PDB, ORCA, and Gaussian trajectories, with optional gnuplot plots,
VMD visualization, and a built-in Tk/Matplotlib preview.

Layout
------
  Geom-Stats.py          Main program
  plot_gnuplot.py        Gnuplot helper
  vmd_viewer.py          VMD helper
  mol_preview.py         Built-in preview helper
  xyz2fakeg.py           Utility
  Lib\                   Runtime assets (settings.ini, converters, changelogs, icon)
  examples\              Sample trajectories
  build_release.bat/.ps1 Windows packaging scripts
  build\                 PyInstaller specs (not required to run from source)

Requirements
------------
  - Python 3.x (3.13 tested)
  - gnuplot in PATH (only for plotting)
  - VMD installed (only for mode V)
  - matplotlib + tkinter (only for mode F preview)
  - Lib\GauIRC2xyz.exe / Lib\QCopt2xyz.exe for QC conversion helpers

How to run
----------
  python Geom-Stats.py

  Edit Lib\settings.ini for Plot / VMD / Preview options.

Release packages
----------------
  Windows binary packages are published on the GitHub Releases page
  (Geom-Stats-x.y.z.zip). Keep Geom-Stats.exe next to the Lib\ folder.

Homepage
--------
  https://github.com/MVertin2000/Muliti-molecular-geometry-statistics.
