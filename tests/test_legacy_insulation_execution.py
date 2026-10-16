"""Actual working JS against Python, with explicit current pipe geometry."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.calc.insulation import PipeGvs, calc_gvs_pipe

ROOT = Path(__file__).resolve().parents[1]


def test_working_insulation_and_explicit_geometry_match_without_formula_overlay():
    node = os.environ.get('NODE_BINARY') or shutil.which('node')
    assert node, 'Node is required for legacy parity'
    cases = [dict(dn=dn, outer_diameter_mm=outer, t_water=t, t_room=room)
             for dn, outer in ((65, None), (65, 76), (40, None), (40, 48))
             for t in (50, 60, 70) for room in (5, 20)]
    run = subprocess.run([node, str(ROOT/'scripts/legacy_insulation_reference.mjs')],
                         input=json.dumps(dict(cases=cases)), text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    raw = json.loads(run.stdout)
    for c, expected in zip(cases, raw['cases'], strict=True):
        actual = calc_gvs_pipe(PipeGvs(c['dn'], c['t_water'],
            outer_diameter_mm=c['outer_diameter_mm']), c['t_room'])
        assert actual.delta == expected['delta'], c
        assert actual.d_mm == pytest.approx(expected['d_mm'], abs=1e-9)
        assert actual.ql == pytest.approx(expected['qL'], abs=.05)
        assert actual.rnl == pytest.approx(expected['RnL'], abs=.0005)
        assert actual.delta_calc == pytest.approx(expected['delta_calc'], abs=.05)
    samara = calc_gvs_pipe(PipeGvs(65, 60, outer_diameter_mm=76),20)
    assert (samara.ql, samara.rnl, samara.delta_calc, samara.delta) == (14.8,.355,56.2,60)
