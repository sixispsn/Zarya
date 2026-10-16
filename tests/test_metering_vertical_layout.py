"""Vertical/flexible layouts preserve graph, published L and hydraulic results."""
from copy import deepcopy
from dataclasses import asdict
from math import dist
from xml.etree import ElementTree as ET

import pytest

from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_joint_audit import audit_direct_joints
from app.data.metering_products import get_metering_catalogue
from app.data.engineering_catalogue import get_engineering_catalogue
from app.pz.metering_flexible import FlexibleConnectionChoice
from scripts.preview_metering_vertical import review_case
from scripts.preview_metering_flanged import flanged_review_project


def chain_for(p):
    s=drawing_state(p)
    selection=resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    return build_metering_chain(p.metering_detail,s,selection)


@pytest.mark.parametrize('vertical',[False,True])
def test_layout_graph_spec_same_nodes_counts_and_no_hydraulic_mutations(vertical):
    p=review_case(vertical); before=deepcopy(asdict(p))
    chain=chain_for(p); layout=build_metering_layout(p)
    assert not layout.issues and layout.parts
    assert {n.id for n in chain.nodes}=={n.id for n in layout.parts}
    assert [(e.before,e.after) for e in layout.links]==list(chain.links)
    rows=build_metering_spec_section(p).rows
    ids=[i for r in rows for i in r.component_ids]
    assert len(ids)==len(set(ids))==len(chain.nodes)
    assert set(ids)=={n.id for n in chain.nodes}
    flex=[r for r in rows if 'flex_inlet' in r.component_ids]
    assert len(flex)==1 and flex[0].qty==p.source.inputs_count
    assert flex[0].catalogue_id==p.metering_detail.flexible_connections['inlet'].catalogue_id
    assert not any('кандидат требует компоновки' in r.name for r in rows)
    for part in layout.parts:
        if part.length_mm is not None:
            assert dist(part.points[0],part.points[-1])*layout.scale==pytest.approx(part.length_mm)
    assert asdict(p)==before
    assert layout.overall_length_mm is None


@pytest.mark.parametrize('orientation',['vertical_up','vertical_down'])
def test_vertical_geometry_direction_text_and_dimensions(orientation):
    p=review_case(True); d=p.metering_detail
    d.flexible_connections={}
    d.assembly_orientation=d.meter_mounting=orientation
    if orientation=='vertical_up':
        # No incorrect upward rotation of the downward-only filter.
        d.catalogue_items.pop('filter'); d.meter_selection_mode='manual'
    layout=build_metering_layout(p)
    assert not layout.issues
    path=chain_for(p).paths[0].nodes
    sign=1 if orientation=='vertical_down' else -1
    for a,b in zip(path,path[1:]):
        assert layout.part(a).points[-1]==layout.part(b).points[0]
        assert sign*(layout.part(b).center[1]-layout.part(a).center[1])>0
    svg=layout_contents(p)[0]
    root=ET.fromstring('<svg>'+svg+'</svg>')
    for g in root.iter('g'):
        if g.get('transform','').startswith('translate'):
            assert not list(g.iter('text'))  # Only ink rotates; annotations remain in paper coordinates.
    assert f'data-vu-orientation="{orientation}"' in svg
    assert 'data-body-dimension="meter"' in svg
    pages=build_metering_detail_pages(p)
    assert f'data-vu-orientation="{orientation}"' in pages[0]
    assert '2. Включение узлов во вводы' not in pages[0]


def test_forbidden_or_unknown_meter_orientation_cannot_bypass_drawing_checks():
    p=review_case(True)
    p.metering_detail.meter_mounting='unknown'
    assert not build_metering_layout(p).parts
    p=flanged_review_project(80)
    p.metering_detail.assembly_orientation=p.metering_detail.meter_mounting='vertical_down'
    layout=build_metering_layout(p)
    assert not layout.parts and any('паспорт не разрешает' in s for s in layout.issues)


def test_upward_filter_and_mixed_axis_need_different_engineered_layout():
    p=review_case(True); d=p.metering_detail
    d.assembly_orientation=d.meter_mounting='vertical_up'
    l=build_metering_layout(p)
    assert not l.parts and any('паспорт не разрешает' in e for e in l.issues)
    d.component_orientations['filter']='horizontal_dial_up'
    l=build_metering_layout(p)
    assert not l.parts and any('повороты' in e for e in l.issues)


