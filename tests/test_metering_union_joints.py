"""Factory meter interfaces and signed axial stack, independent of hydraulics."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.pz.metering_chain import ChainNode, ChainPath, MeteringChain
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_joint_audit import audit_direct_joints, meter_kit_topology_issues
from app.pz.metering_layout import layout_contents
from app.pz.metering_mounting import MeteringMounting, joint_axial_delta, resolve_mounting
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_detail import catalogue_review_project, review_project
from tests.test_metering_layout import chain_for


def test_factory_kit_ports_are_directional_and_meter_is_not_a_generic_thread():
    p=catalogue_review_project(); chain=chain_for(p)
    checks={c.id:c for c in audit_direct_joints(chain,get_metering_catalogue())}
    pipe=checks['filter>kit_in']
    assert pipe.status=='ports_match'
    assert pipe.left.thread==pipe.right.thread=='1 1/4'
    assert pipe.left.seal==pipe.right.seal=='thread'
    for key in ('kit_in>meter','meter>kit_out'):
        c=checks[key]
        assert c.status=='ports_match'
        assert c.left.thread==c.right.thread=='1 1/2'
        assert c.left.seal==c.right.seal=='flat_gasket'
    assert checks['kit_out>service_before'].left.thread=='1 1/4'
    assert not meter_kit_topology_issues(chain,get_metering_catalogue())


def test_matching_thread_size_does_not_allow_a_generic_fitting_on_a_meter_face():
    nodes=(ChainNode('female','Обычная муфта','valtec-vt214-dn40'),
           ChainNode('meter','Счётчик','decast-vskm90-dg-dn32'))
    chain=MeteringChain(nodes,(ChainPath('main','Поток',('female','meter')),),1)
    check=audit_direct_joints(chain,get_metering_catalogue())[0]
    assert check.left.thread==check.right.thread=='1 1/2'
    assert check.status=='incompatible' and 'не взаимозаменяемы' in check.reason
    assert joint_axial_delta({'overlap_mm':5},check)[0] is None


def test_another_meter_family_cannot_borrow_the_kit_by_thread_size():
    from types import SimpleNamespace
    c=get_metering_catalogue(); kits=dict(c.connection_kits)
    k=kits['decast-vskm90-kit-dn32']
    kits['other']=replace(k,id='other',meter_ids=('other-meter',))
    catalog=SimpleNamespace(connection_kits=kits,products=c.products,connectors=c.connectors,
                            thread_connectors=c.thread_connectors,reducers=c.reducers)
    nodes=(ChainNode('kit_in','Чужой комплект','other'),
           ChainNode('meter','Счётчик','decast-vskm90-dg-dn32'))
    chain=MeteringChain(nodes,(ChainPath('main','Поток',('kit_in','meter')),),1)
    check=audit_direct_joints(chain,catalog)[0]
    assert check.status=='incompatible' and 'не относится' in check.reason


@pytest.mark.parametrize('inserted',['reducer_in','gauge_cock'])
def test_no_reducer_or_instrument_inserted_in_factory_straight_section(inserted):
    chain=chain_for(catalogue_review_project()); main=chain.paths[0]
    ids=list(main.nodes)
    if inserted in ids:
        ids.remove(inserted)
    ids.insert(ids.index('meter'),inserted)
    changed=replace(chain,paths=(replace(main,nodes=tuple(ids)),)+chain.paths[1:])
    assert any('посторонняя деталь' in s for s in meter_kit_topology_issues(changed,get_metering_catalogue()))


@pytest.mark.parametrize('anchor',['kit_in','meter','kit_out'])
def test_no_takeoff_from_factory_straight_zone(anchor):
    chain=chain_for(catalogue_review_project())
    paths=tuple(replace(p,nodes=(anchor,)+p.nodes[1:]) if p.id=='gauge' else p for p in chain.paths)
    assert any('отбор' in s for s in meter_kit_topology_issues(replace(chain,paths=paths),get_metering_catalogue()))


def test_gasket_is_added_thread_engagement_subtracted_neither_is_inferred():
    r=resolve_mounting(catalogue_review_project())
    checks={c.id:c for c in r.joint_checks}
    face=checks['kit_in>meter']; thread=checks['filter>kit_in']
    assert joint_axial_delta({'face_gap_mm':2.5},face)==(2.5,'')
    assert joint_axial_delta({'overlap_mm':8},thread)==(-8,'')
    assert joint_axial_delta({'overlap_mm':0},face)[0] is None
    assert joint_axial_delta({'face_gap_mm':2.5},thread)[0] is None
    assert joint_axial_delta({'overlap_mm':8},checks['kit_out>service_before'])[0] is None


@pytest.mark.parametrize('row',[
    {}, {'overlap_mm':2,'face_gap_mm':2}, {'face_gap_mm':0}, {'face_gap_mm':-1},
    {'face_gap_mm':True}, {'face_gap_mm':float('nan')}, {'overlap_mm':'5'},
])
def test_invalid_axial_stack_rejected(row):
    assert MeteringMounting(joints={'kit_in>meter':{**row,'source':'test'}}).validate()


def test_stack_adds_each_gasket_once_and_roundtrips_without_mutating_project(monkeypatch):
    p=catalogue_review_project(); chain=chain_for(p)
    # Synthetic dimensions exercise the solver; never used as product defaults.
    ids=('kit_in','meter','kit_out')
    fragment=replace(chain,nodes=tuple(chain.node(n) for n in ids),
                     paths=(ChainPath('main','Test',ids),))
    monkeypatch.setattr('app.pz.metering_chain.build_metering_chain',lambda *a:fragment)
    p.metering_detail.mounting=MeteringMounting(enabled=True,
        spans={n:{'length_mm':l,'source':'синтетическая геометрия теста'} for n,l in [('kit_in',100),('kit_out',30)]},
        joints={key:{'face_gap_mm':2,'source':'синтетическая геометрия теста'} for key in ('kit_in>meter','meter>kit_out')})
    copied=MeteringDetailData(**deepcopy(asdict(p.metering_detail)))
    assert copied.mounting==p.metering_detail.mounting
    before=deepcopy(asdict(p)); r=resolve_mounting(p)
    assert r.chains[0].length_mm==394
    assert r.chains[0].offsets_mm==(0,102,364)
    assert asdict(p)==before
    p.metering_detail.mounting.joints['kit_in>meter']={'overlap_mm':2,'source':'ошибка'}
    assert resolve_mounting(p).chains[0].length_mm is None


@pytest.mark.parametrize('count',[1,2])
def test_kit_parts_in_specification_are_not_purchased_twice(count):
    p=catalogue_review_project(); p.source.inputs_count=count
    rows=build_metering_spec_section(p).rows
    kits=[r for r in rows if 'kit_in' in r.component_ids or 'kit_out' in r.component_ids]
    assert len(kits)==1 and kits[0].qty==count and kits[0].unit=='компл.'
    assert 'Присоединитель с накидной гайкой - 2 шт.' in kits[0].note
    assert 'Плоская прокладка - 2 шт.' in kits[0].note
    assert not any('Плоская прокладка' in r.name for r in rows)


def test_missing_or_rejected_kit_does_not_keep_previous_interface_approval():
    p=catalogue_review_project(); p.metering_detail.catalogue_items['meter_connections']='decast-vskm90-kit-dn25'
    chain=chain_for(p)
    assert chain.node('kit_in').catalogue_id is None
    assert next(c for c in audit_direct_joints(chain,get_metering_catalogue()) if c.id=='kit_in>meter').status=='unresolved'
    assert not any('data-protected-meter-kit' in s for s in layout_contents(p))


def test_kit_faces_render_from_selected_model_without_changing_hydraulics():
    p=catalogue_review_project(); before=deepcopy(asdict(p))
    pages=layout_contents(p)
    root=ET.fromstring('<svg>'+''.join(pages)+'</svg>')
    assert len([e for e in root.iter() if e.get('data-kit-gasket')])==2
    assert len([e for e in root.iter() if e.get('data-kit-union-nut')])==2
    assert len([e for e in root.iter() if e.get('data-protected-meter-kit')])==1
    assert asdict(p)==before
    assert not any('data-kit-gasket' in s for s in layout_contents(review_project()))
