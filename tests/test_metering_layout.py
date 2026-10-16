from copy import deepcopy
from dataclasses import asdict
import math
import xml.etree.ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_joint_audit import audit_direct_joints
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_detail import catalogue_review_project, review_project


def test_composition_grid_is_closed_on_all_continuation_sheets(monkeypatch):
    from app.pz.metering_layout import _composition_pages
    p = catalogue_review_project()
    state = drawing_state(p)
    spec = build_metering_spec_section(p)
    spec.rows = spec.rows * 5  # stress pagination only, never production data
    monkeypatch.setattr('app.pz.metering_spec.build_metering_spec_section', lambda _: spec)
    pages = _composition_pages(p, state, build_metering_layout(p))
    assert len(pages) > 1
    for page in pages:
        grid = ET.fromstring('<svg>'+page+'</svg>').find('.//*[@data-vu-composition-grid]')
        assert grid is not None
        lines = {(float(e.get('x1')),float(e.get('y1')),float(e.get('x2')),float(e.get('y2')))
                 for e in grid.findall('line')}
        assert {(x,29,x,224) for x in (28,48,335,405)} <= lines
        assert (28,29,405,29) in lines and (28,224,405,224) in lines


def chain_for(project):
    s=drawing_state(project)
    selected=resolve_metering_products(project,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    return build_metering_chain(project.metering_detail,s,selected)


@pytest.mark.parametrize('factory',[catalogue_review_project,lambda:review_project(2)])
def test_every_component_and_link_survives_layout_and_specification(factory):
    p=factory(); before=deepcopy(asdict(p))
    layout=build_metering_layout(p); chain=chain_for(p)
    assert not layout.issues
    assert {n.id for n in layout.parts}=={n.id for n in chain.nodes}
    assert [(e.before,e.after) for e in layout.links]==list(chain.links)
    assert set(n.id for n in layout.parts)=={id for r in build_metering_spec_section(p).rows for id in r.component_ids}
    assert asdict(p)==before
    assert layout.overall_length_mm is None


@pytest.mark.parametrize('scale',[5,10,20])
def test_body_lengths_are_scaled_but_bypass_is_not_stretched(scale):
    p=catalogue_review_project(); p.metering_detail.mounting.scale=scale
    layout=build_metering_layout(p)
    assert not layout.issues
    for part in layout.parts:
        if part.length_mm is not None:
            assert math.dist(part.points[0],part.points[-1])*scale==pytest.approx(part.length_mm)
    assert layout.part('meter').length_mm==260
    assert layout.part('bypass_valve').length_mm==101
    assert layout.part('bypass_route_in').points[0]==layout.part('bypass_start').center
    assert layout.part('bypass_route_out').points[-1]==layout.part('bypass_end').center
    assert layout.part('bypass_route_in').length_mm is None
    assert layout.part('kit_in').length_mm is None
    # One stock kit still owns two drawn halves, quantity not inferred from it.
    row=next(r for r in build_metering_spec_section(p).rows if 'kit_in' in r.component_ids)
    assert row.qty==1 and row.unit=='компл.'


def test_oversized_drawing_does_not_silently_rescale():
    p=catalogue_review_project(); p.metering_detail.mounting.scale=1
    r=build_metering_layout(p)
    assert r.issues and not r.parts and r.scale==1
    assert 'не помещается' in layout_contents(p)[0]


def test_two_female_ports_cannot_be_fixed_by_an_overlap_number():
    p=catalogue_review_project()
    from app.pz.metering_chain import ChainNode, ChainPath, MeteringChain
    raw=MeteringChain((ChainNode('valve_before','Кран','valtec-vt214-dn32'),
                      ChainNode('filter','Фильтр','valtec-vt192-dn32')),
                     (ChainPath('main','Линия',('valve_before','filter')),),1)
    c=audit_direct_joints(raw,get_metering_catalogue())[0]
    assert c.status=='incompatible' and c.left.sex==c.right.sex=='female'
    p.metering_detail.mounting.joints['valve_before>filter']={'overlap_mm':8,'source':'ввод пользователя'}
    r=resolve_mounting(p)
    assert not r.dimensions_complete
    assert any('связь отсутствует' in issue for issue in r.issues)  # direct joint is stale
    ids=chain_for(p).paths[0].nodes
    assert ids[ids.index('valve_before')+1]=='joint_valve_before__filter'
    nipple=chain_for(p).node('joint_valve_before__filter')
    assert nipple.catalogue_id is None and nipple.required_thread=='1 1/4'
    row=next(r for r in build_metering_spec_section(p).rows if nipple.id in r.component_ids)
    assert row.qty==1 and row.diagram_pos=='С7'
    assert row.catalogue_id=='' and 'уточнить' in row.note
    assert next(c for c in r.joint_checks if c.id=='valve_before>'+nipple.id).status=='ports_match'
    good=next(c for c in r.joint_checks if c.id=='check_valve>outlet_thread')
    assert good.status=='ports_match'
    assert next(c for c in r.joint_checks if c.id=='outlet_thread>outlet_connector').status=='ports_match'
    union=next(c for c in r.joint_checks if c.id=='kit_in>meter')
    assert union.status=='ports_match' and union.left.seal==union.right.seal=='flat_gasket'
    assert r.chains[0].length_mm is None  # matching faces do not invent installed lengths


def test_completed_female_joint_is_idempotent_and_does_not_choose_conflicting_brand():
    from app.pz.metering_joint_audit import complete_female_joints
    p=catalogue_review_project(); chain=chain_for(p)
    assert complete_female_joints(chain,p.metering_detail)==chain
    r=build_metering_layout(p)
    nipple=r.part('joint_valve_before__filter')
    assert nipple.length_mm is None and not nipple.catalogue_id
    # Unknown selected models don't license guessing a nipple from DN alone.
    assert not any(n.role=='inline_nipple' for n in chain_for(review_project()).nodes)


def test_unknown_origin_is_not_drawn_as_selected_equipment():
    p=catalogue_review_project(); p.metering_detail.russian_equipment_only=True
    r=build_metering_layout(p)
    assert r.part('inlet_valve').catalogue_id==''
    assert r.part('inlet_valve').length_mm is None
    assert r.part('meter').length_mm==260


def test_connected_sheet_is_in_the_ordinary_pdf_pipeline():
    p=catalogue_review_project(); p.metering_detail.mounting.enabled=True
    pages=build_metering_detail_pages(p)
    page=next(s for s in pages if 'data-vu-layout=' in s)
    root=ET.fromstring(page)
    ns='{http://www.w3.org/2000/svg}'
    parts=[e for e in root.iter(ns+'g') if e.get('data-vu-component')]
    assert len(parts)==len(chain_for(p).nodes)
    for svg in pages:
        ET.fromstring(svg)
    assert 'data-installation-ready="false"' in page
    assert 'data-vu-layout="connected"' in page


@pytest.mark.parametrize('scale',[5,10,20])
@pytest.mark.parametrize('factory',[catalogue_review_project,lambda:review_project(2)])
def test_inline_and_bypass_parts_touch_without_short_spacing_stubs(scale,factory):
    p=factory(); p.metering_detail.mounting.scale=scale
    p.metering_detail.inline_joint_selection_mode='catalogue_proposal'
    p.metering_detail.service_selection_mode='catalogue_proposal'
    chain=chain_for(p); layout=build_metering_layout(p)
    assert not layout.issues
    links={(e.before,e.after):e for e in layout.links}
    for path in chain.paths:
        for index,(a,b) in enumerate(zip(path.nodes,path.nodes[1:])):
            link=links[a,b]
            # Only the first leg of a service/fire branch needs a paper route
            # from the main axis; it is drawn solid, never treated as stock.
            if path.id not in ('main','bypass') and index == 0:
                assert link.points[0] == layout.part(a).center
                assert link.points[1] == layout.part(b).points[0]
            else:
                assert link.points[0] == link.points[1], (path.id,a,b)


def test_reducer_ports_follow_actual_orientation_not_smaller_meter_assumption():
    from app.pz.metering_chain import ChainNode, ChainPath, MeteringChain
    nodes=(ChainNode('reducer_in','Переход','valtec-vtr580-0907'),
           ChainNode('valve_before','Кран','valtec-vt214-dn50'))
    chain=MeteringChain(nodes,(ChainPath('main','Основная',tuple(n.id for n in nodes)),),1)
    c=audit_direct_joints(chain,get_metering_catalogue(),inlet_dn=32)[0]
    assert c.status=='ports_match' and c.left.thread=='2'
