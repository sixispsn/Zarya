"""Read-only reproduction of legacy findings in the current Python core.

This is an audit, not a test suite accepting the faulty results as correct.
No production inputs, algorithms, catalogs or reference numbers are modified.
Usage: NODE_BINARY=/path/to/node venv/bin/python scripts/audit_legacy_port.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.calc.pumps import (  # noqa: E402
    PumpInput, calculate_pump, interpolate_pump_head,
)
from app.calc.water_demand import ConsumerGroup, calculate_water_demand  # noqa: E402
from app.calc.water_meters import MeterInput, MeterSelectionUnavailable, calculate_meters  # noqa: E402
from app.data.pumps import PUMPS  # noqa: E402
from app.data.sp30_tables import get_alpha  # noqa: E402


def main() -> None:
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise SystemExit("Set NODE_BINARY to an installed Node.js executable")
    legacy = json.loads(subprocess.check_output(
        [node, str(ROOT / "scripts/audit_legacy_algorithms.mjs")], text=True,
    ))
    flows = []
    for count in (500, 1629, 1630, 5865, 5866):
        r = calculate_water_demand([ConsumerGroup("residential_full_bath", count)])
        flows.append({"residents": count, "q_sec": r.total.q_sec,
                      "q_hr": r.total.q_hr, "q_day": r.total.q_day})
    pumps = []
    for c in legacy["pump_cases"]:
        data = c["input"]
        r = calculate_pump(PumpInput(
            q_design_m3h=data["q"], h_geom_manual=data["geom"],
            h_losses=data["loss"], h_pr=20, h_gar=data["gar"], npsh_a=8,
        ))
        pumps.append({
            "case": data["name"], "hp": r.h_required, "hstat": r.h_stat,
            "k": r.k_sys, "candidates": [{
                "model": c.pump.model, "q_work": c.working_point.q,
                "h_work": c.working_point.h,
                "head_at_design": interpolate_pump_head(c.eff_curve, r.q_design),
                "score": c.score,
            } for c in r.candidates],
        })
    current = calculate_pump(PumpInput(
        q_design_m3h=16, h_geom_manual=5, h_losses=5, h_pr=20, h_gar=5,
        npsh_a=8, include_current_catalog=True,
    ))
    best = current.candidates[0]
    # Explicitly synthetic minimum-flow evidence isolates the catalog-overflow
    # problem from the separately fixed missing-passport/minimum-flow gate.
    meter_input = MeterInput(
        q_sec_c=120, q_day_c=9600, q_hr_c=432,
        minimum_flow_checks={"cold": {
            "dn_mm": 250, "q_min_hourly_m3h": 20, "q_min_passport_m3h": 15,
            "passport_reference": "Synthetic audit input, NOT a real passport",
            "flow_reference": "Synthetic audit input, NOT a real building",
        }},
    )
    try:
        meters = calculate_meters(meter_input)
        m = meters.meters[0]
        meter_overflow = {
            "q_average": 400, "q_expl": m.meter.q_expl, "dn": m.meter.d_mm,
            "head_loss": m.h_normal, "pass_normal": m.pass_normal,
            "pass_minimum_with_synthetic_evidence": m.pass_sensitivity,
        }
    except MeterSelectionUnavailable as exc:
        meter_overflow = {"q_average": 400, "dn": None, "status": "unavailable", "reason": str(exc)}
    print(json.dumps({
        "mode": "archive_vs_current_approved_corrections",
        "legacy_source_sha256": legacy["source_sha256"],
        "legacy_alpha_63": legacy["alpha"]["at_boundary"],
        "python_alpha_63": get_alpha(63),
        "python_residential": flows,
        "python_pumps_legacy_catalog": pumps,
        "python_current_catalog_first_candidate": {
            "q_required": current.q_design, "h_required": current.h_required,
            "model": best.pump.model, "q_work": best.working_point.q,
            "h_work": best.working_point.h,
            "head_at_design": interpolate_pump_head(best.eff_curve, current.q_design),
        },
        "python_curve_endpoints": [{
            "model": p.model, "q": p.curve[-1].q,
            "stored_head": p.curve[-1].h,
            "returned_head": interpolate_pump_head(p.curve, p.curve[-1].q),
        } for p in PUMPS],
        "python_meter_overflow": meter_overflow,
        "previously_known_legacy_coefficient06_error":
            legacy["previously_known_coefficient06_error"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
