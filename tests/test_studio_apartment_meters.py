"""The approved average-apartment estimate reuses working legacy arithmetic."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.calc.water_meters import MeterInput
from app.data.sp30_tables import CONSUMER_NORMS
from app.intake.preflight import preflight_request
from app.intake.project_builder import build_project
from app.intake.studio_intake import (
    answer_field, build_handoff_request, calculate_draft, public_draft,
)
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import dump_request, load_request


def draft(**overrides):
    result = dict(revision=0, answers={}, documents=[])
    values = dict(residents=20, apartments=8, consumer_code="residential_full_bath",
                  floors=2, building_height_m=6.6, fire_height_m=4.8, hws_type="central",
                  guaranteed_head_m=5, h_geom_m=6, pressure_loss_mode="ready",
                  h_il_m=3, h_vvod_m=1, t3_loss_mode="ready", h_il_hot_m=4,
                  hws_heater_in_scope="no")
    for key, value in {**values, **overrides}.items():
        answer_field(result, key, value)
    result["calculation"] = calculate_draft(result)
    return result


def fields(d):
    return {row["key"]: row for row in public_draft(d)["fields"]}


def reference(script, cases):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node, "Set NODE_BINARY to verify the working legacy"
    result = subprocess.run([node, f"scripts/{script}"],
                            input=json.dumps(dict(working_copy=True, cases=cases)),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)["cases"]


def test_average_apartment_golden_and_unobstructed_preliminary_head():
    d = draft()
    state = public_draft(d)
    estimate = state["apartment_meters"]
    assert estimate["design_residents"] == estimate["average_residents"] == 2.5
    assert fields(d)["h_apartment_c_meter_m"]["value"] == .633
    assert fields(d)["h_apartment_h_meter_m"]["value"] == .708
    assert all(row["dn"] == 15 for row in estimate["rows"].values())
    assert not state["head_missing"]
    assert not any(k in step["fields"] for step in state["next_steps"]
                   for k in ("h_apartment_c_meter_m", "h_apartment_h_meter_m", "h_tepl_m"))
    p = calculate_project(d)
    assert p["head"]["ready"] and p["head"]["preliminary"] and p["can_preview"]
    assert p["head"]["required_m"] == 34.4
    assert not p["can_release"]
    assert p["flows"]["q_day_tot"] == 3.6  # no rounding of the building population


@pytest.mark.parametrize("key,value", [("residents", 40), ("apartments", 4),
                                      ("consumer_code", "residential_sit_bath")])
def test_current_inputs_recompute_estimate_and_revoke_outputs(key, value):
    d = draft()
    before = fields(d)["h_apartment_c_meter_m"]["value"]
    d["project_calculation"], d["preview"] = {"old": True}, {"old": True}
    answer_field(d, key, value)
    assert d["project_calculation"] is None and d["preview"] is None
    assert fields(d)["h_apartment_c_meter_m"]["value"] != before


def test_manual_apartment_and_losses_take_priority_without_false_auto_label():
    d = draft(apartment_design_residents=6)
    assert public_draft(d)["apartment_meters"]["design_residents"] == 6
    answer_field(d, "h_apartment_c_meter_m", 1.25)
    assert fields(d)["h_apartment_c_meter_m"]["value"] == 1.25
    assert "h_apartment_c_meter_m" not in public_draft(d)["apartment_meters"]["rows"]
    answer_field(d, "residents", 40)
    assert fields(d)["h_apartment_c_meter_m"]["value"] == 1.25
    answer_field(d, "h_apartment_h_meter_m", .8)
    assert public_draft(d)["apartment_meters"] is None
    assert not build_handoff_request(d).source_data.apartment_meter_basis
    answer_field(d, "h_apartment_c_meter_m", None)
    assert fields(d)["h_apartment_c_meter_m"]["source"]["kind"] == "apartment_estimate"


@pytest.mark.parametrize("overrides", [dict(apartments=None), dict(residents=None), dict(hws_type="local")])
def test_unknown_or_unsupported_inputs_are_not_fabricated(overrides):
    d = draft()
    for key, value in overrides.items():
        answer_field(d, key, value)
    assert public_draft(d)["apartment_meters"] is None
    assert fields(d)["h_apartment_c_meter_m"]["value"] is None


def test_no_hot_water_has_no_hot_apartment_meter_or_heater_question():
    d = draft(hws_type="none")
    state = public_draft(d)
    assert list(state["apartment_meters"]["rows"]) == ["h_apartment_c_meter_m"]
    assert fields(d)["h_apartment_h_meter_m"]["value"] is None
    assert not any("h_tepl_m" in step["fields"] for step in state["next_steps"])
    assert calculate_project(d)["head"]["ready"]


def test_zero_heater_loss_has_visible_reason_but_no_guided_loss_question():
    d = draft(hws_heater_in_scope="yes", h_tepl_m=0)
    state = public_draft(d)
    assert "h_tepl_m" in state["head_missing"]
    assert not any("h_tepl_m" in step["fields"] for step in state["next_steps"])
    assert not calculate_project(d)["head"]["ready"]


def test_assumption_survives_yaml_builder_and_release_checks():
    req = build_handoff_request(draft())
    restored = load_request(dump_request(req))
    basis = req.source_data.apartment_meter_basis
    assert basis and restored.source_data.apartment_meter_basis == basis
    assert build_project(restored).source.pressure_note == basis
    report = preflight_request(restored)
    assert report.can_calculate and not report.can_release
    assert any(row.code == "studio.apartment_meter_estimate" for row in report.release_blockers)


def test_fractional_average_uses_actual_legacy_calcblock_and_meter_selection():
    cases = [(code, count) for code in CONSUMER_NORMS if code.startswith("residential_")
             for count in (1, 2.5, 20 / 7, 4, 8)]
    expected = reference("legacy_demand_reference.mjs", [
        [dict(label=CONSUMER_NORMS[code].label, count=count)] for code, count in cases])
    meter_inputs = []
    for (code, count), raw in zip(cases, expected, strict=True):
        result = calculate_water_demand([ConsumerGroup(code, count)], round_consumers=False)
        assert result.groups[0].count == count
        for kind in ("total", "cold", "hot"):
            assert getattr(result, kind).q_sec == round(raw[kind]["q_sec"], 3)
            assert getattr(result, kind).q_hr == round(raw[kind]["q_hr"], 3)
        meter_inputs.append(MeterInput(q_sec_c=result.cold.q_sec, q_sec_h=result.hot.q_sec,
            q_sec_tot=result.total.q_sec, q_day_c=result.cold.q_day, q_day_h=result.hot.q_day,
            q_day_tot=result.total.q_day, q_hr_c=result.cold.q_hr, q_hr_h=result.hot.q_hr))
    meters = reference("legacy_meters_reference.mjs", [asdict(item) for item in meter_inputs])
    for (code, count), raw in zip(cases, meters, strict=True):
        # Fractional average only; user-entered governing occupancy remains integer.
        from app.intake.studio_apartment_meters import estimate_apartment_meters
        estimate = estimate_apartment_meters(dict(residents=count * 8, apartments=8,
                                                 consumer_code=code, hws_type="central"))
        for row, expected_meter in zip(estimate["rows"].values(), raw["meters"], strict=True):
            assert row["dn"] == expected_meter["dn"]
            assert row["loss_m"] == expected_meter["h_normal"]


def test_status_lights_and_progress_have_accessible_static_fallback():
    css = Path("app/web/static/studio.css").read_text()
    js = Path("app/web/static/studio.js").read_text()
    green = css.split(".status.confirmed::before {")[1].split("}")[0]
    red = css.split(".status.missing::before, .status.conflict::before {")[1].split("}")[0]
    assert "animation:" not in green
    assert "signal 2.4s" in red and "#ff123b" in red
    assert "prefers-reduced-motion: reduce" in css and "animation: none !important" in css
    assert "Расходы жилой группы" in js and "Предварительный напор" in js
    assert "$('.calculation-progress')?.setAttribute('hidden','')" in js
