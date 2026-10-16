"""User-approved annotation is not approval of additional station hardware."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common
from app.pz.water_station_review import (
    branches, connected_network, factory_component_ids, review_station,
    service_access_requirements,
)
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


def test_access_is_requirement_not_installed_or_counted(common):
    from app.pz.spec import build_specification
    before = deepcopy(asdict(common))
    network = connected_network(common)
    rows = [r for s in build_specification(common).sections for r in s.rows]
    report = review_station(common)
    assert report['access_requirements'] == service_access_requirements(common)
    assert len(report['access_requirements']) == 2
    for a, b in zip(report['access_requirements'], branches(common)):
        assert a['target'] == b['pocket']
        assert a['location'] == f'Полость {b["check_mark"]} - {b["outlet_mark"]}'
        assert a['status'] == 'requires_design' and not a['installed']
        assert a['id'] not in factory_component_ids(common)
        assert a['id'] not in {n.id for n in network.nodes}
        assert not any(p.node == a['target'] for p in network.ports)
        assert not any(a['id'] in r.component_ids for r in rows)
    assert all(not s['removal']['safe_to_remove'] for s in report['scenarios'])
    assert all(s['removal']['pressure_relief'] == 'blocked' for s in report['scenarios'])
    assert connected_network(common) == network
    assert asdict(common) == before


def test_leader_points_at_pocket_without_drawing_new_hardware(common):
    svg = build_pump_zone_scheme_pages(common)[0]
    root = ET.fromstring(svg)
    for a in service_access_requirements(common):
        groups = [g for g in root.iter() if g.get('data-design-requirement') == a['id']]
        assert len(groups) == 1
        g = groups[0]
        assert g.get('data-target-node') == a['target']
        assert a['mark']+'*' in ''.join(g.itertext())
        assert not any(e.get('data-component') or e.get('data-pipe') for e in g.iter())
        assert '112' in ET.tostring(g, encoding='unicode')  # between НОК y119 and НЗ y105
    assert 'не установленная арматура' in svg


@pytest.mark.parametrize('required,working,reserve', [(False,1,1), (True,2,1), (True,1,0)])
def test_no_fabricated_access_on_other_topology(common, required, working, reserve):
    common.pumps.required = required
    common.pumps.working_units = working
    common.pumps.reserve_units = reserve
    assert not service_access_requirements(common)


def test_pz_review_and_studio_share_requirement_without_new_input(common):
    from app.pz.generator import generate_pz_html
    from app.pz.water_station_review_drawing import station_review_contents
    html = generate_pz_html(common)
    audit = ''.join(station_review_contents(common))
    for a in service_access_requirements(common):
        assert a['mark']+'*' in html and a['mark']+'*' in audit
        assert a['location'] in html and a['location'] in audit
    assert 'арматура не выбрана, в СО не добавлена' in html
    studio = Path('app/web/static/studio.js').read_text()
    fn = studio.split('function waterStationReview(report)',1)[1].split('function originResults',1)[0]
    assert 'report.access_requirements' in fn
    assert '<input' not in fn and '<select' not in fn
