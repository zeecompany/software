@echo off
REM ===========================================================================
REM  AURCO INVENTORY MANAGER - Windows build script
REM  Created by Zain Shami
REM
REM  Produces:
REM    dist\AURCO Inventory Manager\AURCO Inventory Manager.exe   (application)
REM    Output\AURCO_Inventory_Manager_Setup_1.0.0.exe             (installer)
REM ===========================================================================
setlocal
cd /d "%~dp0"
title AURCO Inventory Manager - Build

echo.
echo ============================================================
echo   AURCO INVENTORY MANAGER  -  Windows build
echo   Created by Zain Shami
echo ============================================================
echo.

REM ---------- 1. Python check -------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.10 - 3.13 from https://python.org
    echo         and tick "Add Python to PATH" during installation.
    pause & exit /b 1
)
python --version

REM ---------- 2. Virtual environment ------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM ---------- 3. Dependencies --------------------------------------------------
echo [2/5] Installing dependencies...
python -m pip install --upgrade pip  >nul
python -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] Dependency installation failed. & pause & exit /b 1 )
python -m pip install pyinstaller
if errorlevel 1 ( echo [ERROR] PyInstaller installation failed. & pause & exit /b 1 )

REM ---------- 4. Build the EXE -------------------------------------------------
echo [3/5] Building the Windows executable...
if exist dist  rmdir /s /q dist
if exist build rmdir /s /q build
pyinstaller packaging\aurco.spec --noconfirm --clean
if errorlevel 1 ( echo [ERROR] PyInstaller build failed. & pause & exit /b 1 )

echo.
echo [4/5] Executable ready:
echo       "%cd%\dist\AURCO Inventory Manager\AURCO Inventory Manager.exe"

REM ---------- 5. Installer (optional) -----------------------------------------
echo [5/5] Building the setup installer (Inno Setup)...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" packaging\installer.iss
    if errorlevel 1 (
        echo [WARN] Installer compilation failed - the EXE above still works.
    ) else (
        echo       Installer created in the Output folder.
    )
) else (
    echo [SKIP] Inno Setup 6 is not installed.
    echo        Download it from https://jrsoftware.org/isdl.php to build
    echo        the .EXE installer with desktop / Start Menu shortcuts.
)

echo.
echo [6/6] Creating desktop and Start Menu shortcuts...
call "%~dp0create_shortcut.bat" >nul 2>&1
if errorlevel 1 (
    echo        [SKIP] Run create_shortcut.bat manually if you want shortcuts.
) else (
    echo        Desktop and Start Menu shortcuts created.
)

echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo.
pause
