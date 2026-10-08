@echo off
cd /d "%~dp0"
docker compose cp agent-test\quota.sql postgres:/tmp/quota.sql > agent-test\out.txt 2>&1
docker compose exec -T postgres sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -f /tmp/quota.sql" >> agent-test\out.txt 2>&1
echo TURN-DONE %errorlevel% >> agent-test\out.txt
