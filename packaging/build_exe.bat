@echo off
REM ---------------------------------------------------------------------------
REM Build PixelMuse.exe on Windows.
REM Run this from the project root:  packaging\build_exe.bat
REM Needs Python 3.10+ on PATH. Everything is installed into .venv-build.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

echo === PixelMuse EXE build ===
echo Project root: %CD%

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.10+ from python.org first.
    exit /b 1
)

if not exist ".venv-build" (
    echo Creating build virtual environment...
    python -m venv .venv-build || exit /b 1
)

call .venv-build\Scripts\activate.bat || exit /b 1

echo Installing dependencies...
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt pyinstaller pytest || exit /b 1

echo Running tests before packaging...
python -m pytest tests -q
if errorlevel 1 (
    echo Tests failed - refusing to build a broken EXE.
    exit /b 1
)

echo Building the executable...
python -m PyInstaller --clean --noconfirm packaging\pixelmuse.spec || exit /b 1

if exist "dist\PixelMuse.exe" (
    echo.
    echo Build finished: dist\PixelMuse.exe
    for %%F in ("dist\PixelMuse.exe") do echo Size: %%~zF bytes
) else (
    echo Build failed: dist\PixelMuse.exe was not created.
    exit /b 1
)

endlocal
