@echo off
cd /d "%~dp0"
docker compose cp agent-test\. backend:/tmp/at > agent-test\out.txt 2>&1
docker compose exec -T -e PYTHONPATH=/app backend python /tmp/at/driver.py /tmp/at/turn.json >> agent-test\out.txt 2>&1
echo TURN-DONE %errorlevel% >> agent-test\out.txt
