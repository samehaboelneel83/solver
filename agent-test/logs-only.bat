@echo off
cd /d "%~dp0"
docker compose logs --since 30m backend > agent-test\logs.txt 2>&1
echo TURN-DONE >> agent-test\logs.txt
