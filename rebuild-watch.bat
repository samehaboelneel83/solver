@echo off
REM Problem Solver rebuild watcher. Start it once (double-click) and leave the window open.
REM Claude asks for a rebuild by creating rebuild.request in this folder; this window then runs
REM rebuild.bat and writes rebuild.status (running / done <code>) so Claude can see when it finished.
REM Close the window to stop it. Nothing else is watched or run.
cd /d "%~dp0"
title Problem Solver rebuild watcher - close to stop
echo watching since %date% %time%> rebuild.status
echo Watching %cd% for rebuild.request ... (close this window to stop)
:loop
if exist rebuild.request (
  del /q rebuild.request
  echo running %date% %time%> rebuild.status
  echo [%date% %time%] rebuild requested - building...
  call rebuild.bat
  findstr /b "DONE" rebuild.log
  for /f "tokens=2" %%e in ('findstr /b "DONE" rebuild.log') do echo done %%e %date% %time%> rebuild.status
  echo [%date% %time%] finished. Watching again...
)
timeout /t 5 /nobreak >nul
goto loop
