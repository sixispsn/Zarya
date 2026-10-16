"""The exact intake T73 key must survive through to every generated cabinet."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from app.calc.fire_hydraulics import _cabinet_required_head_and_flow, MPA_TO_M
from app.data.fire_tables import FIRE_NOZZLE_TABLE
from app.intake.project_builder import build_project
from app.pz.geometry_builder import build_network
from scripts.build_samara_section_study import load_basis, make_draft, make_request


@pytest.mark.parametrize("key", list(FIRE_NOZZLE_TABLE))
def test_all_108_cabinet_keys_survive_intake_and_geometry(key):
    req = make_request(make_draft(load_basis()))
    req.cabinet_dn, req.nozzle_mm, req.hose_length_m, req.compact_jet_m = key
    # Manual demand avoids conflating applicability/jet-height requirements
    # with this exhaustive data-transfer test. It does not approve all keys
    # for the particular 16-storey building.
    req.fire_mode = "manual"
    req.streams = 2
    req.q_per_stream_lps = FIRE_NOZZLE_TABLE[key].q
    for cab in build_network(build_project(req)).cabinets:
        assert (cab.dn, cab.nozzle_mm, cab.hose_m, cab.jet_m) == key
        h, q, notes = _cabinet_required_head_and_flow(cab)
        assert not notes
        assert (h, q) == (FIRE_NOZZLE_TABLE[key].p*MPA_TO_M, FIRE_NOZZLE_TABLE[key].q)


def test_working_html_table_executed_without_overlays_matches_binding():
    node = os.environ.get("NODE_BINARY")
    assert node, "Set NODE_BINARY for working HTML parity"
    root = Path(__file__).resolve().parents[1]
    script = r"""
      const fs = require('fs'), vm = require('vm');
      const html = fs.readFileSync('legacy/sp30_calculator.html','utf8');
      const start = html.indexOf('const T73 = {');
      if(start < 0) throw Error('Missing canonical table');
      const end = html.indexOf('};',start)+2;
      process.stdout.write(JSON.stringify(vm.runInNewContext(html.slice(start,end)+'; T73;')));
    """
    result = subprocess.run([node, "-e", script], cwd=root, check=True, text=True, capture_output=True)
    js = json.loads(result.stdout)
    assert len(js) == len(FIRE_NOZZLE_TABLE) == 108
    for key, value in FIRE_NOZZLE_TABLE.items():
        assert js["_".join(map(str,key))] == {"q":value.q,"p":value.p}
    # The previous hidden default had the SAME flow but less than half the
    # required pressure. A flow-only parity assertion cannot catch this bug.
    assert js["50_13_20_12"] == {"q":2.6,"p":.21}
    assert js["50_16_20_6"] == {"q":2.6,"p":.10}


def test_study_pz_and_hydraulic_cabinet_pressure_agree():
    p = build_project(make_request(make_draft(load_basis())))
    for cab in build_network(p).cabinets:
        h, q, _ = _cabinet_required_head_and_flow(cab)
        assert h == pytest.approx(p.fire.pressure_mpa*MPA_TO_M)
        assert q == p.fire.q_per_stream
