"""Reconstruct approved historical HTML in memory; never write either copy.

These snapshots prove compatibility, not numerical correctness. The callers
retain the original fixed hashes as independent historical checks.
"""
from pathlib import Path


BUILDER = Path(__file__).resolve().parents[1] / "scripts/rebuild_working_legacy.py"
L08_NOTICE = (
    "<b>Рабочий legacy · 15.10.2026</b> — исправлены L01–L05, L07 (чистая циркуляция), "
    "L08 (нет подстановки NPSHa=8 м), DN65 и проверка минимума водомера."
)
L07_NOTICE = (
    "<b>Рабочий legacy · 06.10.2026</b> — исправлены L01–L05, L07 (чистая циркуляция), "
    "DN65 и проверка минимума водомера."
)


def pre_l08_builder_source() -> str:
    """Exclude only the separately approved L08 block and its dated notice."""
    source = BUILDER.read_text(encoding="utf-8")
    start_marker = "    # L08 (15.10.2026):"
    end_marker = "    # L07: separate blank inputs"
    for marker in (start_marker, end_marker, L08_NOTICE):
        if source.count(marker) != 1:
            raise ValueError(f"Historical builder anchor changed: {marker}")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return (source[:start] + source[end:]).replace(L08_NOTICE, L07_NOTICE, 1)


def build_pre_l08_legacy() -> str:
    namespace = {"__file__": str(BUILDER), "__name__": "compatibility_check"}
    exec(compile(pre_l08_builder_source(), str(BUILDER), "exec"), namespace)
    return namespace["build"]()
