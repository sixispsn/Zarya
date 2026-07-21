#!/bin/bash
set -e

cd "$(dirname "$0")"

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON=python3.12
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "Не найден Python 3.12. Установите его с https://www.python.org/downloads/"
  read -r -p "Нажмите Enter, чтобы закрыть окно."
  exit 1
fi

if [ ! -x "venv/bin/python" ]; then
  echo "Первый запуск: создаю локальное окружение…"
  "$PYTHON" -m venv venv
fi

if ! venv/bin/python -c "import fastapi, uvicorn, weasyprint, yaml, fontTools" >/dev/null 2>&1; then
  echo "Первый запуск: устанавливаю компоненты…"
  venv/bin/python -m pip install --upgrade pip
  venv/bin/python -m pip install -r requirements.txt
fi

exec venv/bin/python start_zarya.py
