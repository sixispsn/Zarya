"""Защита от расхождения Python-справочников с исходным legacy HTML."""
import re
from pathlib import Path

from app.data.sp30_tables import ALPHA_TABLE, CONSUMER_NORMS
from app.data.pumps import PUMPS
from app.data.fire_tables import FIRE_NOZZLE_TABLE


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


def test_every_fire_nozzle_row_matches_legacy_source():
    source = LEGACY.read_text(encoding="utf-8")
    block = source.split("const T73 = {", 1)[1].split("};", 1)[0]
    parsed = {
        tuple(map(int, key.split("_"))): (float(q), float(p))
        for key, q, p in re.findall(
            r"'([0-9_]+)'\s*:\s*\{q:\s*([0-9.]+),\s*p:\s*([0-9.]+)\}",
            block,
        )
    }
    expected = {key: (row.q, row.p) for key, row in FIRE_NOZZLE_TABLE.items()}
    assert len(parsed) == 108
    assert parsed == expected


def test_every_pump_and_curve_point_matches_legacy_source():
    source = LEGACY.read_text(encoding="utf-8")
    block = source.split("const PUMP_CURVES = [", 1)[1].split("];", 1)[0]
    pattern = re.compile(
        r"model:\s*'([^']+)'.*?brand:\s*'([^']+)'.*?type:\s*'([^']+)'.*?"
        r"P_kw:\s*([0-9.]+).*?P_max_bar:\s*([0-9.]+).*?T_max:\s*([0-9.]+).*?"
        r"NPSHr:\s*([0-9.]+).*?Q_opt:\s*([0-9.]+).*?note:\s*'([^']+)'.*?"
        r"curve:\s*\[(.*?)\]",
        re.S,
    )
    parsed = {}
    for match in pattern.finditer(block):
        points = [(float(q), float(h)) for q, h in re.findall(
            r"\{q:\s*([0-9.]+),\s*h:\s*([0-9.]+)\}", match.group(10))]
        parsed[match.group(1)] = {
            "brand": match.group(2), "type": match.group(3),
            "p_kw": float(match.group(4)), "p_max_bar": float(match.group(5)),
            "t_max": float(match.group(6)), "npshr": float(match.group(7)),
            "q_opt": float(match.group(8)), "note": match.group(9), "curve": points,
        }
    assert len(parsed) == len(PUMPS)
    for pump in PUMPS:
        assert parsed[pump.model] == {
            "brand": pump.brand, "type": pump.type, "p_kw": pump.p_kw,
            "p_max_bar": pump.p_max_bar, "t_max": pump.t_max,
            "npshr": pump.npshr, "q_opt": pump.q_opt, "note": pump.note,
            "curve": [(point.q, point.h) for point in pump.curve],
        }


def test_python_pump_system_curve_formula_is_literal_legacy_formula():
    source = LEGACY.read_text(encoding="utf-8")
    function = source.split("function calcPumpHead()", 1)[1].split(
        "// Подбор насосов", 1)[0]
    compact = re.sub(r"\s+", " ", function)
    assert "const Hp = H_geom + H_l + H_pr - H_gar;" in compact
    assert "const H_stat = H_gar > 0 ? H_gar : 0;" in compact
    assert "? (Hp_display - H_stat) / (Q_des * Q_des) : 0.1;" in compact
