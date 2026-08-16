Geom-Stats 1.6.0
================

Interactive multi-frame molecular geometry statistics (B / A / D / FP / PA / PB / E).
Supports XYZ, PDB, ORCA, and Gaussian trajectories, with optional gnuplot plots,
VMD visualization, and a built-in Tk/Matplotlib preview.

Layout
------
  Geom-Stats.py          Main program
  app_paths.py           Shared source / frozen resource paths
  plot_gnuplot.py        Gnuplot helper
  vmd_viewer.py          VMD helper
  mol_preview.py         Built-in preview helper
  xyz2fakeg.py           Utility (also: Geom-Stats.exe --xyz2fakeg)
  Lib\                   Runtime assets (settings.ini, GauIRC2xyz, changelogs, icon)
  examples\              Sample trajectories
  build_release.bat/.ps1 Windows packaging scripts
  build\                 PyInstaller specs (not required to run from source)

Requirements
------------
  - Python 3.x (3.13 tested) when running from source
  - gnuplot in PATH (only for plotting)
  - VMD installed (only for mode V)
  - matplotlib + tkinter (source mode F preview; the Windows exe bundles them)
  - Lib\GauIRC2xyz.exe for Gaussian IRC conversion
    GauIRC2xyz source: http://sobereva.com/285

How to run
----------
  python Geom-Stats.py

  Edit Lib\settings.ini for Plot / VMD / Preview options
  (atom numbers / coordinate axes can also be toggled in the preview window).

Release packages
----------------
  Windows 1.6.0 is a single Geom-Stats.exe (helpers + preview + QC conversion
  compiled in). Keep it next to Lib\ so settings.ini stays editable.
  Built-in preview (mode F) does not need a system Python.

Homepage
--------
  https://github.com/MVertin2000/Muliti-molecular-geometry-statistics.
