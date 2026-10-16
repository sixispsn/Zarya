from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from app.analysis.architecture_confirmation import confirmed_architecture_section_to_mapping
from app.analysis.architecture_import_store import ArchitectureImportStore
from app.analysis.plan_route_measurement import measurement_context
from app.main import app
from app.web import architecture_import
from tests.test_architecture_confirmation import _input
from tests.test_architecture_pdf import _vector_pdf


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    store=ArchitectureImportStore(tmp_path)
    monkeypatch.setattr(architecture_import,'_STORE',store)
    import_id=store.create('Контрольный план.pdf',_vector_pdf())
    survey=store.survey(import_id)
    architecture=replace(_input(),source_sha256=survey.sha256,source_name=survey.original_name)
    store.save_confirmations(import_id,confirmed_architecture_section_to_mapping(architecture))
    _,context_hash=measurement_context(architecture,survey,1)
    payload={'revision':0,'trace':{
        'route_id':'K1:route','system':'K1','floor':1,'context_hash':context_hash,
        'start_node':'source','end_node':'outlet',
        'vertices':[{'x_pt':0,'y_pt':0},{'x_pt':75,'y_pt':0},{'x_pt':75,'y_pt':100}],
        'vertical_mode':'slope','start_elevation_m':.2,'slope':.02,'reviewed':True,
    }}
    with TestClient(app) as client:
        yield client,store,import_id,payload,architecture


def test_workspace_persistence_export_and_replacement(workspace):
    client,store,i,payload,_=workspace
    page=client.get(f'/wizard/architecture/{i}/routes')
    assert page.status_code==200 and 'Измерить трассу' in page.text
    assert 'data-context-hash' in page.text
    saved=client.post(f'/wizard/architecture/{i}/routes/save',json=payload)
    assert saved.status_code==200, saved.text
    assert saved.json()['measurement']['plan_length_m']==7
    assert saved.json()['measurement']['spatial_length_m']>7
    exported=client.get(f'/wizard/architecture/{i}/routes.json')
    assert exported.status_code==200 and not exported.json()['purchase_ready']
    assert len(exported.json()['routes'])==1
    assert exported.headers['cache-control']=='private, no-store'
    page=client.get(f'/wizard/architecture/{i}/routes')
    assert 'data-route-edit="K1:route"' in page.text
    assert 'data-saved-route-traces' in page.text
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==422
    payload['revision']=1
    payload['trace']['vertical_mode']='unknown'
    payload['trace']['slope']=None
    payload['trace']['start_elevation_m']=None
    payload['trace']['reviewed']=False
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==200
    assert len(store.load_route_traces(i)['traces'])==1
    assert 'Нужны отметки' in client.get(f'/wizard/architecture/{i}/routes').text
    deleted=client.post(f'/wizard/architecture/{i}/routes/delete',data={'revision':'2','route_id':'K1:route'})
    assert deleted.status_code==200 and not store.load_route_traces(i)['traces']


def test_changed_calibration_retains_trace_but_revokes_its_number(workspace):
    client,store,i,payload,a=workspace
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==200
    floor=a.floors[0]
    a=replace(a,floors=(replace(floor,scale=replace(floor.scale,real_distance_m=5)),))
    store.save_confirmations(i,confirmed_architecture_section_to_mapping(a))
    export=client.get(f'/wizard/architecture/{i}/routes.json').json()
    row=export['routes'][0]
    assert row['measurement'] is None and 'изменились' in row['error']
    assert row['trace']['vertices']
    page=client.get(f'/wizard/architecture/{i}/routes')
    assert page.status_code==200 and 'Проверьте трассу повторно' in page.text
    payload['revision']=1
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==422


def test_cross_origin_writes_are_rejected(workspace):
    client,store,i,payload,_=workspace
    response=client.post(f'/wizard/architecture/{i}/routes/save',json=payload,headers={'Origin':'https://evil.example'})
    assert response.status_code==403 and not store.load_route_traces(i)['traces']


@pytest.mark.parametrize('bad', [{'trace':None},[],{'revision':0,'trace':{}}, {'revision':False,'trace':{}}])
def test_bad_requests_do_not_leave_partial_records(workspace,bad):
    client,store,i,_,_=workspace
    r=client.post(f'/wizard/architecture/{i}/routes/save',json=bad)
    assert r.status_code==422 and not store.load_route_traces(i)['traces']


def test_route_points_outside_plan_and_nonfinite_are_not_saved(workspace):
    client,store,i,payload,_=workspace
    payload['trace']['vertices'][0]['x_pt']=-5
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==422
    assert not store.load_route_traces(i)['traces']


def test_measurement_store_has_private_atomic_files(workspace):
    client,store,i,payload,_=workspace
    assert client.post(f'/wizard/architecture/{i}/routes/save',json=payload).status_code==200
    assert (store.root/i/'route_traces.json').stat().st_mode & 0o777 == 0o600
    assert not list((store.root/i).glob('routes-*.tmp'))
