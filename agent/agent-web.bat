@echo off
cd /d "%~dp0"
start "" http://localhost:8020
python solver_agent.py --web %*
