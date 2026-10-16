"""Synthetic document references, never project evidence, through ordinary HTTP."""
from io import BytesIO
import json
from pypdf import PdfReader


ANSWERS = dict(project_assignment_ref="ТЕСТ-ПЗ, раздел 1, приложение А",
    project_survey_ref="ТЕСТ-ИИ, том 1, ревизия 2",
    project_service_life_years=100, project_overhaul_period_years=30,
    water_source_description="Тестовая существующая водопроводная сеть",
    water_connection_point="ВК-7, точка врезки по учебным ТУ",
    water_tu_org="Учебный водоканал В1", water_tu_number="УЧ-В-001",
    water_tu_date="01.10.2026", wastewater_disposal_mode="centralized",
    wastewater_tu_org="Учебный водоканал К1", wastewater_tu_number="УЧ-К-002",
    wastewater_tu_date="02.10.2026")


def verify(call, other, state, baseline, out):
    out = out / 'design-basis'; out.mkdir(exist_ok=True)
    state = call('POST', '/studio/api/calculate', json={'revision': state['revision'],
        'answers': dict(ANSWERS, storm_selected_riser_dn_mm=100)}).json()
    calc = state['project_calculation']
    assert state['design_basis']['filled'] == state['design_basis']['total'] == 7
    for key in ('flows', 'meters', 'head', 'pumps', 'storm', 'fire_station'):
        assert calc[key] == baseline[key], key
    findings = {f['code']: f for g in calc['quality']['gates'] for f in g['findings']}
    closed = ('V-GOST-01', 'V-GOST-02', 'K-GOST-01', 'K-GOST-02', 'K-GOST-03')
    assert all(findings[code]['state'] == 'ready' for code in closed)
    assert findings['K-GOST-04']['state'] == 'blocked'
    assert not calc['can_release'] and not calc['sewer_scheme']['ready']
    assert call('GET', '/studio/api/draft').json()['design_basis'] == state['design_basis']
    state = call('POST', '/studio/api/preview', json={'revision': state['revision']}).json()
    pages = {}; urls = []
    for kind, present, absent in (('water_package_pdf', 'УЧ-В-001', 'УЧ-К-002'),
                                  ('wastewater_package_pdf', 'УЧ-К-002', 'УЧ-В-001')):
        d = next(d for d in state['preview']['documents'] if d['kind'] == kind)
        url = f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}'
        data = call('GET', url).content; urls.append(url)
        assert other.get(url).status_code == 404
        pdf = PdfReader(BytesIO(data)); text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        assert present in text and absent not in text
        for value in (ANSWERS['project_assignment_ref'], ANSWERS['project_survey_ref'], '100 лет', '30 лет'):
            assert value in text, (kind, value)
        (out / d['name']).write_bytes(data); pages[kind] = len(pdf.pages)
    (out / 'calculation.json').write_text(json.dumps(state['project_calculation'], ensure_ascii=False, indent=2))
    state = call('POST', '/studio/api/package', json={'revision': state['revision']}).json()
    assert state['package']['state'] == 'blocked'
    state = call('PATCH', '/studio/api/answer', json={'revision': state['revision'],
        'field': 'project_assignment_ref', 'value': None}).json()
    assert state['preview'] is None and state['package'] is None and state['project_calculation'] is None
    for url in urls:
        assert other.get(url).status_code == 404
    # Owner must also lose the old PDFs; use the underlying response status via a separate callback.
    return state, dict(pages=pages, closed=list(closed), calculations_unchanged=True,
                       independent_tu=True, release_still_blocked=True), urls
