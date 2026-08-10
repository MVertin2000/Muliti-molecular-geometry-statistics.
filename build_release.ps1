# Assemble Geom-Stats release package: exe + Lib + source + README
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectRoot "Geom-Stats.py"))) {
    throw "Run this script from the Geom-Stats project root (Geom-Stats.py not found)."
}

$BuildDir = Join-Path $ProjectRoot "build"
$DistExe = Join-Path $BuildDir "dist\Geom-Stats.exe"
$ReleaseRoot = Join-Path $ProjectRoot "release\Geom-Stats"
$LibSrc = Join-Path $ProjectRoot "Lib"

Write-Host "Project root: $ProjectRoot"
Write-Host "Dist exe:     $DistExe"
Write-Host "Release root: $ReleaseRoot"

if (-not (Test-Path $DistExe)) {
    throw "Missing $DistExe. Build with PyInstaller first."
}

if (Test-Path $ReleaseRoot) {
    Remove-Item -Recurse -Force $ReleaseRoot
}
New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "Lib") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "source") | Out-Null

Copy-Item $DistExe (Join-Path $ReleaseRoot "Geom-Stats.exe")
Copy-Item (Join-Path $ProjectRoot "Geom-Stats.py") (Join-Path $ReleaseRoot "source\Geom-Stats.py")
Copy-Item (Join-Path $ProjectRoot "xyz2fakeg.py") (Join-Path $ReleaseRoot "source\xyz2fakeg.py")

foreach ($helper in @("plot_gnuplot.py", "vmd_viewer.py", "mol_preview.py")) {
    Copy-Item (Join-Path $ProjectRoot $helper) (Join-Path $ReleaseRoot $helper)
    Copy-Item (Join-Path $ProjectRoot $helper) (Join-Path $ReleaseRoot "source\$helper")
}

Get-ChildItem $LibSrc -File | Where-Object {
    $_.Extension -ne ".pyc"
} | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $ReleaseRoot "Lib\$($_.Name)")
}

$Readme = @"
Geom-Stats 1.5.5
================

Layout
------
  Geom-Stats.exe     Main program (no Python required for core stats)
  plot_gnuplot.py    Gnuplot interface (beside the exe)
  vmd_viewer.py      VMD interface (beside the exe)
  mol_preview.py     Built-in preview window (beside the exe)
  Lib\               Settings, converters, and assets
  source\            Python sources for users who prefer scripts

Requirements
------------
  - Windows x64
  - gnuplot in PATH (only needed for plotting)
  - VMD installed (only needed for mode V visualization)
  - Python + matplotlib/tkinter on PATH (only needed for mode F preview)
  - Lib\GauIRC2xyz.exe (bundled) for Gaussian IRC conversion
  - Lib\QCopt2xyz.exe (bundled) for ORCA/Gaussian opt to XYZ
    GauIRC2xyz source: http://sobereva.com/285

How to run (exe)
----------------
  1. Keep Geom-Stats.exe, the three helper .py files, and Lib\ together.
  2. Double-click Geom-Stats.exe, or run it from a console.
  3. Plot / VMD / preview settings: edit Lib\settings.ini
     (png / pdf / svg / eps). Terminal and extension stay in sync
     when using plot_gnuplot.py.

How to run (source)
-------------------
  cd <this folder>
  python source\Geom-Stats.py

  Standalone replot:
  python plot_gnuplot.py --data Geom.txt
  python plot_gnuplot.py --data Geom.txt --format svg

Notes
-----
  - Sample trajectories are not included in this package.
  - Antivirus / SmartScreen may warn on unsigned PyInstaller exes.
"@

Set-Content -Path (Join-Path $ReleaseRoot "README.txt") -Value $Readme -Encoding UTF8

Write-Host "Release assembled at: $ReleaseRoot"
Get-ChildItem $ReleaseRoot -Recurse -File | ForEach-Object {
    "{0,-50} {1,10}" -f $_.FullName.Substring($ReleaseRoot.Length + 1), $_.Length
}
