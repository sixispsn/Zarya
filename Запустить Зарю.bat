@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3.12"
) else (
  where python >nul 2>nul
  if %errorlevel% neq 0 goto :no_python
  set "PYTHON=python"
)

if not exist "venv\Scripts\python.exe" (
  echo Первый запуск: создаю локальное окружение...
  %PYTHON% -m venv venv || goto :failed
)

"venv\Scripts\python.exe" -c "import fastapi, uvicorn, weasyprint, yaml, fontTools" >nul 2>nul
if %errorlevel% neq 0 (
  echo Первый запуск: устанавливаю компоненты...
  "venv\Scripts\python.exe" -m pip install --upgrade pip || goto :failed
  "venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
)

"venv\Scripts\python.exe" start_zarya.py
goto :eof

:no_python
echo Не найден Python 3.12. Установите его с https://www.python.org/downloads/
goto :failed

:failed
echo.
echo Запуск не выполнен. Скопируйте текст ошибки разработчику.
pause
