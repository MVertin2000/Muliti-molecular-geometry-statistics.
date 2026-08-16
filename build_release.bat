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
copy /y "%ROOT%\app_paths.py" "%REL%\source\app_paths.py" >nul
copy /y "%ROOT%\plot_gnuplot.py" "%REL%\source\plot_gnuplot.py" >nul
copy /y "%ROOT%\vmd_viewer.py" "%REL%\source\vmd_viewer.py" >nul
copy /y "%ROOT%\mol_preview.py" "%REL%\source\mol_preview.py" >nul
copy /y "%ROOT%\Lib\*.*" "%REL%\Lib\" >nul
if exist "%REL%\Lib\QCopt2xyz.exe" del /q "%REL%\Lib\QCopt2xyz.exe"
if exist "%REL%\Lib\geom-stats-app-icon.png" del /q "%REL%\Lib\geom-stats-app-icon.png"
if exist "%REL%\Lib\__pycache__" rmdir /s /q "%REL%\Lib\__pycache__"

> "%REL%\README.txt" (
echo Geom-Stats 1.6.0
echo ================
echo.
echo Layout
echo ------
echo   Geom-Stats.exe     Main program ^(helpers + preview stack compiled in^)
echo   Lib\               Editable settings.ini, VMD palette, GauIRC2xyz.exe
echo   source\            Python sources for users who prefer scripts
echo.
echo Requirements
echo ------------
echo   - Windows x64
echo   - gnuplot in PATH ^(only needed for plotting^)
echo   - VMD installed ^(only needed for mode V visualization^)
echo   - Lib\settings.ini ^(created beside the exe on first run if missing^)
echo     GauIRC2xyz source: http://sobereva.com/285
echo.
echo How to run ^(exe^)
echo ----------------
echo   1. Keep Geom-Stats.exe next to the Lib\ folder.
echo   2. Double-click Geom-Stats.exe, or run it from a console.
echo   3. Plot / VMD / preview settings: edit Lib\settings.ini
echo   4. Built-in preview ^(mode F^) does not need a system Python.
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
