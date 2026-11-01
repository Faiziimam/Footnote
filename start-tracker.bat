@echo off
rem Double-click on Windows. Opens the tracker for the folder this file is in.
cd /d "%~dp0"
set PYTHONPATH=%CD%
python -m footnote --project "%CD%" ui
pause
