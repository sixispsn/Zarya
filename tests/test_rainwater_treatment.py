"""Treatment is an optional bounded extension; no invented quality or losses."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.calc.rainwater_reuse import from_dict, assess
from app.calc.rainwater_treatment import assess_treatment, project_context
from app.calc.rainwater_pump import assess_pump
from app.data.rainwater_treatment import CATALOG, PACK_ID
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.intake.studio_intake import validate_value, IntakeError
from app.pz.project import BuildingPurpose
from app.pz.generator import generate_rainwater_reuse_html, generate_pz_html, generate_wastewater_pz_html
from app.pz.rainwater_reuse import specification_rows, functional_svg
from app.pz.commission import build_commission_report
from scripts.preview_rainwater_reuse import example_project
from tests import test_studio as studio

client = studio.client
CTX = dict(building_kind="residential", roof_kind="flat_accessible")


def example():
    p = example_project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    p.sewage.roof_kind = "flat_accessible"
    p.rainwater_reuse = replace(p.rainwater_reuse,
        treatment_setup=PACK_ID, treatment_surface="hard_terrace",
        treatment_selection_flow_lps=.4, treatment_filter_loss_m=1.8, treatment_uv_loss_m=.2,
        treatment_selection_source="Синтетические данные регрессионного теста, не реальный лист подбора.",
        treatment_quality_basis="Условие теста: пригодность обоих изделий подтверждена. Не анализ воды объекта.",
        pump_treatment_loss_m=99)
    return p


def test_loss_sum_once_and_legacy_aggregate_ignored_without_mutation():
    p = example(); d = p.rainwater_reuse; before = deepcopy(asdict(p))
    r = assess(d, **project_context(p))
    assert r['treatment']['head_loss_m'] == 2
    assert not r['treatment']['quality_verified']
    assert r['pump']['duty']['h_m'] == 30
    assert r['pump']['selected']['id'] == 'vodomet-55-50-a'
    assert asdict(p) == before
    assert all(c['head_loss_m'] is None for c in CATALOG)


@pytest.mark.parametrize('field', ['treatment_filter_loss_m','treatment_uv_loss_m',
    'treatment_selection_flow_lps','treatment_selection_source','treatment_quality_basis'])
def test_missing_or_stale_does_not_fall_back_to_aggregate(field):
    d = example().rainwater_reuse
    d = replace(d, **{field: '' if isinstance(getattr(d,field),str) else None})
    r = assess(d, **CTX)
    assert r['treatment']['head_loss_m'] is None
    assert r['pump']['selected'] is None and r['pump']['duty'] is None


def test_flow_change_invalidates_selection_but_small_flow_not_fake_uv_minimum():
    d = example().rainwater_reuse
    assert assess(replace(d,pump_flow_lps=.3), **CTX)['pump']['selected'] is None
    d = replace(d,pump_flow_lps=.05,treatment_selection_flow_lps=.05)
    assert assess_treatment(d, **CTX)['ready_for_pump']  # not a made-up 0.4 m³/h minimum
    for q in (.667, 1.0):
        assert assess_treatment(replace(d,pump_flow_lps=q,treatment_selection_flow_lps=q), **CTX)['status'] == 'no_match'


@pytest.mark.parametrize('context', [dict(building_kind='public',roof_kind='flat_accessible'),
    dict(building_kind='residential',roof_kind='flat_non_accessible'),
    dict(building_kind='residential',roof_kind='gable'),
    dict(building_kind=None,roof_kind=None)])
def test_no_inferred_roof_or_building(context):
    r = assess(example().rainwater_reuse, **context)
    assert not r['treatment']['candidates'] and not r['pump']['selected']


@pytest.mark.parametrize('patch', [{'treatment_surface':'other'}, {'purpose':'toilets'},
    {'treatment_surface':''}, {'pump_temperature_c':2}])
def test_scope_and_temperature_reject(patch):
    r = assess(replace(example().rainwater_reuse,**patch), **CTX)
    assert not r['treatment']['ready_for_pump'] and not r['pump']['selected']


def test_large_pump_is_rejected_for_filter_pressure_even_when_hose_sufficient():
    p = example(); p.rainwater_reuse.pump_terminal_head_m = 35
    r = assess(p.rainwater_reuse, **CTX)
    assert r['pump']['status']=='no_match'
    assert any('давление' in s for c in r['pump']['candidates'] for s in c['reasons'])
    assert all(row.qty is None for row in specification_rows(p) if row.type_mark in [c['model'] for c in CATALOG])


@pytest.mark.parametrize('key,value', [('treatment_setup',[]),('treatment_surface',{}),
    ('treatment_filter_loss_m',True),('treatment_uv_loss_m',-1),
    ('treatment_selection_flow_lps',0),('treatment_filter_loss_m',float('inf')),
    ('treatment_quality_basis',None)])
def test_validation(key,value):
    with pytest.raises(ValueError): from_dict({key:value})


def test_studio_numeric_validation_and_roundtrip():
    assert validate_value('rainwater_treatment_filter_loss_m','0') == 0
    with pytest.raises(IntakeError): validate_value('rainwater_treatment_selection_flow_lps','0')
    with pytest.raises(IntakeError): validate_value('rainwater_treatment_filter_loss_m','-1')
    req = IOS2Request(DocumentRequest('','',''),'residential',2,6.6,
        fire_height_m=4.8, wastewater_roof_kind='flat_accessible',rainwater_reuse=example().rainwater_reuse)
    restored = load_request(dump_request(req))
    assert restored.rainwater_reuse == req.rainwater_reuse
    p=build_project(restored)
    assert assess(p.rainwater_reuse,**project_context(p))['pump']['duty']['h_m']==30


def test_spec_templates_scope_quality_and_no_duplicate_supplied_parts():
    p=example(); before=deepcopy(asdict(p)); rows=specification_rows(p)
    assert sum(r.code=='32034' for r in rows)==1
    assert sum(r.type_mark=='ЛЕНА DUV-1-48-N MST' for r in rows)==1
    assert not any(r.name.startswith(('Картридж','УФ-датчик','Блок химической','Пробоотборник')) for r in rows)
    assert any('Отстойная' in r.name for r in rows)
    assert 'Первый загрязнённый сток' in functional_svg(p)
    for renderer in (generate_rainwater_reuse_html,generate_pz_html,generate_wastewater_pz_html):
        html=renderer(p)
        assert 'DUV-1-48-N MST' in html and 'качества' in html
    assert asdict(p)['rainwater_reuse']==before['rainwater_reuse']
    assert next(c for c in build_commission_report(p).checks if c.code=='RAIN-01').blocking
    p.rainwater_reuse.treatment_quality_basis='<script>alert(1)</script>'
    assert '<script>' not in generate_rainwater_reuse_html(p)
    assert '&lt;script&gt;' in generate_rainwater_reuse_html(p)
    p.rainwater_reuse.enabled=False
    assert not specification_rows(p) and 'DUV-1-48-N MST' not in generate_pz_html(p)


def test_real_studio_reselection_roof_change_and_no_flow_changes(client):
    s=studio.residential_project(client)
    original=client.post('/studio/api/calculate',json={'revision':s['revision']}).json()
    answers={'rainwater_'+k:v for k,v in asdict(example().rainwater_reuse).items() if k not in {'enabled','design_review'}}
    answers.update(rainwater_enabled='yes',roof_type='flat_accessible')
    response=client.post('/studio/api/calculate',json={'revision':original['revision'],'answers':answers})
    assert response.status_code==200,response.text
    s=response.json()
    assert s['rainwater_reuse']['pump']['duty']['h_m']==30
    assert s['calculation']==original['calculation']
    assert s['project_calculation']['flows']==original['project_calculation']['flows']
    s=studio.answer(client,s,'roof_type','gable')
    assert s['rainwater_reuse']['treatment']['status']=='out_of_scope'
    assert not s['rainwater_reuse']['pump']['selected']
    s=studio.answer(client,s,'rainwater_treatment_setup',None)
    assert s['rainwater_reuse']['treatment']['status']=='not_configured'
