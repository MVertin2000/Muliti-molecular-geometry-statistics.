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

foreach ($helper in @("plot_gnuplot.py", "vmd_viewer.py", "mol_preview.py", "app_paths.py")) {
    Copy-Item (Join-Path $ProjectRoot $helper) (Join-Path $ReleaseRoot "source\$helper")
}

$skipLibNames = @("QCopt2xyz.exe", "geom-stats-app-icon.png")
Get-ChildItem $LibSrc -File | Where-Object {
    $_.Extension -ne ".pyc" -and $skipLibNames -notcontains $_.Name
} | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $ReleaseRoot "Lib\$($_.Name)")
}

$Readme = @"
Geom-Stats 1.6.0
================

Layout
------
  Geom-Stats.exe     Main program (helpers + preview stack compiled in)
  Lib\               Editable settings.ini, VMD palette, GauIRC2xyz.exe
  source\            Python sources for users who prefer scripts

Requirements
------------
  - Windows x64
  - gnuplot in PATH (only needed for plotting)
  - VMD installed (only needed for mode V visualization)
  - Lib\settings.ini (created beside the exe on first run if missing)
    GauIRC2xyz source: http://sobereva.com/285

How to run (exe)
----------------
  1. Keep Geom-Stats.exe next to the Lib\ folder.
  2. Double-click Geom-Stats.exe, or run it from a console.
  3. Plot / VMD / preview settings: edit Lib\settings.ini
  4. Built-in preview (mode F) does not need a system Python.

How to run (source)
-------------------
  cd <this folder>
  python source\Geom-Stats.py

  Standalone replot (from source\):
  python source\plot_gnuplot.py --data Geom.txt

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
