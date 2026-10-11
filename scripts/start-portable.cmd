@echo off
cd /d "%~dp0"
TableProof.exe
if errorlevel 1 pause
