"""Parity against working JS: unchanged rain and explicitly corrected demand."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.calc.storm import StormInput, calculate_storm
from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.data.storm_cities import GAMMA_PERIOD, STORM_CITIES

ROOT = Path(__file__).resolve().parents[1]


def legacy_reference(cases, residents=()):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        pytest.fail("Node is required for executable legacy parity; set NODE_BINARY")
    return json.loads(subprocess.run(
        [node, str(ROOT / "scripts/legacy_rainwater_reference.mjs")],
        input=json.dumps({"cases": cases, "residents": residents}), text=True,
        capture_output=True, check=True,
    ).stdout)


def test_all_legacy_rain_cities_periods_and_wall_contributions():
    parameters = [(city, period, roof, walls) for city in STORM_CITIES.values()
                  for period in GAMMA_PERIOD for roof, walls in ((252., 0.), (63., 0.), (1234.56, 789.12))]
    ref = legacy_reference([dict(city=c.name, period=p, roof=f, walls=w) for c, p, f, w in parameters])
    # Exact rain block of the first recorded version (17c1bb1), verified against git.
    assert ref["rain_sha256"] == "3bfcd46750888c8f69c21f8d9b8900af24e66860b9c0ffd8f75cf1fed1506ec5"
    assert ref["gamma"] == {str(k): v for k, v in GAMMA_PERIOD.items()}
    assert [(c["name"], c["q20"], c["n"], c["region"]) for c in ref["cities"]] == [
        (c.name, c.q20, c.n, c.region) for c in STORM_CITIES.values()]
    for (city, period, roof, walls), expected in zip(parameters, ref["cases"], strict=True):
        result = calculate_storm(StormInput(city.code, roof, walls, period))
        assert (result.q_total_l_per_s, result.q5, result.f_calculated_m2) == (
            expected["flow_lps"], expected["q5"], expected["area"]), (city.code, period, roof, walls)


def test_educational_sewage_uses_unrounded_legacy_total_before_adding_fixture():
    for count, expected in zip((5, 20, 500), legacy_reference([], [5, 20, 500])["residents"], strict=True):
        result = calculate_water_demand([ConsumerGroup("residential_full_bath", count)])
        assert result.total.q_sec == expected["total_lps"]
        if count == 500:
            # L01: NPhr=19.333... now interpolates the restored 19.2/19.4 cells.
            # Working HTML now includes L01; the immutable archive is tested separately.
            assert expected["hourly_m3"] == 10.075
            assert result.total.q_hr == 10.075
        else:
            assert result.total.q_hr == expected["hourly_m3"]
        assert result.sewage_flow == expected["sewage_lps"]


def test_project_pipeline_does_not_recalculate_k1_from_rounded_water_flow(tmp_path):
    from app.intake.request_dto import IOS2Request, DocumentRequest, ConsumerGroupRequest
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    counts = [5, 20, 500]
    for count, expected in zip(counts, legacy_reference([], counts)["residents"], strict=True):
        request = IOS2Request(
            document=DocumentRequest("", "", ""), building_type="residential",
            floors=2, building_height_m=6.6, fire_height_m=4.8,
            consumers=[ConsumerGroupRequest("residential_full_bath", count)],
        )
        bundle = design_ios2(build_project(request), output_dir=str(tmp_path), render_documents=False)
        assert bundle.project.flows.sewage_l_per_s == expected["sewage_lps"]
        assert bundle.project.sewage.result.total.q_sewage_lps == expected["sewage_lps"]
