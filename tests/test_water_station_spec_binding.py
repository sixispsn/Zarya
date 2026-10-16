"""Station drawing/PZ/SO reconciliation without new hydraulics or sizing."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

import pytest

from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common
from app.pz.spec import build_specification
from app.pz.water_station_components import external_items
from app.pz.water_station_drafting import build_pump_zone_scheme_pages
from app.pz.water_station_review import factory_component_ids, service_access_requirements


def rows(project):
    return [r for s in build_specification(project, scope='water').sections for r in s.rows]


def test_every_explicit_station_spec_binding_has_exactly_one_owner(common):
    before = deepcopy(asdict(common))
    spec = rows(common)
    counts = Counter(i for r in spec for i in r.component_ids)
    assert not [(i, n) for i, n in counts.items() if n > 1]
    drawing = ET.fromstring(build_pump_zone_scheme_pages(common)[0])
    links = [e.get('data-spec-component') for e in drawing.iter() if e.get('data-spec-component')]
    assert set(links) == {'station_air', 'station_drain', 'station_cold_isolation',
                          'meter_cold', 'hot:meter', 'hot:valve_before'}
    assert all(counts[key] == 1 for key in links)
    assert asdict(common) == before


def test_station_external_points_do_not_disappear_or_become_factory_parts(common):
    spec = rows(common)
    expected = {item.id for item in external_items(common)}
    assert expected == {'station_air', 'station_drain', 'station_cold_isolation'}
    for key in expected:
        owner = next(r for r in spec if key in r.component_ids)
        assert owner.qty == 1 and owner.quantity_basis == 'principle_requirement'
        assert owner.catalogue_id == '' and 'по подбору' in owner.type_mark
        assert 'station_assembly' not in owner.component_ids
        assert key not in factory_component_ids(common)
    # General building service points are NOT the new station quantities.
    assert next(r for r in spec if 'v1-drain-valve' in r.component_ids).qty is None
    assert next(r for r in spec if 'v1-air-vent' in r.component_ids).qty is None


def test_three_meters_one_station_and_no_annotation_only_purchases(common):
    spec = rows(common)
    for key, dn in (('meter', 50), ('meter_cold', 32), ('hot:meter', 32)):
        owner = next(r for r in spec if key in r.component_ids)
        assert owner.qty == 1 and f'DN{dn}' in owner.name
    assert sum(r.qty for r in spec if 'station_assembly' in r.component_ids) == 1
    assert sum(r.qty for r in spec if 'hot:valve_before' in r.component_ids) == 2  # one grouped before/after row
    ids = {i for r in spec for i in r.component_ids}
    assert all(a['id'] not in ids and a['target'] not in ids
               for a in service_access_requirements(common))
    for key in factory_component_ids(common):
        assert len([r for r in spec if key in r.component_ids]) == 1


def test_meter_dn_binding_is_not_external_pipe_or_station_port_dn(common):
    spec = rows(common)
    drawing = ET.fromstring(build_pump_zone_scheme_pages(common)[0])
    for e in drawing.iter():
        if e.get('data-spec-component') in ('meter_cold', 'hot:meter'):
            owner = next(r for r in spec if e.get('data-spec-component') in r.component_ids)
            assert f'DN{e.get("data-dn")}' in owner.name
    assert 'DN80*' in ET.tostring(drawing, encoding='unicode')
    assert all('DN80' not in r.type_mark for r in spec if
               set(r.component_ids) & {i.id for i in external_items(common)})


@pytest.mark.parametrize('mode', ['no_pump', 'two_zones', 'no_hot_meter', 'one_inlet', 'unknown_pbs'])
def test_binding_conditions_match_what_is_actually_drawn(common, mode):
    if mode == 'no_pump':
        common.pumps.required = False
    elif mode == 'two_zones':
        common.building.zones = 2
    elif mode == 'no_hot_meter':
        from app.pz.meter_validation import meter_node_key
        common.meters.rows[:] = [r for r in common.meters.rows if meter_node_key(r) != 'hot']
    elif mode == 'one_inlet':
        common.source.inputs_count = 1
    else:
        common.pumps.model = 'Unconfirmed model'
    spec = rows(common)
    drawing = ET.fromstring(build_pump_zone_scheme_pages(common)[0])
    links = {e.get('data-spec-component') for e in drawing.iter() if e.get('data-spec-component')}
    assert {i.id for i in external_items(common)} <= links
    assert all(sum(key in r.component_ids for r in spec) == 1 for key in links)
    if mode == 'no_pump':
        assert not {'station_air', 'station_drain'} & links
    if mode == 'two_zones':
        assert 'station_cold_isolation' not in links
    if mode == 'no_hot_meter':
        assert 'station_heater_isolation' in links and 'hot:valve_before' not in links
    if mode == 'unknown_pbs':
        assert not factory_component_ids(common)


def test_pz_explains_separate_external_scope_without_changing_balance(common):
    from app.pz.generator import generate_pz_html
    before = deepcopy(asdict(common))
    html = generate_pz_html(common)
    for item in external_items(common):
        assert item.name in html
    assert 'отдельно от PBS' in html
    assert 'Т1*' in html and 'Т2*' in html
    assert 'Qрасч = 11,466' in html and 'Hтреб = 50,25' in html
    assert 'Оценочное пересечение кривых и каталожные мощности приведены отдельно' in html
    assert asdict(common) == before


@pytest.mark.parametrize('required', [True, False])
def test_intro_does_not_substitute_intersection_when_design_pair_is_missing(common, required):
    from app.pz.generator import _build_env
    common.pumps.q_design_m3h = 0
    common.pumps.h_design_m = 0
    common.pumps.required = required
    html = _build_env().get_template('pump_design_summary.html').render(pumps=common.pumps)
    assert 'Q/H требует подтверждения' in html
    assert '14,78' not in html and '58,22' not in html
