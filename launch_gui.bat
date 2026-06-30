@echo off
rem FT-60 -> FTM-300DR migrator (double-click to run). Needs CHIRP in _chirp\ (see README).
cd /d "%~dp0"
python ftm300dr_gui.py
pause
