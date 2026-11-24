@echo off
rem ==============================================================================
rem Local LLM Music Renaming & Tagging Pipeline - Windows Launcher
rem Launches the PyQt6 GUI application using the local environment.
rem ==============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Detect Python environment
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_BIN=python"
    ) else (
        echo [ERROR] Python was not found in PATH or in .venv.
        echo Please install Python 3.10+ and add it to your PATH.
        pause
        exit /b 1
    )
)

rem Add modular source directory to Python module search path
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

rem Launch PyQt6 GUI
"%PYTHON_BIN%" "%~dp0src\gui_app.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%.
    pause
)
