"""The schematic can compress floors, but cannot replace their AR elevations."""
from xml.etree import ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

import pytest

from app.pz.project import Project
from app.pz.scheme import build_scheme
from app.pz.section_scaffold import build_section_scaffold


def text(svg):
    return ' '.join(ET.fromstring(svg).itertext())


def mark(value):
    v = Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return (f'{v:+.2f}' if v else '0.00').replace('.', ',')


@pytest.mark.parametrize('floors', [1, 2, 3, 4, 9, 16, 25])
def test_water_scheme_uses_explicit_irregular_floor_levels(floors):
    p = Project()
    p.building.floors_above = floors
    p.building.floors_below = 1
    p.building.height_m = 111.123  # fire/building height is not the roof elevation
    p.building.floor_elevations_m = {-1: -3.1, 1: .15, **{i: .15+(i-1)*3.3 for i in range(2, floors+1)}}
    p.sewage.roof_relative_elevation_m = floors*3.3+.15
    result = build_scheme(p)
    contents = text(result.svg)
    shown = {1, floors} | ({2} if floors >= 2 else set()) | ({3} if floors >= 3 else set())
    for floor in shown:
        assert mark(p.building.floor_elevations_m[floor]) in contents
    assert '-3,10' in contents
    assert mark(p.sewage.roof_relative_elevation_m) in contents
    assert '+111,123' not in contents


def test_missing_levels_are_not_guessed_from_the_old_template():
    p = Project()
    p.building.floors_above = 3
    p.building.height_m = 9
    result = build_scheme(p)
    contents = text(result.svg)
    assert 'отм. по АР' in contents
    assert '+5,900' not in contents and '-4,000' not in contents and '+9,000' not in contents
    assert '-0,700' not in contents and '-2,200' not in contents and '-3,400' not in contents
    assert any('2 этаж' in warning for warning in result.warnings)


@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_nonfinite_level_is_not_printed_as_a_project_mark(value):
    p = Project()
    p.building.floor_elevations_m = {1: value}
    with pytest.raises(ValueError, match='конечным'):
        build_scheme(p)


@pytest.mark.parametrize('inlets', [1, 2])
@pytest.mark.parametrize('floors', [2, 3, 16])
def test_each_water_inlet_crosses_exterior_wall(inlets, floors):
    p = Project()
    p.building.floors_above = floors
    p.source.inputs_count = inlets
    scaffold = build_section_scaffold(p)
    svg = ET.fromstring(build_scheme(p).svg)
    expected_y = [1560] if inlets == 1 else [1526, 1594]
    lines = list(svg.iter('{http://www.w3.org/2000/svg}line'))
    for y in expected_y:
        matches = [line for line in lines
                   if float(line.get('y1', -1)) == y == float(line.get('y2', -1))
                   and float(line.get('x1', 0)) < scaffold.x_left
                   and float(line.get('x2', 0)) > scaffold.x_left]
        assert len(matches) == 1
        assert float(matches[0].get('x2')) == scaffold.x_left + 106
        assert scaffold.roof_y < y < scaffold.basement_y
