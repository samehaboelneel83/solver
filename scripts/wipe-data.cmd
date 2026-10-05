@echo off
REM ============================================================================
REM  wipe-data.cmd -- delete ALL business data from the platform, for good.
REM
REM  Kept:    user accounts, organizations, roles and permissions, API keys,
REM           SSO / SCIM set-up, solver licences, platform settings.
REM  Deleted: domains, record types, records, relationships, parameters,
REM           problems, models, drafts, scenarios, runs and solutions, map data
REM           and uploads, imports, predictors, suites, integrations, camp layouts,
REM           templates (the built-in ones come back when the backend starts),
REM           the audit log and record history, usage counters,
REM           the ClickHouse analytics tables,
REM           and every old backup (nightly dumps + WAL archive).
REM
REM  Usage:   scripts\wipe-data.cmd            preview, then asks before deleting
REM           scripts\wipe-data.cmd --yes      preview, then deletes without asking
REM           scripts\wipe-data.cmd --preview  only show what would be deleted
REM
REM  There is no undo: no copy is made, and the old backups are deleted too.
REM ============================================================================
setlocal
cd /d "%~dp0\.."

set "PGUSER=solver"
set "PGDB=solver"
set "CHDB=analytics"
set "BACKUPDIR="
if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="POSTGRES_USER" set "PGUSER=%%B"
    if /i "%%A"=="POSTGRES_DB" set "PGDB=%%B"
    if /i "%%A"=="CLICKHOUSE_DB" set "CHDB=%%B"
    if /i "%%A"=="SOLVER_BACKUP_DIR" set "BACKUPDIR=%%B"
  )
)
REM docker-compose.yml's default: a solver-backups folder beside this repository.
if "%BACKUPDIR%"=="" set "BACKUPDIR=%CD%\..\solver-backups"

echo.
echo === What would be deleted (nothing is changed yet) ===
echo.
docker compose exec -T postgres psql -U %PGUSER% -d %PGDB% -q -v ON_ERROR_STOP=1 -f - < scripts\wipe-data-preview.sql
if errorlevel 1 (
  echo Could not read the database. Is the stack running? Try: docker compose up -d
  exit /b 1
)
echo ClickHouse analytics tables (database %CHDB%^):
docker compose exec -T clickhouse clickhouse-client --query "SELECT name, total_rows FROM system.tables WHERE database = '%CHDB%' FORMAT PrettyCompact"
if errorlevel 1 echo   (ClickHouse is not running: its tables will be skipped^)
echo.
echo Backups folder: %BACKUPDIR%
if exist "%BACKUPDIR%" (dir /s /a-d "%BACKUPDIR%" | findstr /c:"File(s)") else (echo   ^(not found: nothing to delete^))
echo.

if /i "%~1"=="--preview" (
  echo Preview only: nothing was deleted.
  exit /b 0
)

echo This deletes everything listed above PERMANENTLY. There is no copy and no undo.
if /i "%~1"=="--yes" (
  echo Confirmed on the command line ^(--yes^).
  goto :wipe
)
set "ANSWER="
set /p "ANSWER=Type DELETE EVERYTHING to go ahead: "
if not "%ANSWER%"=="DELETE EVERYTHING" (
  echo Nothing was deleted.
  exit /b 1
)
:wipe

echo.
echo [1/5] Stopping the backend and the worker, so nothing writes meanwhile...
docker compose stop backend worker

echo [2/5] Deleting the data from Postgres (one transaction: all of it, or none)...
docker compose exec -T postgres psql -U %PGUSER% -d %PGDB% -v ON_ERROR_STOP=1 -f - < scripts\wipe-data.sql
if errorlevel 1 (
  echo FAILED: the database refused, so NOTHING was deleted from it. Backups were not touched.
  docker compose start backend worker
  exit /b 1
)

echo [3/5] Emptying the ClickHouse analytics tables...
for /f "usebackq delims=" %%T in (`docker compose exec -T clickhouse clickhouse-client --query "SELECT name FROM system.tables WHERE database = '%CHDB%' AND engine NOT LIKE '%%View%%'"`) do (
  echo   %%T
  docker compose exec -T clickhouse clickhouse-client --query "TRUNCATE TABLE %CHDB%.%%T"
)

echo [4/5] Deleting the old backups in %BACKUPDIR% ...
if exist "%BACKUPDIR%" (
  REM The folder itself stays: Postgres has it mounted and archives new WAL into it.
  del /f /s /q "%BACKUPDIR%\*" >nul 2>&1
  for /d %%D in ("%BACKUPDIR%\*") do rmdir /s /q "%%D"
)

echo [5/5] Starting the backend and the worker again...
docker compose start backend worker

echo.
echo Done. All business data is deleted; user accounts, roles and settings are kept.
echo Sign in as before. The built-in templates are recreated as the backend starts.
endlocal
