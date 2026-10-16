"""Reproducible L02 control PDF; no project/user data or source archive is changed."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.calc.fire_hydraulics import PumpDutyPoint, SourceKind  # noqa: E402
from app.pz.generator import generate_pump_selection_pdf  # noqa: E402
from app.pz.project import Project, WaterSource  # noqa: E402
from app.pz.pump_bridge import compute_fire_pump_from_duty, compute_pump_from_head  # noqa: E402
from app.pz.rules import calc_required_head  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("l02", "l03", "l04"), default="l02")
    case = parser.parse_args().case
    project = Project()
    # Synthetic audit inputs, not a building design. Blank project stamp.
    project.source = WaterSource(
        h_geom_m=6 if case == "l03" else 25, h_pr_m=20, h_il_m=3, h_vod_m=1,
        h_vvod_m=1, h_tepl_m=0,
        guaranteed_head_m=5 if case == "l03" else (20 if case == "l04" else 40),
    )
    project.pumps = compute_pump_from_head(
        q_design_m3h=10 if case == "l03" else 5,
        head=calc_required_head(project.source), npsh_a_m=8,
    )
    project.fire_pumps = compute_fire_pump_from_duty(
        PumpDutyPoint(required_head_m=70, flow_lps=2.6,
                      source_kind=SourceKind.CITY_MAIN),
        npsh_a_m=8, maximum_source_head_m=30, pk_total=8,
    )
    output = ROOT / f"output/pdf/{case}_pump_selection.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    generate_pump_selection_pdf(project, str(output))
    print(output)
    print(f"В1: Hнас={project.pumps.h_design_m:g}; H0={project.pumps.h_stat:g}; "
          f"k={project.pumps.k_sys:g}; {project.pumps.model}")
    print(f"В2: {project.fire_pumps.curve_kind}; {project.fire_pumps.model}")


if __name__ == "__main__":
    main()
