"""Current preview files close presence checks, never engineering decisions."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft

client = studio_tests.client


def findings(calculation):
    return {row['code']: row for gate in calculation['quality']['gates']
            for row in gate['findings'] if row['source'] != 'quality_gates'}


def test_nonexistent_empty_or_directory_paths_are_not_generated_documents(tmp_path):
    from app.pz.ios2_orchestrator import IOS2DesignBundle, bundle_artifacts
    from tests.test_commission import _calculated_project
    from app.pz.commission import build_commission_report

    missing = tmp_path / 'missing.pdf'
    empty = tmp_path / 'empty.pdf'
    empty.touch()
    present = tmp_path / 'present.pdf'
    present.write_bytes(b'%PDF-test-presence-only')
    bundle = IOS2DesignBundle(project=_calculated_project(), pz_pdf=str(missing),
                              balance_pdf=str(empty), spec_pdf=str(tmp_path),
                              hydraulic_pdf=str(missing), fire_pressure_review_pdf=str(present))
    inventory = bundle_artifacts(bundle)
    assert not inventory['Пояснительная записка']
    assert not inventory['Баланс ВиВ']
    assert not inventory['Спецификация']
    assert inventory['Гидравлический расчёт В2']  # alternative existing report
    report = build_commission_report(bundle.project, artifacts=inventory)
    rows = {row['rule_id']: row for audit in report.normative_audits for row in audit['rows']}
    assert all(rows[c]['blocks_release'] for c in ('V-GOST-A01', 'V-GOST-A02', 'V-GOST-A03'))


def test_refresh_cannot_grant_release_or_mutate_calculations(monkeypatch):
    from app.intake import studio_project
    from app.pz.commission import CommissionReport

    monkeypatch.setattr(studio_project, 'preflight_request', lambda req: {'issues': []})
    original = {'can_release': False, 'flows': {'q_day_tot': 90}, 'head': {'ready': False}}
    before = deepcopy(original)
    result = studio_project.refresh_document_readiness(draft(), original, CommissionReport())
    assert not result['can_release']  # even an all-ready document report cannot grant release
    assert original == before and result['flows'] == original['flows']
    with pytest.raises(ValueError, match='отсутствует отчёт'):
        studio_project.refresh_document_readiness(draft(), original, None)


def test_new_missing_file_restricts_formerly_releasable_calculation(monkeypatch):
    from app.intake import studio_project
    from app.pz.commission import CommissionReport

    monkeypatch.setattr(studio_project, 'preflight_request', lambda req: {'issues': []})
    report = CommissionReport(normative_audits=[{'rows': [
        {'rule_id': 'V-GOST-A01', 'status': 'missing', 'blocks_release': True,
         'title': 'ПЗ', 'evidence': 'не сформирована'},
    ]}])
    result = studio_project.refresh_document_readiness(draft(), {'can_release': True}, report)
    assert not result['can_release']
    assert result['gost_blockers'][0]['rule_id'] == 'V-GOST-A01'
    assert findings(result)['V-GOST-A01']['state'] == 'blocked'


def test_preview_updates_file_checks_keeps_engineering_and_revokes_on_edit(client, tmp_path):
    state = studio_tests.new(client)
    data = draft(floor_height_m=3.3, basement_kind='basement', basement_floor_m=-3.1,
                 roof_type='flat_non_accessible', storm_city='moscow',
                 storm_roof_area_m2=252, section_drainage='internal')
    response = client.post('/studio/api/calculate', json={
        'revision': state['revision'],
        'answers': {key: row['value'] for key, row in data['answers'].items()},
    })
    assert response.status_code == 200, response.text
    state = response.json()
    before = state['project_calculation']
    codes = {'V-GOST-A01', 'V-GOST-A02', 'V-GOST-A03', 'V-GOST-A06',
             'K-GOST-A01', 'K-GOST-A02', 'K-GOST-A03'}
    assert all(findings(before)[code]['state'] == 'conditional' for code in codes)
    response = client.post('/studio/api/preview', json={'revision': state['revision']})
    assert response.status_code == 200, response.text
    state = response.json()
    after = state['project_calculation']
    ready_codes = codes - {'K-GOST-A03'}
    assert all(findings(after)[code]['state'] == 'ready' for code in ready_codes)
    assert findings(after)['K-GOST-A03']['state'] == 'blocked'
    assert findings(after)['DOC-03']['state'] == 'blocked'
    assert ready_codes.isdisjoint({row['code'] for section in after['review_sections']
                            for row in section['findings']})
    for code, row in findings(before).items():
        if row['state'] == 'blocked':
            assert findings(after)[code]['state'] == 'blocked', code
    assert findings(after)['V-GOST-A07']['state'] == 'blocked'  # absent manual plan
    assert not after['can_release'] and not after['sewer_scheme']['ready']
    assert after['gost_blockers']
    for key in ('flows', 'meters', 'head', 'pumps', 'storm', 'sewer_scheme'):
        assert after[key] == before[key], key
    reopened = client.get('/studio/api/draft').json()
    assert reopened['project_calculation'] == after
    for endpoint in ('calculate', 'package'):
        response = client.post('/studio/api/' + endpoint, json={'revision': state['revision']})
        assert response.status_code == 200, response.text
        state = response.json()
        assert all(findings(state['project_calculation'])[code]['state'] == 'ready' for code in ready_codes)
        assert findings(state['project_calculation'])['K-GOST-A03']['state'] == 'blocked'
        assert findings(state['project_calculation'])['DOC-03']['state'] == 'blocked'
        assert not state['project_calculation']['can_release']
    assert state['package']['state'] == 'blocked'
    scheme = next(d for d in state['preview']['documents'] if d['kind'] == 'wastewater_scheme_pdf')
    assert scheme['state'] != 'ready'
    assert client.get(f"/studio/api/preview/{state['preview']['id']}/files/{scheme['name']}").status_code == 200
    document = next(d for d in state['preview']['documents'] if d['kind'] == 'water_package_pdf')
    url = f"/studio/api/preview/{state['preview']['id']}/files/{document['name']}"
    assert client.get(url).status_code == 200
    with TestClient(studio_tests.app) as other:
        assert other.get(url).status_code == 404
    spec = next(d for d in state['preview']['documents'] if d['kind'] == 'spec_pdf')
    (tmp_path / 'studio' / state['project_id'] / 'previews' / state['preview']['id'] / spec['name']).unlink()
    state = client.post('/studio/api/calculate', json={'revision': state['revision']}).json()
    assert findings(state['project_calculation'])['V-GOST-A03']['state'] == 'blocked'
    assert findings(state['project_calculation'])['V-GOST-A01']['state'] == 'ready'
    state = studio_tests.answer(client, state, 'residents', 21)
    assert state['preview'] is None and state['project_calculation'] is None
    assert client.get(url).status_code == 404
    state = client.post('/studio/api/calculate', json={'revision': state['revision']}).json()
    assert all(findings(state['project_calculation'])[code]['state'] == 'conditional' for code in codes)
