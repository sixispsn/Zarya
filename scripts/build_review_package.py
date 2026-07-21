#!/usr/bin/env python3
"""Собрать ZIP исходной версии Zarya для локальной проверки."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE_ROOT = "Zarya-review"
ROOT_FILES = (
    "README.md",
    "requirements.txt",
    "start_zarya.py",
    "Запустить Зарю.command",
    "Запустить Зарю.bat",
)


def _revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _package_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for folder in ("app", "demo"):
        files.extend(
            path for path in (ROOT / folder).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        )
    return files


def main() -> None:
    DIST.mkdir(exist_ok=True)
    target = DIST / f"Zarya-review-{_revision()}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _package_files():
            archive.write(path, f"{PACKAGE_ROOT}/{path.relative_to(ROOT)}")
    print(target)


if __name__ == "__main__":
    main()
