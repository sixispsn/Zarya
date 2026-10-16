"""G.1 presentation must not replace the approved hydraulic/topology model."""
from copy import deepcopy
from dataclasses import asdict
import xml.etree.ElementTree as ET

import pytest

from app.pz.metering_detail import build_metering_detail_pages
from app.pz.metering_principle_drawing import common_principle_contents
from app.pz.metering_layout import build_metering_layout
from tests.test_metering_common_inlets import common_project, chain_for


@pytest.mark.parametrize('serviceable',[False,True])
def test_first_sheet_draws_one_real_meter_all_main_links_and_service_branches(serviceable):
    p=common_project()
    if serviceable:
        p.metering_detail.maintenance_layout='serviceable'
    s,chain=chain_for(p)
    before=deepcopy(asdict(p))
    dimensional=build_metering_layout(p,s)
    root=ET.fromstring(build_metering_detail_pages(p)[0])
    ids=[e.get('data-vu-component') for e in root.iter() if e.get('data-vu-component')]
    assert ids.count('meter')==1
    assert {'filter','check_valve','gauge','gauge_cock','control_cock_1','control_cock_2',
            'control_cap_1','control_cap_2','supply_valve_1','supply_valve_2','bypass_valve'} <= set(ids)
    assert not any(e.get('data-common-vu-reference') for e in root.iter())
    edges={tuple(e.get('data-chain-edge').split(':')) for e in root.iter() if e.get('data-chain-edge')}
    assert edges==set(zip(chain.paths[0].nodes,chain.paths[0].nodes[1:]))
    branches={e.get('data-chain-path'):tuple(e.get('data-chain-nodes').split())
              for e in root.iter() if e.get('data-chain-path')}
    assert branches=={p.id:p.nodes for p in chain.paths[1:]}
    assert asdict(p)==before and build_metering_layout(p,s)==dimensional
    assert len([e for e in root.iter() if e.get('data-wall-crossing')])==2
    assert any(e.get('data-askue') for e in root.iter())
    assert any(e.get('data-vu-room-contour') for e in root.iter())


def test_common_data_table_survives_on_separate_sheet_and_notes_are_honest():
    p=common_project()
    pages=build_metering_detail_pages(p)
    assert 'data-vu-parameter-table' not in pages[0]
    data=[s for s in pages if 'Общий водомерный узел. Данные и позиции' in s]
    assert len(data)==1 and 'data-vu-parameter-table' in data[0]
    assert 'Переключающая обвязка нижнего примера' in data[0]
    assert 'data-principle-topology="merge-before-meter"' in pages[0]


def test_drawing_keeps_missing_data_missing_and_uses_thin_leader_with_shelf():
    p=common_project()
    p.metering_detail.inlet_elevation_m=None
    p.metering_detail.bypass_dn=None
    p.source.elev_header_m=-9.99
    s,_=chain_for(p)
    svg=common_principle_contents(p,s)
    assert 'Отм. оси' not in svg and '-9,99' not in svg
    assert 'DN — уточнить' in svg
    root=ET.fromstring('<svg>'+svg+'</svg>')
    leader=next(e for e in root.iter() if e.get('data-leader-id')=='common-meter')
    assert leader.get('data-line-width-mm')=='0.25'
    assert leader.get('data-text-height-mm')=='3.5'
    assert leader.get('data-title-above-shelf')=='true'
    assert leader.get('data-detail-below-shelf')=='true'
    assert any(e.get('data-leader-arrow') for e in leader)
