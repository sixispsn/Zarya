"""Actual standalone HTML, without corrective test overlays, against Python."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.calc.pumps import PumpInput, calculate_pump
from app.calc.water_meters import MeterInput, MeterSelectionUnavailable, calculate_meters
from app.data.sp30_tables import ALPHA_TABLE, get_alpha
from app.data.water_meters import WATER_METERS
from scripts.rebuild_working_legacy import ARCHIVE, ARCHIVE_SHA, WORKING, build

ROOT = Path(__file__).resolve().parents[1]


def execute(script, **payload):
    node = os.environ.get('NODE_BINARY') or shutil.which('node')
    assert node, 'Node is required'
    result = subprocess.run([node, str(ROOT / 'scripts' / script)],
                            input=json.dumps({'working_copy': True, 'cases': [], **payload}),
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_archive_immutable_and_working_copy_reproducible():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_SHA
    assert WORKING.read_text() == build()
    assert WORKING.read_bytes() != ARCHIVE.read_bytes()


def test_working_b2_all_cells_and_midpoints_match_python_without_overlay():
    points = [x for x, _ in ALPHA_TABLE]
    points += [(a[0] + b[0]) / 2 for a, b in zip(ALPHA_TABLE, ALPHA_TABLE[1:])]
    result = execute('legacy_demand_reference.mjs', points=points)
    assert result['approved_l01_correction'] is False
    assert result['alpha'] == pytest.approx([get_alpha(x) for x in points], abs=1e-10)


def test_working_meter_branches_boundaries_rounding_and_unknown_minimum():
    cases = []
    for mode in ('central', 'local'):
        for meter in WATER_METERS:
            for factor in (.999, 1, 1.001):
                for flow in (.3, 2, 20, 120, 400):
                    for fire in (0, 5):
                        cases.append(MeterInput(hws_type=mode, period_hours=24,
                            q_day_c=meter.q_expl*factor*24, q_day_h=meter.q_expl*factor*24,
                            q_day_tot=meter.q_expl*factor*24,
                            q_sec_c=flow, q_sec_h=flow, q_sec_tot=flow,
                            q_hr_c=4, q_hr_h=4, q_fire_l_per_s=fire))
    result = execute('legacy_meters_reference.mjs', **{'cases': [asdict(c) for c in cases]})
    assert len(cases) == 720
    for data, raw in zip(cases, result['cases'], strict=True):
        if raw.get('unavailable'):
            with pytest.raises(MeterSelectionUnavailable):
                calculate_meters(data)
            continue
        actual = calculate_meters(data)
        for row, expected in zip(actual.meters, raw['meters'], strict=True):
            assert row.meter.d_mm == expected['dn']
            assert row.meter.s == expected['s']
            for name in ('h_normal', 'h_fire', 'pass_normal', 'pass_fire', 'pass_sensitivity', 'need_combo'):
                assert getattr(row, name) == expected[name], (data, name)


@pytest.mark.parametrize('mode', ['1', '2p', '2s'])
def test_working_pump_curves_admission_intersections_and_scores_match_python(mode):
    cases = [dict(geom=g, loss=loss, gar=h, q=q, mode=mode)
             for g, loss, h, q in [(25, 5, 20, 5), (25, 5, 40, 5), (6, 5, 5, 10), (50, 8, 25, 20)]]
    raw = execute('legacy_pumps_reference.mjs', **{'cases': cases})
    for data, expected in zip(cases, raw['cases'], strict=True):
        actual = calculate_pump(PumpInput(q_design_m3h=data['q'], h_geom_manual=data['geom'],
            h_losses=data['loss'], h_gar=data['gar'], npsh_a=8, mode=mode))
        assert [r.pump.model for r in actual.candidates] == [r['model'] for r in expected['candidates']]
        for row, candidate in zip(actual.candidates, expected['candidates'], strict=True):
            assert row.score == candidate['score']
            assert asdict(row.working_point) == pytest.approx(candidate['wp'], abs=1e-8)


def test_working_intersection_refuses_no_root_ambiguity_and_preserves_endpoint():
    probes = [dict(curve=[dict(q=0, h=30), dict(q=10, h=20)], hstat=10, k=.1),
              dict(curve=[dict(q=0, h=30), dict(q=10, h=20)], hstat=100, k=.1),
              dict(curve=[dict(q=0, h=5), dict(q=10, h=5)], hstat=5, k=0),
              dict(curve=[dict(q=0, h=0), dict(q=4, h=8)], hstat=.75, k=1)]
    raw = execute('legacy_pumps_reference.mjs', probes=probes)
    assert raw['probes'] == [dict(q=10, h=20, h_sys=20), None, None, None]
