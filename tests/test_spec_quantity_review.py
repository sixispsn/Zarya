from copy import deepcopy
from dataclasses import asdict

import pytest

from app.pz.spec import SpecRow, SpecSection, Specification, build_water_specification
from app.pz.spec_quantity_review import review_spec_quantities, water_spec_quantity_review
from app.intake.studio_intake import build_handoff_request
from app.intake.project_builder import build_project
from tests.test_studio_apartment_meters import draft
from tests.test_apartment_accessories import samara
from tests.test_studio import client, new, answer


def test_current_samara_rows_are_not_a_frozen_count_or_approval(samara):
    before = deepcopy(asdict(samara))
    report = water_spec_quantity_review(samara)
    # Existing no-pump sample: one previously omitted branch isolation is
    # now owned by the station sheet. Unknown branch geometry stays unknown.
    assert report['counts'] == dict(positions=144, assigned=88, estimated=8,
                                    missing=56, invalid=0, requirements=0)
    assert sum(g['count'] for g in report['groups']) == 56
    assert len(report['groups']) == 5
    assert next(g for g in report['groups'] if g['title'].startswith('ВУ-Г.'))['count'] == 7
    assert report['actions'][:2] == [dict(id='risers', title='Указать известное число стояков',
        fields=['risers_v1','risers_t3','risers_t4'],
        note='В1, Т3 и Т4 задаются отдельно. Это заполнит количество арматуры, не метраж труб.'),
        dict(id='sectional_valves', title='Уточнить секционные краны В1',
        fields=['v1_sectional_valves_count', 'v1_sectional_valves_basis'],
        note='Необязательно для расчёта и принципиальной схемы. Количество и основание по компоновке, без повторного учёта арматуры узлов.')]
    assert [a['id'] for a in report['actions'][2:]] == ['service_nodes', 'balancing']
    assert 'не подбор оборудования' in report['notice']
    assert not any(k in report for k in ('can_release','ready','can_purchase'))
    assert asdict(samara) == before
    actual = build_water_specification(samara)
    assert [(g['title'], [i['name'] for i in g['items']]) for g in report['groups']] == [
        (s.title, [r.name for r in s.rows if r.qty is None and r.unit])
        for s in actual.sections if any(r.qty is None and r.unit for r in s.rows)]


def test_riser_input_closes_three_counts_not_unselected_balancing_or_pipe_metres():
    p=build_project(build_handoff_request(draft()))
    initial=water_spec_quantity_review(p)
    p.building.risers_v1, p.building.risers_t3, p.building.risers_t4 = 12, 10, 5
    updated=water_spec_quantity_review(p)
    assert initial['counts']['missing'] - updated['counts']['missing'] == 3
    assert any(a['id']=='balancing' for a in updated['actions'])
    assert not any(a['id']=='risers' for a in updated['actions'])
    assert any(item['unit']=='м' for g in updated['groups'] for item in g['items'])


def test_requirements_zero_estimates_and_duplicate_position_numbers():
    spec=Specification(sections=[SpecSection('В1', rows=[
        SpecRow(1,'Нулевое заданное количество',unit='шт.',qty=0),
        SpecRow(2,'Оценка',unit='м',qty=3.5,quantity_basis='area_estimate'),
        SpecRow(3,'Пожелание диспетчеризации',unit='',qty=None),
        SpecRow(4,'Неизвестное',unit='шт.',qty=None),
    ]), SpecSection('ВУ',rows=[SpecRow(1,'Неизвестный ВУ',diagram_pos='П1',unit='м',qty=None)])])
    before=deepcopy(asdict(spec))
    r=review_spec_quantities(spec)
    assert r['counts']==dict(positions=4,assigned=2,estimated=1,missing=2,invalid=0,requirements=1)
    assert r['groups'][1]['items'][0]['position']=='П1'
    assert asdict(spec)==before


@pytest.mark.parametrize('value',[True,-1,1.1,'2',float('nan'),float('inf')])
def test_bad_piece_quantities_not_counted_as_filled(value):
    r=review_spec_quantities(Specification(sections=[SpecSection('В1',rows=[
        SpecRow(1,'Деталь',unit='шт.',qty=value)])]))
    assert r['counts']['invalid']==1 and r['counts']['assigned']==0
    assert r['groups'][0]['items'][0]['state']=='invalid'


def test_unavailable_report_not_empty_success(samara,monkeypatch):
    from app.pz import spec_quantity_review as module
    def bad(p): raise ValueError('Недостаточно данных спецификации')
    monkeypatch.setattr(module,'build_water_specification',bad)
    r=water_spec_quantity_review(samara)
    assert r['state']=='unavailable' and 'counts' not in r


def test_ordinary_http_persists_review_and_revokes_it_on_edits(client):
    state=new(client)
    answers={k:r['value'] for k,r in draft(risers_v1=12,risers_t3=10,risers_t4=5)['answers'].items()}
    response=client.post('/studio/api/calculate',json={'revision':state['revision'],'answers':answers})
    assert response.status_code==200,response.text
    state=response.json()
    result=state['project_calculation']
    assert result['can_preview'] and not result['can_release']
    review=result['spec_quantity_review']
    assert review['counts']['missing']>0
    assert not any(a['id']=='risers' for a in review['actions'])
    assert client.get('/studio/api/draft').json()['project_calculation']['spec_quantity_review']==review
    state=answer(client,state,'risers_t4',None)
    assert state['project_calculation'] is None and state['preview'] is None
    html=client.get('/studio').text
    assert '/static/studio_spec_review.js?v=4-service-assemblies' in html


def test_samara_http_uses_same_review_and_remains_read_only(client):
    state=new(client)
    response=client.post('/studio/api/study',json={'revision':state['revision'],'kind':'samara'})
    assert response.status_code==200,response.text
    state=response.json()
    assert state['project_calculation']['spec_quantity_review']['counts']['missing']==56
    assert state['project_calculation']['can_preview'] and not state['project_calculation']['can_release']
    response=client.patch('/studio/api/answer',json={'revision':state['revision'],'field':'risers_v1','value':12})
    assert response.status_code==422
