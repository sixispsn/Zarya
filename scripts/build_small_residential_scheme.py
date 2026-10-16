"""Explicit proposed topology for the supplied two-floor/eight-apartment plans."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess

from app.calc.sewer_outlet_depth import preliminary_k1_frost_bound
from app.intake.yaml_io import load_request_file
from app.pz.small_residential_preview import build_small_residential_preview, generate_small_residential_pdf
from app.pz.wastewater_basement_profile import basement_profile_from_request
from app.pz.small_residential_combined import generate_small_residential_combined_pdf
from app.pz.small_residential_section import generate_small_residential_section_pdf
from app.pz.small_residential_basement_proposal import educational_basement_proposal


def verify_calculated_legacy(root: Path) -> str:
    """Fail before PDF export if the executable legacy reference differs."""
    from app.calc.storm import StormInput, calculate_storm
    from app.calc.water_demand import ConsumerGroup, calculate_water_demand
    from app.data.storm_cities import STORM_CITIES, GAMMA_PERIOD

    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("Executable legacy check needs Node; set NODE_BINARY")
    params = [(c, p, f, w) for c in STORM_CITIES.values() for p in GAMMA_PERIOD
              for f, w in ((252., 0.), (63., 0.), (1234.56, 789.12))]
    result = subprocess.run([node, str(root / "scripts/legacy_rainwater_reference.mjs")],
                            input=json.dumps({"cases": [dict(city=c.name, period=p, roof=f, walls=w)
                                                       for c, p, f, w in params], "residents": [5, 20, 500]}),
                            capture_output=True, text=True, check=True)
    ref = json.loads(result.stdout)
    for (c, p, f, w), expected in zip(params, ref["cases"], strict=True):
        actual = calculate_storm(StormInput(c.code, f, w, p))
        if (actual.q_total_l_per_s, actual.q5, actual.f_calculated_m2) != (
                expected["flow_lps"], expected["q5"], expected["area"]):
            raise ValueError(f"Legacy rain parity failed: {c.code}, P={p}; export stopped")
    for count, expected in zip((5, 20, 500), ref["residents"], strict=True):
        water = calculate_water_demand([ConsumerGroup("residential_full_bath", count)])
        if (water.total.q_sec, water.total.q_hr, water.sewage_flow) != (
                expected["total_lps"], expected["hourly_m3"], expected["sewage_lps"]):
            raise ValueError("Legacy sewage parity failed; export stopped")
    return ref["rain_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    views = parser.add_mutually_exclusive_group()
    views.add_argument("--separate", action="store_true", help="Previous two-sheet K1/K2 presentation")
    views.add_argument("--inventory", action="store_true", help="Previous all-apartment references/detail-A sheet")
    views.add_argument("--basement-proposal", action="store_true", help="Explicit educational K1 grade/envelope study, not basement AR")
    views.add_argument("--calculated", action="store_true", help="Legacy-verified K1/K2 study: one A2 scheme plus calculation PDF")
    views.add_argument("--demo", action="store_true", help="One K1/K2 cutaway with full-size slopes and compact legend; engineering report stays separate")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    req = load_request_file(str(root / "demo/residential_2floors_8apartments.yaml"))
    ground, frost = req.wastewater_ground_relative_elevation_m, req.wastewater_frost_depth_m
    if ground is None or frost is None:
        raise ValueError("ground and frost inputs required")
    bound = preliminary_k1_frost_bound(
        ground_elevation_m=ground, zero_temperature_depth_m=frost, diameter_mm=110,
    )
    basement = basement_profile_from_request(
        req, proposed_invert_m=bound.highest_invert_m, preview_dn_mm=100,
        proposed_invert_basis="Условие: заданная глубина принята как глубина нулевой температуры; СП 32, 6.2.4.",
    )
    model = build_small_residential_preview(
        req, basement=basement,
        source_ref="Два исходных JPG-плана; ручное чтение мокрых зон. Разводка предложена, не извлечена из АР.",
        proposed_shafts=4, branch_outer_mm=50, stack_outer_mm=110,
        include_roof=True,
    )
    if args.demo:
        from app.pz.small_residential_calculation import calculate_residential_study
        verify_calculated_legacy(root)
        calculation = calculate_residential_study(model)
        print(generate_small_residential_section_pdf(
            str(root / "output/pdf/Жилой_дом_8_квартир_К1_К2_принципиальная.pdf"), model,
            calculation=calculation, compact_demo=True))
    elif args.calculated:
        from app.pz.small_residential_calculation import calculate_residential_study
        from app.pz.small_residential_calculation_pdf import generate_residential_calculation_pdf
        source_hash = verify_calculated_legacy(root)
        calculation = calculate_residential_study(model)
        print(generate_small_residential_section_pdf(
            str(root / "output/pdf/Жилой_дом_8_квартир_К1_К2_расчётная_схема.pdf"), model, calculation=calculation))
        print(generate_residential_calculation_pdf(
            str(root / "output/pdf/Жилой_дом_8_квартир_расчёт_К1_К2.pdf"), model, calculation,
            rain_source_sha256=source_hash))
    elif args.separate:
        print(generate_small_residential_pdf(str(root / "output/pdf/Жилой_дом_8_квартир_схема_К1_К2.pdf"), model))
    elif args.inventory:
        print(generate_small_residential_combined_pdf(str(root / "output/pdf/Жилой_дом_8_квартир_К1_К2_общий_лист.pdf"), model))
    elif args.basement_proposal:
        print(generate_small_residential_section_pdf(
            str(root / "output/pdf/Жилой_дом_8_квартир_К1_К2_подвал.pdf"), model,
            basement_proposal=educational_basement_proposal(model),
        ))
    else:
        print(generate_small_residential_section_pdf(str(root / "output/pdf/Жилой_дом_8_квартир_К1_К2_разрез.pdf"), model))


if __name__ == "__main__":
    main()
