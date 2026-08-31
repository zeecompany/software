@echo off
REM ===========================================================================
REM  AURCO INVENTORY MANAGER - create Windows shortcuts
REM
REM  Creates a Desktop shortcut and a Start Menu entry for the application,
REM  whether you run the built .EXE or the Python source.
REM  Safe to run any time - it simply refreshes the shortcuts.
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AURCO Inventory Manager - Create Shortcuts

echo.
echo ============================================================
echo   AURCO INVENTORY MANAGER  -  Shortcut creator
echo ============================================================
echo.

set "APPNAME=AURCO Inventory Manager"
set "ICON=%cd%\assets\aurco.ico"
set "TARGET="
set "ARGS="
set "WORKDIR=%cd%"

REM ---------- 1. prefer the built executable --------------------------------
if exist "%cd%\dist\%APPNAME%\%APPNAME%.exe" (
    set "TARGET=%cd%\dist\%APPNAME%\%APPNAME%.exe"
    set "WORKDIR=%cd%\dist\%APPNAME%"
    echo [OK] Found the built application.
    goto :make
)

REM ---------- 2. an installed copy -------------------------------------------
if exist "%ProgramFiles%\AURCO\%APPNAME%\%APPNAME%.exe" (
    set "TARGET=%ProgramFiles%\AURCO\%APPNAME%\%APPNAME%.exe"
    set "WORKDIR=%ProgramFiles%\AURCO\%APPNAME%"
    echo [OK] Found the installed application.
    goto :make
)

REM ---------- 3. fall back to running from source ----------------------------
if exist "%cd%\.venv\Scripts\pythonw.exe" (
    set "TARGET=%cd%\.venv\Scripts\pythonw.exe"
    set "ARGS=%cd%\main.py"
    echo [OK] Using the project virtual environment ^(source mode^).
    goto :make
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('where pythonw') do set "TARGET=%%P"
    set "ARGS=%cd%\main.py"
    echo [OK] Using the system Python ^(source mode^).
    goto :make
)

echo [ERROR] Could not find the application or Python.
echo         Build it first with build_windows.bat, or install Python.
pause & exit /b 1

:make
if not exist "%ICON%" set "ICON=%TARGET%"

set "VBS=%TEMP%\aurco_shortcut.vbs"
> "%VBS%" echo Set oWS = WScript.CreateObject("WScript.Shell")
>>"%VBS%" echo sDesktop = oWS.SpecialFolders("Desktop")
>>"%VBS%" echo sPrograms = oWS.SpecialFolders("Programs")
>>"%VBS%" echo sGroup = sPrograms ^& "\AURCO"
>>"%VBS%" echo Set fso = CreateObject("Scripting.FileSystemObject")
>>"%VBS%" echo If Not fso.FolderExists(sGroup) Then fso.CreateFolder(sGroup)
>>"%VBS%" echo targets = Array(sDesktop ^& "\%APPNAME%.lnk", sGroup ^& "\%APPNAME%.lnk")
>>"%VBS%" echo For Each p In targets
>>"%VBS%" echo   Set s = oWS.CreateShortcut(p)
>>"%VBS%" echo   s.TargetPath = "%TARGET%"
>>"%VBS%" echo   s.Arguments = """%ARGS%"""
>>"%VBS%" echo   s.WorkingDirectory = "%WORKDIR%"
>>"%VBS%" echo   s.IconLocation = "%ICON%"
>>"%VBS%" echo   s.Description = "AURCO Inventory Manager - Inventory ^& Warehouse Management"
>>"%VBS%" echo   s.WindowStyle = 1
>>"%VBS%" echo   s.Save
>>"%VBS%" echo Next

cscript //nologo "%VBS%"
if errorlevel 1 (
    echo [ERROR] Could not create the shortcuts.
    del "%VBS%" >nul 2>&1
    pause & exit /b 1
)
del "%VBS%" >nul 2>&1

echo.
echo   Desktop shortcut ...... created
echo   Start Menu ^(AURCO^) .... created
echo   Target ................ %TARGET%
echo.
echo   Tip: right-click the Start Menu entry to pin it to the taskbar.
echo ============================================================
echo.
pause
