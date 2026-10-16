"""Legacy execution plus separately approved DN65/minimum-flow/L05 corrections.

Original HTML and its fingerprint are unchanged. The comparison oracle enables
DN65 data and L05 catalog-exhaustion overlays explicitly. Minimum flow has
independent tests. See docs/water_meter_audit_2026-09-20.md and
docs/meter_catalog_bounds_correction_2026-09-21.md (approval 21.09.2026).
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.calc.water_meters import MeterInput, MeterSelectionUnavailable, calculate_meters
from app.data.water_meters import WATER_METERS

ROOT = Path(__file__).resolve().parents[1]


def legacy_reference(cases, *, approved_dn65_correction=False, approved_l05_correction=False):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        pytest.fail("Node is required for executable legacy parity; set NODE_BINARY")
    return json.loads(subprocess.run(
        [node, str(ROOT / "scripts/legacy_meters_reference.mjs")],
        input=json.dumps({"cases": cases, "approved_dn65_correction": approved_dn65_correction,
                          "approved_l05_correction": approved_l05_correction}), text=True,
        capture_output=True, check=True,
    ).stdout)


def test_all_meter_rows_match_executed_legacy_including_overwrites():
    legacy = legacy_reference([])
    assert legacy["source_sha256"] == "ebf419b2b1f38ec09277cc63b0f9048055ca55f3ef0625a52eb6e495a221ec3d"
    assert len(legacy["table"]) == len(WATER_METERS) == 12
    for actual, expected in zip(WATER_METERS, legacy["table"], strict=True):
        assert actual.d_mm == expected["d"]
        assert actual.q_min == expected["qmin"]
        assert actual.q_expl == expected["qexpl"]
        assert actual.q_max == expected["qmax"]
        assert actual.q_threshold == expected["qthr"]
        if actual.d_mm == 65:
            assert expected["S"] == 81 * 1e-5  # archived error must remain visible
            assert actual.s == 810 * 1e-5     # independently approved SP table value
        else:
            assert actual.s == expected["S"]
        assert actual.type == {"w": "wing", "t": "turbine"}[expected["type"]]


def _cases():
    # Every selection threshold, below/above; no duplicated arithmetic oracle.
    for hws_type in ("central", "local"):
        for meter in WATER_METERS:
            for factor in (0.999, 1., 1.001):
                for q_sec in (0.3, 2., 10., 20., 400.):
                    for fire in (0., 5.):
                        yield MeterInput(
                            hws_type=hws_type, period_hours=24,
                            q_day_tot=meter.q_expl * factor * 24,
                            q_day_c=meter.q_expl * factor * 24,
                            q_day_h=meter.q_expl * factor * 24,
                            q_sec_tot=q_sec, q_sec_c=q_sec, q_sec_h=q_sec,
                            q_hr_c=0.02, q_hr_h=4., q_fire_l_per_s=fire,
                            inputs_count=1 if fire else 2,
                            is_individual_house=(factor < 1),
                        )


@pytest.fixture(scope="module")
def compared_cases():
    cases = list(_cases())
    reference = legacy_reference([asdict(case) for case in cases], approved_dn65_correction=True,
                                 approved_l05_correction=True)
    assert reference["approved_dn65_correction"] is True
    return list(zip(cases, reference["cases"], strict=True))


def test_meter_selection_and_checks_match_legacy(compared_cases):
    for data, expected in compared_cases:
        if expected.get("unavailable"):
            with pytest.raises(MeterSelectionUnavailable):
                calculate_meters(data)
            continue
        result = calculate_meters(data)
        assert len(result.meters) == len(expected["meters"])
        assert bool(result.notes) == expected["one_input_bypass_note"], data
        for actual, wanted in zip(result.meters, expected["meters"], strict=True):
            assert actual.meter.d_mm == wanted["dn"], data
            assert actual.meter.s == pytest.approx(wanted["s"], rel=1e-14)
            for field in (
                "h_limit_normal", "pass_normal",
                "h_limit_fire", "pass_fire", "need_bypass",
            ):
                assert getattr(actual, field) == wanted[field], (data, field, actual, wanted)
            # Deliberate normative difference: peak flow cannot prove minimum flow.
            assert actual.pass_sensitivity is None
            assert actual.need_combo is False


def test_rendered_meter_losses_match_legacy_exactly(compared_cases):
    # No tolerance: JS toFixed(3), including the former DN200 0.003/0.004 failure.
    mismatches = []
    for data, expected in compared_cases:
        if expected.get("unavailable"):
            with pytest.raises(MeterSelectionUnavailable):
                calculate_meters(data)
            continue
        actual = calculate_meters(data)
        for row, wanted in zip(actual.meters, expected["meters"], strict=True):
            for field in ("h_normal", "h_fire"):
                if getattr(row, field) != wanted[field]:
                    mismatches.append((data, row.meter.d_mm, field, getattr(row, field), wanted[field]))
    assert not mismatches, f"{len(mismatches)} rounding mismatches; first: {mismatches[:1]}"
