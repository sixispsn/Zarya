from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.pz.project import Project
from app.pz.scheme import build_scheme, PXMM
from app.pz.hws_building_drafting import build_hws_section, section_floors
from app.pz.section_construction import section_slab_svg
from app.pz.section_scaffold import build_section_scaffold


@pytest.mark.parametrize('scale', [1, PXMM])
def test_hatch_is_physically_consistent_and_clipped_without_svg_masks(scale):
    svg = ET.fromstring(section_slab_svg('floor', 20*scale, 200*scale, 50*scale,
                                       units_per_mm=scale))
    for line in svg.findall('line'):
        assert float(line.get('stroke-width'))/scale == pytest.approx(.18,abs=.001)
        x1,y1,x2,y2 = [float(line.get(key)) for key in ('x1','y1','x2','y2')]
        assert 20*scale-.001 <= x1 <= x2 <= 200*scale+.001
        assert 50*scale-.001 <= y2 <= y1 <= 53*scale+.001
        assert x2-x1 == pytest.approx(y1-y2,abs=.002)
    assert len(svg.findall('line')) > 40
    assert 'clipPath' not in ET.tostring(svg).decode()


@pytest.mark.parametrize('floors', [1,2,3,4,9,16,25])
def test_every_visible_water_floor_has_a_hatched_band_at_the_same_datum(floors):
    p = Project()
    p.building.floors_above = floors
    p.building.floors_below = 1
    p.building.floor_elevations_m = {-1:-3.25, **{i:(i-1)*3 for i in range(1,floors+1)}}
    before = deepcopy(asdict(p))
    svg = ET.fromstring(build_scheme(p).svg)
    slabs = {e.get('data-section-slab'):e for e in svg.iter() if e.get('data-section-slab')}
    sc = build_section_scaffold(p)
    expected = {'v1-floor-1':sc.zero_y, 'v1-base':sc.basement_y,
                **{f'v1-floor-{b.floor}':b.bottom_y for b in sc.bands}}
    assert set(slabs) == set(expected)
    for key, y in expected.items():
        rect = list(slabs[key])[0]
        assert float(rect.get('y')) == y
        assert float(rect.get('width')) == sc.x_right-sc.x_left
        assert any(e.get('data-slab-hatch') for e in slabs[key])
    # HWS uses the same physical hatch style, not a second PDF-only pattern.
    hws = ET.fromstring(build_hws_section(p,3,3))
    keys = {e.get('data-section-slab') for e in hws.iter() if e.get('data-section-slab')}
    assert keys == {'hws-base', *(f'hws-floor-{f}' for f in section_floors(p))}
    if floors > 4:
        top_slab = next(e for e in hws.iter() if e.get('data-section-slab') == f'hws-floor-{floors}')
        slab_rect = list(top_slab)[0]
        slab_bottom = float(slab_rect.get('y')) + float(slab_rect.get('height'))
        edge = next(e for e in hws.iter() if e.get('data-floor-break') == 'upper')
        upper = float(edge.get('d').split(' H')[0].split(',')[1])
        assert upper > slab_bottom
    assert asdict(p) == before


def test_regulators_are_not_inferred_from_typical_apartments_or_irrigation():
    p = Project()
    p.building.floors_above = 16
    p.flows.irrigation_m3_day = 1
    assert 'data-pressure-regulator' not in build_scheme(p).svg
    # Preserve explicit model-based regulators (never remove them with templates).
    p.v1_hydraulic_result = SimpleNamespace(zone_regulators=[SimpleNamespace(
        required=True, topology_feasible=True, hydraulic_reserve_available=True,
        outlet_setpoint_m=25)], pressure_checks=[])
    assert 'data-pressure-regulator="model"' in build_scheme(p).svg
