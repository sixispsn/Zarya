#!/usr/bin/env python3
"""Локальный запуск Zarya с открытием рабочего места в браузере."""
from __future__ import annotations

import argparse
import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _configure_drawing_font() -> Path:
    """Найти TTF для подписей на схемах, не привязываясь к одному компьютеру."""
    configured = os.environ.get("OSIFONT_PATH")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(__file__).parent / "assets" / "osifont.ttf",
        Path.home() / ".fonts" / "osifont.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            os.environ["OSIFONT_PATH"] = str(candidate)
            return candidate
    raise SystemExit(
        "Не найден шрифт TTF для чертежей. Укажите путь в переменной "
        "OSIFONT_PATH и запустите программу повторно."
    )


def _open_when_ready(url: str) -> None:
    """Открыть браузер только после успешного старта веб-сервера."""
    health_url = url.rsplit("/", 1)[0] + "/health"
    for _ in range(120):
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный запуск Zarya")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    font = _configure_drawing_font()
    url = f"http://127.0.0.1:{args.port}/wizard"
    print("\nЗаря запускается локально.")
    print(f"Рабочее место: {url}")
    print(f"Шрифт схем: {font}")
    print("Для остановки закройте это окно или нажмите Ctrl+C.\n")

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "Не установлены зависимости. Запускайте через пусковой файл "
            "для вашей операционной системы."
        ) from exc
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
