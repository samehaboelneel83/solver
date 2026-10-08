@echo off
cd /d "%~dp0"
docker compose run --rm -T backend alembic upgrade head > agent-test\out.txt 2>&1
echo TURN-DONE %errorlevel% >> agent-test\out.txt
