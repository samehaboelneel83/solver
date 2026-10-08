@echo off
cd /d "%~dp0"
docker compose cp agent-test\. backend:/tmp/at > agent-test\out.txt 2>&1
docker compose exec -T -e PYTHONPATH=/app backend python /tmp/at/check.py >> agent-test\out.txt 2>&1
docker compose logs --since 90m --tail 400 backend worker > agent-test\logs.txt 2>&1
docker compose ps >> agent-test\out.txt 2>&1
echo TURN-DONE %errorlevel% >> agent-test\out.txt
