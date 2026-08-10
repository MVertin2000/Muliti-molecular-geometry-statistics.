@echo off
REM Assemble release package (avoids PowerShell execution policy issues)
set ROOT=%~dp0
set ROOT=%ROOT:~0,-1%
set DIST=%ROOT%\build\dist\Geom-Stats.exe
set REL=%ROOT%\release\Geom-Stats

if not exist "%DIST%" (
  echo Missing %DIST%. Build with PyInstaller first.
  exit /b 1
)

if exist "%REL%" rmdir /s /q "%REL%"
mkdir "%REL%\Lib"
mkdir "%REL%\source"

copy /y "%DIST%" "%REL%\Geom-Stats.exe" >nul
copy /y "%ROOT%\Geom-Stats.py" "%REL%\source\Geom-Stats.py" >nul
copy /y "%ROOT%\xyz2fakeg.py" "%REL%\source\xyz2fakeg.py" >nul
copy /y "%ROOT%\plot_gnuplot.py" "%REL%\plot_gnuplot.py" >nul
copy /y "%ROOT%\vmd_viewer.py" "%REL%\vmd_viewer.py" >nul
copy /y "%ROOT%\mol_preview.py" "%REL%\mol_preview.py" >nul
copy /y "%ROOT%\plot_gnuplot.py" "%REL%\source\plot_gnuplot.py" >nul
copy /y "%ROOT%\vmd_viewer.py" "%REL%\source\vmd_viewer.py" >nul
copy /y "%ROOT%\mol_preview.py" "%REL%\source\mol_preview.py" >nul
copy /y "%ROOT%\Lib\*.*" "%REL%\Lib\" >nul
if exist "%REL%\Lib\__pycache__" rmdir /s /q "%REL%\Lib\__pycache__"

> "%REL%\README.txt" (
echo Geom-Stats 1.5.5
echo ================
echo.
echo Layout
echo ------
echo   Geom-Stats.exe     Main program ^(no Python required for core stats^)
echo   plot_gnuplot.py    Gnuplot interface ^(beside the exe^)
echo   vmd_viewer.py      VMD interface ^(beside the exe^)
echo   mol_preview.py     Built-in preview window ^(beside the exe^)
echo   Lib\               Settings, converters, and assets
echo   source\            Python sources for users who prefer scripts
echo.
echo Requirements
echo ------------
echo   - Windows x64
echo   - gnuplot in PATH ^(only needed for plotting^)
echo   - VMD installed ^(only needed for mode V visualization^)
echo   - Python + matplotlib/tkinter on PATH ^(only needed for mode F preview^)
echo   - Lib\GauIRC2xyz.exe ^(bundled^) for Gaussian IRC conversion
echo   - Lib\QCopt2xyz.exe ^(bundled^) for ORCA/Gaussian opt to XYZ
echo     GauIRC2xyz source: http://sobereva.com/285
echo.
echo How to run ^(exe^)
echo ----------------
echo   1. Keep Geom-Stats.exe, the three helper .py files, and Lib\ together.
echo   2. Double-click Geom-Stats.exe, or run it from a console.
echo   3. Plot / VMD / preview settings: edit Lib\settings.ini
echo.
echo How to run ^(source^)
echo -------------------
echo   cd ^<this folder^>
echo   python source\Geom-Stats.py
echo.
echo Notes
echo -----
echo   - Sample trajectories are not included in this package.
echo   - Antivirus / SmartScreen may warn on unsigned PyInstaller exes.
)

echo Release assembled at: %REL%
dir /s /b "%REL%"
