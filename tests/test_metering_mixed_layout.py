from copy import deepcopy
from dataclasses import asdict
from math import dist

import pytest

from scripts.preview_metering_mixed import mixed_review_project
from scripts.preview_metering_flanged import flanged_review_project
from app.data.metering_products import get_metering_catalogue
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_joint_audit import audit_direct_joints


def selected_chain(p):
    s=drawing_state(p)
    selection=resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    return selection,build_metering_chain(p.metering_detail,s,selection)


@pytest.mark.parametrize('direction',['vertical_up','vertical_down'])
def test_mixed_axes_connected_and_true_two_leg_elbow_dimensions(direction):
    p=mixed_review_project(direction); before=deepcopy(asdict(p))
    selection,chain=selected_chain(p); l=build_metering_layout(p)
    assert not selection.errors and not l.issues and l.parts
    ids=chain.paths[0].nodes
    for a,b in zip(ids,ids[1:]):
        assert l.part(a).points[-1]==l.part(b).points[0]
    f=l.part('filter'); m=l.part('meter')
    assert f.points[0][1]==f.points[1][1] and f.points[1][0]>f.points[0][0]
    assert m.points[0][0]==m.points[1][0]
    assert (m.points[1][1]>m.points[0][1])==(direction=='vertical_down')
    for name in ('filter_turn_in','filter_turn_out'):
        part=l.part(name); a,c,b=part.points
        assert part.length_mm is None and part.center_to_face_mm==46
        assert dist(a,c)*l.scale==pytest.approx(46)
        assert dist(c,b)*l.scale==pytest.approx(46)
        assert (c[0]-a[0])*(b[0]-c[0])+(c[1]-a[1])*(b[1]-c[1])==pytest.approx(0)
    rows=build_metering_spec_section(p).rows
    owned=[i for r in rows for i in r.component_ids]
    assert len(owned)==len(set(owned))==len(chain.nodes)
    assert set(owned)=={n.id for n in l.parts}
    bends=[r for r in rows if r.diagram_pos in ('О1','О2')]
    assert len(bends)==2 and all(r.qty==1 and 'A=46' in r.note for r in bends)
    for part in l.parts:
        if part.length_mm is not None:
            assert dist(part.points[0],part.points[-1])*l.scale==pytest.approx(part.length_mm)
    assert asdict(p)==before and l.overall_length_mm is None
    # Persistence is the same supported input path as API/YAML; no hidden work.
    restored=MeteringDetailData(**asdict(p.metering_detail))
    assert not restored.validate() and asdict(restored)==asdict(p.metering_detail)


def test_filter_female_ports_require_real_joining_nodes():
    p=mixed_review_project(); _,chain=selected_chain(p)
    ids=chain.paths[0].nodes
    assert ids[ids.index('filter_turn_in'):ids.index('filter_turn_out')+1]==(
        'filter_turn_in','joint_filter_turn_in__filter','filter','joint_filter__filter_turn_out','filter_turn_out')
    joints=audit_direct_joints(chain,get_metering_catalogue(),inlet_dn=32)
    assert all(c.status=='ports_match' for c in joints if 'filter_turn' in c.id)
    assert chain.node('joint_filter__filter_turn_out').catalogue_id is None


@pytest.mark.parametrize('mode',['missing','wrong_dn','wrong_kind','stale','pressure','origin'])
def test_missing_or_ineligible_turns_never_rotated_or_substituted(mode):
    p=mixed_review_project(); d=p.metering_detail
    if mode=='missing': d.fitting_items.pop('filter_turn_in')
    elif mode=='wrong_dn': d.fitting_items['filter_turn_in']='valtec-vtr090-dn50'
    elif mode=='wrong_kind': d.fitting_items['filter_turn_in']='valtec-vtr130-dn32'
    elif mode=='stale': d.catalogue_revision='old'
    elif mode=='pressure': d.design_pressure_bar=30
    else: d.russian_equipment_only=True
    l=build_metering_layout(p)
    assert not l.parts and l.issues
    row=next(r for r in build_metering_spec_section(p).rows if r.diagram_pos=='О1')
    assert row.qty is None and not row.catalogue_id


def test_other_mixed_axes_still_rejected_and_no_old_turn_assignments():
    p=mixed_review_project(); p.metering_detail.component_orientations['meter_valves']='horizontal_dial_up'
    assert not build_metering_layout(p).parts
    p=mixed_review_project(); p.metering_detail.component_orientations={}
    selected,_=selected_chain(p)
    assert any('Узел отсутствует' in e for e in selected.errors)


def test_bend_is_not_an_axial_mounting_length_even_with_manual_override():
    p=mixed_review_project(); d=p.metering_detail
    d.mounting.spans={'filter_turn_in':{'length_mm':92,'source':'ручной размер'}}
    r=resolve_mounting(p)
    assert any('два размера A' in e for e in r.issues)
    assert r.chains[0].length_mm is None
    assert next(s for s in r.chains[0].spans if s.id=='filter_turn_in').length_mm is None


def test_mixed_render_uses_actual_axes_and_separate_bend_dimensions():
    p=mixed_review_project()
    svg=layout_contents(p)[0]
    assert 'с горизонтальным фильтром' in svg
    assert 'data-bend-dimensions="filter_turn_in"' in svg
    assert 'data-center-to-face-mm="46"' in svg
    assert 'data-unmeasured-route="true"' in svg  # bypass still not pipe takeoff
    assert 'data-bend-dimensions="filter_turn_out"' in build_metering_detail_pages(p)[0]


def test_flanged_mixed_retains_meter_straights_and_exact_elbow_A():
    p=flanged_review_project(80); d=p.metering_detail
    d.assembly_orientation=d.meter_mounting='vertical_up'
    d.component_orientations={'filter':'horizontal_dial_up'}
    d.fitting_items={r:'vodopribor-elbow90-dn80' for r in ('filter_turn_in','filter_turn_out')}
    d.mounting.scale=20
    l=build_metering_layout(p)
    assert l.parts and not l.issues
    assert l.part('kit_in').length_mm==240 and l.part('kit_out').length_mm==80
    assert l.part('filter_turn_out').center_to_face_mm==150
    assert l.part('filter_turn_out').points[-1]==l.part('kit_in').points[0]


def test_mixed_configuration_survives_public_yaml_builder_and_counts_per_inlet():
    from app.intake.yaml_io import load_request, dump_request
    from app.intake.project_builder import build_project
    req=load_request('''document: {object_name: Жилой дом}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
''')
    p=mixed_review_project()
    req.metering_detail=p.metering_detail
    restored=load_request(dump_request(req))
    built=build_project(restored)
    assert asdict(built.metering_detail)==asdict(p.metering_detail)
    assert built.metering_detail is not restored.metering_detail
    p.metering_detail=built.metering_detail
    p.source.inputs_count=2
    assert build_metering_layout(p).parts
    rows=build_metering_spec_section(p).rows
    assert all(r.qty==2 for r in rows if r.diagram_pos in ('О1','О2'))
