@echo off
REM Rebuilds and restarts the app after the improvement-plan changes (written by Claude).
cd /d "%~dp0"
echo started %date% %time% > rebuild.log
docker compose build backend worker frontend >> rebuild.log 2>&1
docker compose up -d >> rebuild.log 2>&1
echo DONE %errorlevel% %date% %time% >> rebuild.log
