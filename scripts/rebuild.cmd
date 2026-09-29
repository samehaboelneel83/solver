@echo off
rem Windows version of scripts/rebuild.sh: rebuild the images, bring the
rem database up to the newest migrations, recreate the containers, and wait
rem until the backend and the frontend answer. Run it from the project folder:
rem     scripts\rebuild.cmd
setlocal

echo == Building backend, worker and frontend images ==
docker compose build backend worker frontend || goto :failed

echo == Applying database migrations ==
docker compose run --rm backend alembic upgrade head || goto :failed

echo == Recreating backend, worker and frontend containers ==
docker compose up -d --force-recreate backend worker frontend || goto :failed

echo == Checking backend health ==
call :wait http://localhost:8010/api/health backend || goto :failed

echo == Checking frontend is serving ==
call :wait http://localhost:3010/ frontend || goto :failed

echo == Rebuild complete: open http://localhost:3010 and press Ctrl+F5 ==
exit /b 0

rem Containers start before they accept connections: try 15 times, 2 s apart.
:wait
for /l %%i in (1,1,15) do (
    curl.exe -fs -o nul %1 && exit /b 0
    echo waiting for %2... (%%i/15^)
    timeout /t 2 /nobreak >nul
)
echo %2 did not become ready after 15 attempts
exit /b 1

:failed
echo.
echo Rebuild stopped: the step above failed. Its output says why.
exit /b 1
