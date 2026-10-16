from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.water_meters import router
from app.data.engineering_catalogue import get_engineering_catalogue, load_families, plain, _DATA
from app.data.engineering_catalogue_store import export_sqlite
from app.data.metering_products import get_metering_catalogue
from app.intake.yaml_io import load_request, dump_request
from app.intake.project_builder import build_project
from app.pz.metering_pipes import MeteringPipeSection, pipe_checks


PPR = 'proaqua-ppr-sdr6-white-pa10018'
PE11 = 'polyplastic-pe100-sdr11-od63-s5p8'
PE17 = 'polyplastic-pe100-sdr17-od63-s3p8'


def test_existing_ids_dimensions_and_passport_payloads_are_preserved():
    c, old = get_engineering_catalogue(), get_metering_catalogue()
    for group in ('products','fittings','connectors','thread_connectors','reducers','service_products'):
        for ident,p in getattr(old,group).items():
            item = c.items[ident]
            assert dict(item.dimensions_mm) == dict(p.dimensions_mm)
            assert plain(item.native) == plain(p)
            assert item.status == ('conflict' if p.dimension_status == 'passport_nominal' else p.dimension_status)
    assert c.items['saures-r7-din'].kind == 'controller'
    assert c.items['gidrolock-wsp-plus'].status == 'reference_only'


def test_pipe_materials_and_processes_are_independent():
    c = get_engineering_catalogue()
    assert c.items[PPR].material == 'ppr'
    assert c.items[PPR].dn is None and c.items[PPR].inner_diameter_mm == 42
    assert c.items[PE11].inner_diameter_mm == pytest.approx(51.4)
    assert c.items[PE17].inner_diameter_mm == pytest.approx(55.4)
    ew = c.items['stami-ew-10704-s3p5-od76-s3p5']
    ss = c.items['gost9941-12x18n10t-od76-s2']
    assert ew.manufacturing == 'electric_welded_longitudinal' and ew.dn is None
    assert ss.manufacturing == 'seamless_cold_formed' and ss.material == 'stainless_steel'
    assert ew.material != ss.material
    assert c.items['gost3262-ordinary-galvanized_steel-dn65'].dimensions_mm['outer_diameter_mm'] == 75.5
    assert 'gost9941-12x18n10t-od159-s3' not in c.items  # No guessed normative rows.


def test_named_dimensions_do_not_turn_into_axial_lengths():
    c = get_engineering_catalogue()
    p = c.items['gost17375-ex1-90-od26p9-s3p2']
    assert p.dn == 20 and p.dimensions_mm['A'] == 29  # NOT 1.5*DN.
    assert 'L' not in p.dimensions_mm
    p = c.items['proaqua-pa140-white-pa14018p']
    assert p.dimensions_mm['H'] == 105 and p.dimensions_mm['L'] == 126
    assert 'НЕ от оси' in p.dimension_meanings['H']
    assert len(p.ports) == 3 and all(q.dn is None for q in p.ports)


def test_no_nearest_size_no_fake_ru_and_no_quarantine_selection():
    c = get_engineering_catalogue()
    assert not c.search(kind='pipe',material='ppr',dn=63)
    assert c.search(kind='pipe',material='ppr',outer_diameter_mm=63)
    assert not c.search(kind='pipe',outer_diameter_mm=64)
    assert not c.search(kind='pipe',russian_only=True)  # No inferred origin by brand.
    conflict = 'proaqua-ppr-sdr11-white-pa11028'
    assert c.card(conflict)['inner_diameter_mm'] is None
    assert c.items[conflict] not in c.search(kind='pipe')
    with pytest.raises(ValueError,match='conflict'):
        MeteringPipeSection.from_catalogue(conflict,joining='socket_fusion')
    assert c.items['proaqua-pa130-white-pa13028p'].status == 'missing'
    with pytest.raises(ValueError):
        c.require('does-not-exist')


def test_fingerprint_is_stable_unrelated_additions_do_not_invalidate():
    c = get_engineering_catalogue()
    current = c.fingerprint(PPR)
    changed = replace(c,revision='future',items={**c.items,'dummy':c.items[PE11]})
    assert changed.fingerprint(PPR) == current
    item = replace(c.items[PPR],dimensions_mm={'outer_diameter_mm':63,'wall_thickness_mm':10.6})
    assert replace(c,items={**c.items,PPR:item}).fingerprint(PPR) != current
    with pytest.raises(TypeError):
        c.items[PPR].dimensions_mm['outer_diameter_mm'] = 99
    with pytest.raises(TypeError):
        c.sources['proaqua-ppr-2026']['title'] = 'changed'


@pytest.mark.parametrize('changes', [
    {'wall_thickness_mm':8.6}, {'nominal_dn':63}, {'material':'steel'},
    {'catalogue_id':'not-there'}, {'catalogue_fingerprint':''},
    {'joining':'welded'}, {'series':'guessed'}, {'geometry_source':'made-up'},
])
def test_saved_selection_cannot_silently_drift(changes):
    pipe = MeteringPipeSection.from_catalogue(PPR,joining='socket_fusion')
    assert not pipe.validate()
    assert replace(pipe,**changes).validate()
    assert replace(pipe,**changes).inner_diameter_mm is None


