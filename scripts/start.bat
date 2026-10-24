@echo off
rem ============================================================
rem  start.bat — Lance le bot complet en un double-clic :
rem    1. Le scanner (détection + trades + notifications)
rem    2. Le serveur du dashboard
rem    3. Ouvre le dashboard dans le navigateur
rem ============================================================
cd /d "%~dp0.."

start "Bot Forex Runner" cmd /k python -m forex.paper.runner
start "Copy Trading Runner" cmd /k python -m copytrading.runner
start "Dashboard Web" cmd /k python main.py

rem Laisser le serveur démarrer avant d'ouvrir le navigateur
timeout /t 4 /nobreak >nul
start http://localhost:8000/dashboard
