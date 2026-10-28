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
    echo Instale Python 3.10 ou superior com Add Python to PATH.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Nao foi possivel instalar as dependencias. Verifique a conexao.
  pause
  exit /b 1
)
echo ready>".venv\.synapse-ready-v07"
".venv\Scripts\python.exe" configurar_admin.py
pause
