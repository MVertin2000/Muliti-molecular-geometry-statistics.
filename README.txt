Geom-Stats 1.4.0
================

Layout
------
  Geom-Stats.exe   Main program (no Python required)
  Lib\             Runtime helpers (must sit beside the exe)
  source\          Python sources for users who prefer scripts

Requirements
------------
  - Windows x64
  - gnuplot in PATH (only needed for plotting)
  - Lib\GauIRC2xyz.exe (bundled) for Gaussian IRC conversion
    Source: http://sobereva.com/285

How to run (exe)
----------------
  1. Keep Geom-Stats.exe and the Lib\ folder in the same directory.
  2. Double-click Geom-Stats.exe, or run it from a console.
  3. Plot style / format: edit Lib\plot-settings.ini
     (png / pdf / svg / eps). Terminal and extension stay in sync
     when using Lib\plot_gnuplot.py.

How to run (source)
-------------------
  cd <this folder>
  python source\Geom-Stats.py

  Standalone replot:
  python Lib\plot_gnuplot.py --data Geom.txt
  python Lib\plot_gnuplot.py --data Geom.txt --format svg

Notes
-----
  - Sample trajectories are not included in this package.
  - Antivirus / SmartScreen may warn on unsigned PyInstaller exes.
