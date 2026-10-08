@echo off
cd /d "%~dp0"
for /f "tokens=1,2 delims==" %%a in (.env) do (if "%%a"=="POSTGRES_USER" set PGU=%%b& if "%%a"=="POSTGRES_DB" set PGD=%%b)
docker compose exec -T postgres psql -U %PGU% -d %PGD% -At -c "SELECT id, filename, size_bytes, created_at FROM gis_upload ORDER BY created_at DESC" > agent-test\uploads.txt 2>&1
docker compose exec -T postgres psql -U %PGU% -d %PGD% -At -c "SELECT encode(data, 'base64') FROM gis_upload WHERE lower(filename) LIKE '%%.dxf' ORDER BY created_at DESC LIMIT 1" > agent-test\camp.b64 2>&1
echo DUMP-DONE >> agent-test\uploads.txt