def test_flexible_before_meter_never_occupies_protected_straight_section():
    p=flanged_review_project(80); d=p.metering_detail
    from app.pz.metering_pipes import MeteringPipeSection
    d.pipe_sections['before_meter']=MeteringPipeSection(material='steel',nominal_dn=80,
        outer_diameter_mm=89,wall_thickness_mm=4,joining='welded',geometry_source='Test')
    c=get_engineering_catalogue(); ident='rushwork-501-dn80'
    d.flexible_connections={'before_meter':FlexibleConnectionChoice(ident,c.fingerprint(ident))}
    chain=chain_for(p); ids=chain.paths[0].nodes
    assert ids[ids.index('filter'):ids.index('meter')+1]==('filter','flex_before_meter','kit_in','meter')
    assert chain.node('kit_in').minimum_length_mm==240
    assert build_metering_layout(p).part('flex_before_meter').kind=='flexible_connection'
    row=next(r for r in build_metering_spec_section(p).rows if 'flex_before_meter' in r.component_ids)
    assert row.diagram_pos=='Г2' and row.qty==1


def test_free_flexible_length_never_becomes_installation_size_by_manual_override():
    p=review_case(False); d=p.metering_detail
    part=build_metering_layout(p).part('flex_inlet')
    assert part.length_mm==135 and part.dimension_basis=='free'
    d.mounting.spans['flex_inlet']={'length_mm':135,'source':'manual'}
    r=resolve_mounting(p)
    s=next(s for c in r.chains for s in c.spans if s.id=='flex_inlet')
    assert s.length_mm is None and any('ручной размер не заменяет' in i for i in r.issues)
    d.mounting.spans={}
    d.flexible_connections['inlet'].mounting_precompression_mm=4
    part=build_metering_layout(p).part('flex_inlet')
    assert part.length_mm==131 and part.dimension_basis=='installed'
    s=next(s for c in resolve_mounting(p).chains for s in c.spans if s.id=='flex_inlet')
    assert s.length_mm==131


@pytest.mark.parametrize('value',[0,2,5.1,float('nan'),True])
def test_invalid_precompression_is_not_dimensioned_or_purchased(value):
    p=review_case(False); p.metering_detail.flexible_connections['inlet'].mounting_precompression_mm=value
    assert p.metering_detail.validate()
    with pytest.raises(ValueError,match='предварительное сжатие'):
        build_metering_layout(p)
    with pytest.raises(ValueError,match='предварительное сжатие'):
        build_metering_spec_section(p)


def test_stale_flex_cannot_disappear_or_keep_old_catalogue_quantity():
    p=review_case(False); p.metering_detail.flexible_connections['inlet'].catalogue_fingerprint='stale'
    chain=chain_for(p)
    assert chain.node('flex_inlet').catalogue_id is None
    part=build_metering_layout(p).part('flex_inlet')
    assert part.length_mm is None and not part.catalogue_id
    rows=build_metering_spec_section(p).rows
    row=next(r for r in rows if 'flex_inlet' in r.component_ids)
    assert row.qty is None and not row.catalogue_id


def test_flexible_ports_are_real_flange_not_generic_thread():
    p=review_case(True); chain=chain_for(p)
    check=next(c for c in audit_direct_joints(chain,get_metering_catalogue(),inlet_dn=50)
               if c.before=='flex_inlet' and c.after=='inlet_valve')
    assert check.left.flange and check.left.seal=='rubber_lip'
    assert check.status=='incompatible'  # No hidden adapter to the threaded valve.


def test_vertical_length_limit_does_not_silently_change_selected_scale():
    p=review_case(True); p.metering_detail.mounting.scale=5
    l=build_metering_layout(p)
    assert l.scale==5 and not l.parts and any('не помещается' in i for i in l.issues)


@pytest.mark.parametrize('dn,scale',[(65,20),(80,20),(100,20),(150,20),(200,25),(250,50)])
def test_large_upward_layout_retains_unconfirmed_armature_and_straights(dn,scale):
    p=flanged_review_project(dn); d=p.metering_detail
    d.assembly_orientation=d.meter_mounting='vertical_up';d.mounting.scale=scale
    l=build_metering_layout(p)
    assert not l.issues and l.parts
    assert l.part('kit_in').length_mm==dn*3
    assert l.part('kit_out').length_mm==dn
    contents=layout_contents(p)
    assert 'ещё не подтверждено паспортом' in contents[0]
    assert 'data-installation-ready="false"' in contents[0]
