@echo off
rem kushim-Befehl: startet die Projekt-venv. Der Ordner bin steht im Benutzer-PATH (siehe scripts/add-path.ps1).
"%~dp0..\.venv\Scripts\python.exe" -m kushim.cli %*
