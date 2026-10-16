from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.pz.wastewater_fan_binding import (
    audit_bound_fan_svgs, bind_project_fans, build_bound_fan_preview_svgs,
)
from app.pz.wastewater_scheme_service import (
    assess_wastewater_scheme_readiness, generate_wastewater_fan_binding_preview,
)
from tests.fan_binding_fixture import fan_binding_fixture


def test_building_binding_is_connected_and_never_mutates_project():
    project, data = fan_binding_fixture()
    before = deepcopy(project)
    pages = build_bound_fan_preview_svgs(project, data)
    binding = bind_project_fans(project, data)
    assert project == before
    assert len(pages) == 7
    assert binding.roof_sheet_by_terminal == {"К1-Вент1": 7}
    assert not audit_bound_fan_svgs(binding, pages)
    rows = [r for s in pages for r in ET.fromstring(s).iter()]
    ports = [r for r in rows if r.get("data-fan-building-port")]
    assert len(ports) == 5
    assert sum(r.get("data-role") == "common_vent" for r in rows) == 1
    assert not any(r.get("data-vent-cap") for r in rows)
    assert all(r.get("data-target-sheet") == "7" for r in ports if r.get("data-kind") == "roof")
    valve = next(r for r in ports if r.get("data-kind") == "valve")
    assert valve.get("data-fan-building-port") == "К1-Ст5"
    assert valve.get("data-level-m") == "4.5"
    assert sum(bool(r.get("data-valve-outline")) for r in rows) == 1
    # Both original independent drainage systems, floors, revisions, cleanouts,
    # through fittings and final outlets must survive the upper-port replacement.
    assert sum(bool(r.get("data-floor-assembly")) for r in rows) == 10
    assert any(r.get("data-building-revision") for r in rows)
    assert "К1-ПрНП1" in "".join(pages) and "К2-ПрНП1" in "".join(pages)
    assert "К1-Вып1" in "".join(pages) and "К2-Вып1" in "".join(pages)


@pytest.mark.parametrize("change,match", [
    ("evidence", "evidence"), ("dn", "risers/DN"), ("outlet", "risers/DN"),
    ("roof", "roof level"), ("floor", "floor levels"), ("port", "upper endpoint"),
    ("valve_od", "connection OD"), ("roof_unknown", "roof level required"),
])
def test_binding_rejects_detached_or_invented_inputs(change, match):
    project, data = fan_binding_fixture()
    if change == "evidence":
        project.sewage.fan_ventilation = None
    elif change in {"dn", "outlet"}:
        data = replace(data, risers=(replace(data.risers[0], **(
            {"diameter_mm": 50.} if change == "dn" else {"outlet_id": "foreign"}
        )),)+data.risers[1:])
    elif change == "roof":
        data = replace(data, roofs=(replace(data.roofs[0], roof_level_m=6.7),))
    elif change == "floor":
        project.building.floor_elevations_m = {2: 3.2}
    elif change == "port":
        data = replace(data, roofs=(replace(data.roofs[0], risers=tuple(replace(p, lower_port_m=4.45) for p in data.roofs[0].risers)),))
    elif change == "valve_od":
        next(p for p in project.sewage.pipes if p.section_id == "К1-Ст5").outer_diameter_mm = 125.
    else:
        project.sewage.roof_relative_elevation_m = None
    with pytest.raises(ValueError, match=match):
        bind_project_fans(project, data)


@pytest.mark.parametrize("damage", ["missing_port", "old_roof", "wrong_sheet", "disconnected", "lost_edge", "duplicate_valve"])
def test_drawing_regressions_stop_the_bound_audit(damage):
    project, data = fan_binding_fixture()
    binding = bind_project_fans(project, data)
    roots = [ET.fromstring(s) for s in build_bound_fan_preview_svgs(project, data)]
    port = next(r for r in roots[0].iter() if r.get("data-fan-building-port") == "К1-Ст1")
    if damage == "missing_port":
        roots[0].remove(port)
    elif damage == "old_roof":
        ET.SubElement(roots[0], "line", {"data-vent-cap": "К1-Ст1"})
    elif damage == "wrong_sheet":
        port.set("data-target-sheet", "6")
    elif damage == "disconnected":
        port.set("data-port-y", "123")
    elif damage == "lost_edge":
        edge = next(r for r in roots[-1].iter() if r.get("data-fan-edge") == "collector:1")
        roots[-1].remove(edge)
    else:
        port = next(r for r in roots[2].iter() if r.get("data-fan-building-port"))
        port.append(deepcopy(next(r for r in port.iter() if r.get("data-valve-outline"))))
    assert audit_bound_fan_svgs(binding, tuple(ET.tostring(r, encoding="unicode") for r in roots))


def test_missing_input_never_overwrites_pdf(tmp_path):
    p, d = fan_binding_fixture()
    p.sewage.roof_relative_elevation_m = None
    out = tmp_path / "existing.pdf"
    out.write_bytes(b"original")
    with pytest.raises(ValueError):
        generate_wastewater_fan_binding_preview(p, d, str(out))
    assert out.read_bytes() == b"original"


def test_new_callouts_stay_above_rooms_and_valve_moves_with_explicit_level():
    p, d = fan_binding_fixture()
    original = build_bound_fan_preview_svgs(p, d)
    d = replace(d, valves=(replace(d.valves[0], connection_level_m=4.65),))
    next(row for row in p.sewage.pipes if row.section_id == "К1-Ст5").elevation_start_m = 4.65
    changed = build_bound_fan_preview_svgs(p, d)
    def valve_y(svg):
        return float(next(r.get("data-port-y") for r in ET.fromstring(svg).iter()
                          if r.get("data-fan-building-port") == "К1-Ст5"))
    assert valve_y(changed[2]) < valve_y(original[2])
    for svg in changed[:3]:
        for group in (r for r in ET.fromstring(svg).iter() if r.get("data-fan-building-port")):
            leader = next(r for r in group.iter() if r.get("data-leader-id"))
            assert float(leader.get("data-text-box-y2")) < 480  # above upper room cells


def test_bound_preview_remains_explicitly_not_a_release(tmp_path):
    p, d = fan_binding_fixture()
    assert not assess_wastewater_scheme_readiness(p).ready
    result = generate_wastewater_fan_binding_preview(p, d, str(tmp_path / "bound.pdf"))
    assert not result.ready and result.backend == "fan-binding-control"
    pages = PdfReader(result.output_path).pages
    assert len(pages) == 7
    text = [page.extract_text() for page in pages]
    assert "Воздушный клапан" in text[2]
    assert "3000" in text[6] and "С л. 1; +4.40" in text[6]
    assert all('data-production-release="false"' in s for s in build_bound_fan_preview_svgs(p, d))
