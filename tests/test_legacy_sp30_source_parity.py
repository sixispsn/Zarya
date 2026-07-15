"""Защита от расхождения Python-справочников с исходным legacy HTML."""
import re
from pathlib import Path

from app.data.sp30_tables import ALPHA_TABLE, CONSUMER_NORMS


LEGACY = Path(__file__).parents[1] / "legacy" / "sp30_calculator.html"


def test_all_consumer_norm_rows_are_present_verbatim_in_legacy():
    source = LEGACY.read_text(encoding="utf-8")
    block = source.split("const TBL = [", 1)[1].split("];", 1)[0]
    fields = ("qu_tot", "qu_h", "q_hr_tot", "q_hr_h", "q0_tot", "q0_c", "q0_h",
              "q0hr_tot", "q0hr_c", "q0hr_h")
    numeric = r"(-?[0-9.]+)"
    pattern = (
        r'\{label:"([^"]+)",\s*um:"([^"]+)",\s*'
        + r",\s*".join(f"{field}:{numeric}" for field in fields)
        + r"\s*\}"
    )
    parsed = {}
    for match in re.finditer(pattern, block):
        parsed[match.group(1)] = (match.group(2), tuple(map(float, match.groups()[2:])))
    assert len(CONSUMER_NORMS) == 29
    for norm in CONSUMER_NORMS.values():
        expected = tuple(float(getattr(norm, field)) for field in fields)
        assert parsed[norm.label] == (norm.unit, expected), norm.code


def test_every_alpha_table_pair_is_present_in_legacy():
    source = LEGACY.read_text(encoding="utf-8")
    block = source.split("const B2 = [", 1)[1].split("];", 1)[0]
    parsed = [(float(x), float(y)) for x, y in re.findall(
        r"\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]", block)]
    assert parsed == ALPHA_TABLE
