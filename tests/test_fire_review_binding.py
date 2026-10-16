from copy import deepcopy
from io import BytesIO

import pytest

from app.intake.studio_intake import build_handoff_request
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from app.pz.fire_review_binding import validate_binding, spec_rows
from app.pz.fire_review_scheme import build_review_sheet
from tests.test_studio_fire_review import review_model, station_draft
from tests import test_studio as api_tests

client = api_tests.client


def passing_model():
    # A separate positive integration fixture. Never repair the negative fixture
    # by hiding its failing source or changing real project inputs.
    model = review_model()
    model['supplies'][1]['guaranteed_head_m'] = 30.
    model['basis'] = 'Положительный контроль интеграции: оба Hгар=30 м. Не исправление исходных реального проекта.'
    model['pressure_review']['document_use'] = 'preliminary_project'
    return model


def bundle(model, tmp_path):
    return design_ios2(build_project(build_handoff_request(station_draft(model))),
                       output_dir=str(tmp_path), render_documents=False)


def test_same_variant_in_pz_spec_and_scheme(tmp_path):
    from app.pz.generator import generate_pz_html, generate_pump_selection_html, generate_spec_html
    b = bundle(passing_model(), tmp_path)
    p, r = b.project, b.fire_pressure_review
    assert r['minimum_pass_count'] == r['scenario_count'] == 45
    assert r['adoption']['state'] == 'preliminary'
    assert validate_binding(p) == p.fire_pumps.pressure_review
    assert p.fire_pumps.model == 'CNP CDM32-3'
    assert not p.fire_pumps.top3 and p.fire_pumps.working_units == p.fire_pumps.reserve_units == 1
    assert not r['release_ready'] and not r['product_verified']
    html = [generate_pz_html(p), generate_pump_selection_html(p), generate_spec_html(p), build_review_sheet(p)]
    for doc in html:
        assert 'CNP CDM32-3' in doc and 'Hydro MX' not in doc
        assert 'Д1' in doc and '21' in doc
    assert 'не найдена' not in html[1].split('Подбор пожарной насосной установки В2')[-1]
    rows = spec_rows(p)
    assert rows[0]['qty'] == 2 and rows[0]['unit'] == 'шт.'
    assert len(rows) == 7 and rows[-1]['qty'] is None
    assert 'по зданию' in rows[-1]['note']
    assert rows[1]['id'] == 'ШУ-В2' and rows[1]['qty'] == 1
    assert 'data-fire-automation="true"' in html[0]
    assert 'Для резервного пожарного насоса не предусматривать автоматическую защиту' in html[0]
    assert 'Предварительная спецификация оборудования' in html[0]
    assert 'В составе данного раздела не разрабатывается (приводится в рабочей документации)' not in html[0]
    from xml.etree import ElementTree as ET
    root=ET.fromstring(html[-1])
    valve=float(next(e for e in root.iter() if 'data-fire-valve-x' in e.attrib).attrib['data-fire-valve-x'])
    hole=float(next(e for e in root.iter() if 'data-diaphragm-location-x' in e.attrib).attrib['data-diaphragm-location-x'])
    assert valve < hole  # after the valve, never on its supply side
    from app.pz.fire_review_scheme import build_network_sheet
    graph=ET.fromstring(build_network_sheet(p))
    edges=[(e.attrib['data-from'],e.attrib['data-to']) for e in graph.iter() if 'data-from' in e.attrib]
    assert edges == [(e['from_node'],e['to_node']) for e in p.fire_station_model_input['network']['runs']]


@pytest.mark.parametrize('change', ['head', 'aperture', 'group', 'nozzle', 'pump', 'result', 'reserve', 'power'])
def test_stale_or_modified_binding_is_rejected(tmp_path, change):
    p = bundle(passing_model(), tmp_path).project
    if change == 'head': p.fire_station_model_input['supplies'][0]['guaranteed_head_m'] = 31
    if change == 'aperture': p.fire_station_model_input['pressure_review']['apertures_mm']['СТ-В2-1'] = 22
    if change == 'group': p.fire_station_model_input['pressure_review']['groups'][0].reverse()
    if change == 'nozzle': p.fire.nozzle_mm = 16
    if change == 'pump': p.fire_pumps.model = 'Старый насос'
    if change == 'result': p.fire_pumps.pressure_review['schedule'][0]['aperture_mm'] = 25
    if change == 'reserve': p.fire_pumps.working_units = 2
    if change == 'power': p.fire_pumps.power_kw = 110
    with pytest.raises(ValueError): validate_binding(p)