def test_selection_requires_pipe_and_explicit_joint():
    with pytest.raises(ValueError):
        MeteringPipeSection.from_catalogue(PPR,joining='flanged')
    with pytest.raises(ValueError):
        MeteringPipeSection.from_catalogue('itap-europa100-g-dn15',joining='threaded')


def test_offline_user_selection_to_project_spec_and_roundtrip():
    from app.pz.metering_spec import build_metering_spec_section
    from scripts.preview_metering_detail import review_project
    app=FastAPI();app.include_router(router);client=TestClient(app)
    result=client.get('/meters/engineering-catalogue/'+PPR+'/pipe-section?joining=socket_fusion')
    assert result.status_code == 200
    selection=result.json()['pipe_section']
    req=load_request('''document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail: {pipe_sections: {}}
''')
    req.metering_detail.pipe_sections['outlet']=MeteringPipeSection(**selection)
    roundtrip=load_request(dump_request(req))
    project=build_project(roundtrip)
    assert asdict(project.metering_detail.pipe_sections['outlet']) == selection
    p=review_project()
    old_meter=deepcopy(asdict(p.meters))
    p.metering_detail.pipe_sections['outlet']=project.metering_detail.pipe_sections['outlet']
    row=next(r for r in build_metering_spec_section(p).rows if r.catalogue_id==PPR)
    assert row.manufacturer == 'PRO AQUA' and 'PA10018' in row.type_mark
    assert row.qty is None and row.unit=='м'  # No length from drawing/size table.
    assert asdict(p.meters) == old_meter
    p.metering_detail.pipe_sections['outlet']=replace(p.metering_detail.pipe_sections['outlet'],wall_thickness_mm=5.8)
    errors,_=pipe_checks(p.metering_detail,bypass=True,fire_branch=False)
    assert any('расходится с каталогом' in e for e in errors)
    with pytest.raises(ValueError,match='расходится с каталогом'):
        build_metering_spec_section(p)


def test_api_exact_filters_pagination_conflicts_and_no_origin_shortcut():
    app=FastAPI();app.include_router(router);client=TestClient(app)
    r=client.get('/meters/engineering-catalogue?kind=pipe&material=ppr&outer_diameter_mm=63&limit=1').json()
    assert r['matched']==2 and len(r['items'])==1 and not r['installation_approved']
    assert client.get('/meters/engineering-catalogue?kind=pipe&material=ppr&dn=63').json()['matched']==0
    assert client.get('/meters/engineering-catalogue/not-there').status_code==404
    assert client.get('/meters/engineering-catalogue/proaqua-ppr-sdr11-white-pa11028/pipe-section?joining=socket_fusion').status_code==422
    assert client.get('/meters/engineering-catalogue?limit=999').status_code==422


def test_pipe_candidates_are_explicit_same_system_same_port_not_a_dn_guess():
    c=get_engineering_catalogue()
    rows=c.pipe_connection_candidates(PPR,joining='socket_fusion')
    ids={r['id'] for r in rows}
    assert 'proaqua-pa22524p' in ids
    assert 'proaqua-pa140-white-pa14018p' in ids
    assert 'valtec-vtp761-06309' not in ids
    assert not c.pipe_connection_candidates(PE11,joining='electrofusion')
    assert not c.pipe_connection_candidates('stami-ew-10704-s3p5-od76-s3p5',joining='welded')
    assert not c.pipe_connection_candidates('gost3262-ordinary-steel-dn50',joining='threaded')
    assert all(not r['installation_approved'] for r in rows)
    for row in rows:
        for q in c.items[row['id']].ports:
            if q.name in row['matching_ports']:
                assert q.outer_diameter_mm==63 and q.system_id=='proaqua_ppr'


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(schema_version=99),
    lambda r: r['units'].update(dimensions='cm'),
    lambda r: r['families'].append(deepcopy(r['families'][0])),
    lambda r: r['families'][0]['rows'].append(list(r['families'][0]['rows'][0])),
    lambda r: r['families'][0]['rows'][0].pop(),
    lambda r: r['families'][0]['rows'][0].__setitem__(1,100),
    lambda r: r['families'][0].update(source_ids=['unknown']),
    lambda r: r['families'][3]['rows'][-1].__setitem__(3,'verified'),
])
def test_malformed_catalogue_is_rejected(mutate):
    raw=json.loads(_DATA.read_text());mutate(raw)
    with pytest.raises(ValueError):
        load_families(raw,get_metering_catalogue().sources)


def test_sqlite_is_complete_indexed_and_does_not_clobber(tmp_path):
    path=tmp_path/'catalogue.sqlite'
    summary=export_sqlite(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT count(*) FROM items').fetchone()[0]==summary['total']
        assert db.execute('PRAGMA user_version').fetchone()==(1,)
        payload=json.loads(db.execute('SELECT payload FROM items WHERE id=?',(PPR,)).fetchone()[0])
        assert payload==get_engineering_catalogue().card(PPR)
        assert db.execute('SELECT dn FROM ports WHERE item_id=?',(PPR,)).fetchone()==(None,)
    before=path.read_bytes()
    with pytest.raises(FileExistsError):
        export_sqlite(path)
    assert path.read_bytes()==before
    assert export_sqlite(path,replace=True)['total']==summary['total']
