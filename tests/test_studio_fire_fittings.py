"""A coverage declaration is not a new hydraulic allowance or a passport."""
from copy import deepcopy

import pytest

from app.intake.studio_fire_fittings import coverage
from app.intake.studio_fire_station import parse_model
from app.intake.studio_fire_pipework import from_model
from tests.test_studio_fire_location import located_model
from tests.test_fire_review_binding import bundle
from tests.test_studio_fire_review import evaluate, station_draft


def scoped_model():
    m = located_model()
    m['pipework']['fittings_scope'] = dict(
        pump_model='CNP CDM32-3', nozzle_dn=65,
        suction_header_dn=100, suction_branch_dn=100,
        discharge_header_dn=100, discharge_branch_dn=100,
        basis='Для контрольного примера стадии П принято: суммарный ζ каждой ветви включает '
              'переходы к коллектору и патрубку. ζ отнесён к скорости в трубе ветви DN100, '
              'а не к скорости в патрубке DN65. Не паспорт и не универсальное значение для других объектов.')
    return m


@pytest.mark.parametrize('mutate', [
    lambda s:s.update(nozzle_dn=100),
    lambda s:s.update(nozzle_dn=True),
    lambda s:s.update(pump_model='Unknown pump'),
    lambda s:s.update(pump_model=[]),
    lambda s:s.update(suction_branch_dn=65),
    lambda s:s.update(discharge_header_dn=150),
    lambda s:s.update(basis=' '),
    lambda s:s.update(basis=3),
    lambda s:s.update(extra_loss_m=0),
    lambda s:s.pop('pump_model'),
])
def test_inconsistent_or_implicit_coverage_is_rejected(mutate):
    m = scoped_model(); mutate(m['pipework']['fittings_scope'])
    with pytest.raises(ValueError): parse_model(m)


def test_changed_pump_rejects_old_coverage():
    m = scoped_model(); m['pressure_review']['pump_id'] = 'cnp-cdm20-4'
    with pytest.raises(ValueError, match='модель насоса'): parse_model(m)


def test_old_models_and_same_hydraulic_budget_are_not_rewritten():
    original, m = located_model(), scoped_model()
    before = deepcopy(m)
    assert not coverage(original)['included']
    assert coverage(m)['included']
    assert from_model(m) == from_model(original)
    for q in (0, 12, 20.810, 30):
        assert from_model(m).audit(q) == from_model(original).audit(q)
    _,_,new = evaluate(m)
    _,_,old = evaluate(original)
    for field in ('rows','static_rows','scenario_count','minimum_pass_count','pipework'):
        assert new[field] == old[field]
    assert new['input_sha256'] != old['input_sha256']
    assert m == before
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    req = build_handoff_request(station_draft(m))
    assert load_request(dump_request(req)).fire_station_model == m


def test_same_coverage_in_pz_scheme_calculation_and_spec(tmp_path):
    from app.pz.generator import generate_pz_html, generate_pump_selection_html
    from app.pz.fire_principle_scheme import build_station_sheet, build_pipework_sheet
    from app.pz.fire_review_binding import spec_rows, validate_binding
    from app.pz.fire_station_input_report import render_station_input_report
    from app.pz.commission import build_commission_report
    from pypdf import PdfReader
    b = bundle(scoped_model(),tmp_path)
    p = b.project
    for html in (generate_pz_html(p), generate_pump_selection_html(p)):
        assert 'Переходы коллектора и патрубков входят' in html
        assert 'DN100' in html and 'DN65' in html and '0,500' in html
    pz_html = generate_pz_html(p)
    assert 'Качество воды на хозяйственно-питьевые нужды должно соответствовать' in pz_html
    assert 'Качество воды на хозяйственно-питьевые нужды соответствует' not in pz_html
    assert 'потери в суммарном zeta ветви' in build_station_sheet(p)
    assert 'dвн=105 мм' in build_pipework_sheet(p, page=2, total=5)
    rows = [r for r in spec_rows(p) if r['id'].startswith(('ПВ','ПД'))]
    assert sum(r['qty'] for r in rows) == 4
    assert all('без повторной надбавки' in r['note'] for r in rows)
    path = render_station_input_report(tmp_path/'calc.pdf',p,b.fire_station_result)
    text = ' '.join(page.extract_text() for page in PdfReader(path).pages)
    assert 'Переходы коллектора и патрубков входят' in text
    assert 'при dвн=105 мм' in text
    audits = build_commission_report(p).normative_audits
    gate = next(r for a in audits for r in a['rows'] if r['rule_id']=='V-GOST-A05')
    assert gate['blocks_release'] and gate['status']=='missing'
    p.fire_station_model_input['pipework']['fittings_scope']['basis'] += ' Изменено.'
    with pytest.raises(ValueError): validate_binding(p)


def test_header_reducer_is_not_claimed_covered_without_declaration():
    from app.pz.fire_review_binding import station_requirement_rows
    m=located_model()
    for r in m['pipework']['elements']:
        if r['role'].endswith('header'): r['dn']=150
    rows = [r for r in station_requirement_rows(m) if r['id'].startswith(('ПС','ПН'))]
    assert len(rows)==2 and all('требует увязки' in r['note'] for r in rows)
