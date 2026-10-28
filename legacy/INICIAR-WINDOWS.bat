@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    python -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
  if errorlevel 1 (
    echo Instale Python 3.10 ou superior e marque Add Python to PATH.
    pause
    exit /b 1
  )
)
if not exist ".venv\.synapse-ready-v07" (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo A instalacao falhou. Confira sua conexao com a internet.
    pause
    exit /b 1
  )
  echo ready>".venv\.synapse-ready-v07"
)
".venv\Scripts\python.exe" run.py %*
pause