@pytest.mark.parametrize('kind', ['deficit','unknown_max','high_max','disconnected'])
def test_bad_result_never_becomes_a_selected_variant(tmp_path, kind):
    m = review_model() if kind == 'deficit' else passing_model()
    m['pressure_review']['document_use'] = 'preliminary_project'
    if kind == 'unknown_max': m['supplies'][0]['maximum_head_m'] = None
    if kind == 'high_max': m['supplies'][0]['maximum_head_m'] = 100.
    if kind == 'disconnected':
        net=m['network']
        m['pressure_review']['repairs']=[dict(id='cut',basis='Контроль разрыва',closed_ports=[],
            closed_runs=[[r['from_node'],r['to_node']] for r in net['runs'][:2]])]
    b=bundle(m,tmp_path)
    assert b.fire_pressure_review['adoption']['state'] == 'rejected'
    assert not b.project.fire_pumps.model and not b.project.fire_pumps.pressure_review
    assert 'не принят' in b.project.fire_pumps.selection_note


def test_no_automatic_adoption_and_explicit_revoke(tmp_path):
    m = passing_model()
    for value in [None,'review_only']:
        if value is None: m['pressure_review'].pop('document_use')
        else: m['pressure_review']['document_use']=value
        b=bundle(m,tmp_path)
        assert not b.project.fire_pumps.pressure_review
        assert b.project.fire_pumps.curve_kind == 'duty_only'


def test_package_control_distinguishes_calculation_from_project_completeness(tmp_path):
    from app.pz.commission import build_commission_report
    from app.pz.fire_calculation_evidence import fire_calculation_evidence
    p = bundle(passing_model(), tmp_path).project
    assert p.fire.required_head_m is None  # never copy the obsolete fixed-Q head
    report = build_commission_report(p, artifacts={
        'Принципиальная схема': True, 'Схема насосов, зон и ГВС': True,
        'Пояснительная записка': True, 'Гидравлический расчёт В2': True,
    })
    checks = {r.code:r for r in report.checks}
    assert checks['FIRE-01'].status == 'specified' and not checks['FIRE-01'].blocking
    assert '45/45' in checks['FIRE-01'].result
    assert 'выполнить гидравлику' not in checks['FIRE-01'].action
    assert checks['FIRE-L06'].blocking and 'NPSH' in checks['FIRE-L06'].result
    rows = {r['rule_id']:r for audit in report.normative_audits for r in audit['rows']}
    assert rows['V-GOST-05']['status'] == 'specified'
    assert 'None' not in rows['V-GOST-05']['evidence']
    for code in ('V-GOST-A04', 'V-GOST-A05'):
        assert rows[code]['status'] == 'missing' and rows[code]['blocks_release']
    p.fire_station_model_input['supplies'][0]['guaranteed_head_m'] += 1
    assert fire_calculation_evidence(p)['status'] == 'fail'


def test_failed_adoption_does_not_pass_control_using_old_fixed_flow_head(tmp_path):
    from app.pz.fire_calculation_evidence import fire_calculation_evidence
    model = review_model()
    model['pressure_review']['document_use'] = 'preliminary_project'
    p = bundle(model, tmp_path).project
    assert fire_calculation_evidence(p)['status'] == 'fail'


def test_api_bound_outputs_and_revocation(client):
    from pypdf import PdfReader
    d=api_tests.new(client)
    values={k:v['value'] for k,v in station_draft(passing_model())['answers'].items()}
    response=client.post('/studio/api/calculate',json={'revision':d['revision'],'answers':values})
    assert response.status_code == 200, response.text
    s=response.json()
    assert s['project_calculation']['fire_station']['adopted']
    assert not s['project_calculation']['can_release']
    assert all('ПК' not in n and 'NPSH' not in n for n in s['project_calculation']['preview_notes'])
    issue = next(i for i in s['project_calculation']['issues'] if i['code'] == 'studio.fire_station_preliminary')
    assert 'фиксированным расходам' not in issue['message'] and 'L06' in issue['message']
    response=client.post('/studio/api/preview',json={'revision':s['revision']})
    assert response.status_code == 200, response.text
    s=response.json()
    row=next(x for x in s['preview']['documents'] if x['kind']=='fire_station_scheme_pdf')
    url=f'/studio/api/preview/{s["preview"]["id"]}/files/{row["name"]}'
    pdf=client.get(url)
    assert pdf.status_code == 200
    assert 'Диафрагма' in ' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    docs = {r['kind']:r for r in s['preview']['documents']}
    def text(kind):
        item = docs[kind]
        reply = client.get(f'/studio/api/preview/{s["preview"]["id"]}/files/{item["name"]}')
        assert reply.status_code == 200
        return ' '.join(p.extract_text() for p in PdfReader(BytesIO(reply.content)).pages)
    assert 'Для резервного пожарного насоса' in text('pz_pdf')
    sewer = text('wastewater_pz_pdf')
    assert 'NPSH' not in sewer and 'Принят единый предварительный вариант для заданных ПК' not in sewer
    m=passing_model(); m['pressure_review']['apertures_mm']['СТ-В2-1']=20.
    api_tests.answer(client,s,'fire_station_model',m)
    assert client.get(url).status_code==404
