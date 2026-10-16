"""Schema 3 is an explicit boundary, never a silent retrofit of old inputs."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.intake.studio_fire_pipework import BOUNDARY, ROLES, from_model
from app.intake.studio_fire_station import parse_model
from tests.test_fire_review_binding import passing_model, bundle
from tests.test_studio_fire_review import evaluate, station_draft


def pipework_model():
    """Synthetic adapter fixture; NO product selection or default for a building."""
    m = passing_model()
    m['schema_version'] = 3
    m['basis'] = 'Отдельный контроль адаптера. Вводы и сеть не содержат обвязки. Не реальные исходные здания.'
    m['pressure_review']['loss_boundary'] = BOUNDARY
    rows = []
    for role, (side, count, method, name) in ROLES.items():
        row = dict(role=role, dn=100, basis='Явное условное сопротивление теста, не паспорт')
        if method == 'A_L': row.update(value=.0023, length_m=.8 if count==1 else .4)
        elif method == 'Kv': row.update(value=180. if role.endswith('check') else 250.)
        else: row.update(value=.5)
        rows.append(row)
    m['pipework'] = dict(material='steel_vgp_ordinary', elements=rows,
        basis='Явная синтетическая геометрия для интеграционного теста. Один активный путь, резерв закрыт.',
        connections=[dict(kind=kind, at=side+'_header', dn=15 if kind!='test' else 50,
            destination='В атмосферу' if kind=='air' else 'Приёмник с разрывом струи',
            basis='Условное подключение теста; трасса и режим требуют увязки')
            for side in ('suction','discharge') for kind in ('air','drain','test')
            if kind!='test' or side=='discharge'])
    return m


@pytest.mark.parametrize('mutate', [
    lambda m: m['pressure_review'].update(loss_boundary='all_pipework_explicit_in_supplies_and_network'),
    lambda m: m.update(schema_version=2),
    lambda m: m.pop('pipework'),
    lambda m: m['pipework'].update(material='plastic'),
    lambda m: m['pipework']['elements'].pop(),
    lambda m: m['pipework']['elements'][0].update(role='suction_branch'),
    lambda m: m['pipework']['elements'][0].update(value=0),
    lambda m: m['pipework']['elements'][0].update(value=True),
    lambda m: m['pipework']['elements'][0].update(length_m=-1),
    lambda m: m['pipework']['elements'][2].update(dn=80),
    lambda m: m['pipework']['elements'][2].update(basis=''),
    lambda m: m['pipework']['elements'][2].update(value=1e-300),
    lambda m: m['pipework']['elements'][0].update(value=1e308,length_m=1e308),
    lambda m: m['pipework']['connections'][0].update(kind=[]),
    lambda m: m['pipework']['connections'][0].update(at={}),
    lambda m: m['pipework']['connections'][0].update(kind='test'),
    lambda m: m['pipework']['connections'][0].update(dn=150),
    lambda m: m['pipework']['connections'][0].update(destination=''),
    lambda m: m['pipework']['connections'].__setitem__(1, m['pipework']['connections'][0]),
])
def test_ambiguous_or_invalid_pipework_rejected(mutate):
    m=pipework_model(); mutate(m)
    with pytest.raises(ValueError): parse_model(m)


def test_fixed_flow_boundary_adds_each_side_once_not_installed_reserve():
    from app.calc.fire_pump_station import calculate_common_fire_station
    parsed=parse_model(pipework_model())
    before=deepcopy(parsed)
    pw=from_model(parsed.model)
    from app.intake.project_builder import build_project
    from app.intake.studio_intake import build_handoff_request
    from app.pz.geometry_builder import build_network
    network=build_network(build_project(build_handoff_request(station_draft(parsed.model))))
    original=calculate_common_fire_station(network, parsed.station, 2)
    explicit=calculate_common_fire_station(network, parsed.station, 2, pipework=pw)
    audit=explicit.pipework_audit
    assert audit['reserve_in_flow_sum'] is False
    assert all(e['quantity_on_active_path']==1 for e in audit['elements'])
    assert explicit.minimum_suction_head_m == pytest.approx(original.minimum_suction_head_m-audit['losses_m']['suction'])
    assert explicit.hydraulic.pump_duty.required_head_m == pytest.approx(original.hydraulic.pump_duty.required_head_m+audit['total_loss_m'])
    assert explicit.hydraulic.required_head_at_source_m == pytest.approx(original.hydraulic.required_head_at_source_m)
    assert explicit.maximum_static_suction_head_m == original.maximum_static_suction_head_m
    assert parsed == before


def test_l06_parity_with_approved_pipework_solver_and_yaml():
    from app.calc.fire_repair_flow import check_repair_operating_point
    from app.calc.fire_pressure_flow import handbook_characteristic
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    m=pipework_model(); before=deepcopy(m)
    request=build_handoff_request(station_draft(m))
    assert load_request(dump_request(request)) == request
    p,net,out=evaluate(m)
    r=from_model(m).resistances(); boundary=out['boundaries'][0]
    chars=[handbook_characteristic(c,hose_material='rubber_lined',nozzle_kind='non_shutoff') for c in net.cabinets]
    direct=check_repair_operating_point(net,chars,out['pump']['curve'],
        closed_port_ids=[net.source.node_id],suction_static_head_m=boundary['static_head_m'],
        supply_resistance=boundary['resistance'],apertures_mm={net.cabinets[0].cabinet_id:21.},
        station_suction_resistance=r['suction'],station_discharge_resistance=r['discharge'])
    row=next(r for r in out['rows'] if r['case']=='port-1' and r['boundary']==boundary['id'] and r['axis_offset_px']==0)
    assert row['result']==asdict(direct)
    assert out['minimum_pass_count']==out['scenario_count']==45
    assert out['reserve_in_flow_sum'] is False and not out['release_ready']
    _,_,old=evaluate(passing_model())
    assert out['static_rows']==old['static_rows']  # zero-flow resistance is not static protection
    assert out['rows']!=old['rows']
    m['pipework']['connections']=[]
    _,_,without_aux=evaluate(m)
    assert without_aux['rows']==out['rows']  # test and drain modes are not falsely simulated
    assert before['pipework']['elements']==m['pipework']['elements']


@pytest.fixture(scope='module')
def accepted(tmp_path_factory):
    return bundle(pipework_model(),tmp_path_factory.mktemp('explicit-pipework')).project


def test_binding_spec_and_graph_share_sizes_and_auxiliary_positions(accepted):
    from app.pz.fire_review_binding import validate_binding,spec_rows,station_requirement_rows
    from app.pz.fire_principle_scheme import build_station_sheet
    from tests.test_fire_principle_scheme import elements
    p=deepcopy(accepted)
    r=validate_binding(p)
    assert r['pipework']==from_model(p.fire_station_model_input).audit(p.fire_pumps.wp_q)
    ids={e.attrib['data-component'] for e in elements(build_station_sheet(p),'data-component')}
    for row in station_requirement_rows(p.fire_station_model_input):
        assert row in spec_rows(p)
        if row['unit'] in ('шт.','компл.'):
            assert type(row['qty']) is int
            assert set(row['id'].split('/'))<=ids
    pipes={r['id']:r for r in spec_rows(p) if r['unit']=='м'}
    assert len(pipes)==4 and sum(r['qty'] for r in pipes.values())==pytest.approx(3.2)
    p.fire_station_model_input['pipework']['elements'][0]['length_m']+=1
    with pytest.raises(ValueError): validate_binding(p)


def test_reducers_exist_only_for_explicit_different_bores():
    from app.pz.fire_review_binding import station_requirement_rows
    m=pipework_model()
    assert not any(r['id'].startswith(('ПС','ПН')) for r in station_requirement_rows(m))
    for row in m['pipework']['elements']:
        if row['role'].endswith('header'): row['dn']=150
    reducers=[r for r in station_requirement_rows(m) if r['id'].startswith(('ПС','ПН'))]
    assert len(reducers)==2 and all(r['qty']==2 and r['mark']=='DN150×100' for r in reducers)


def test_drawn_reducers_match_spec_and_no_implicit_auxiliaries(tmp_path):
    from app.pz.fire_principle_scheme import build_station_sheet
    from tests.test_fire_principle_scheme import elements
    from app.pz.fire_review_binding import spec_rows
    m=pipework_model(); m['pipework']['connections']=[]
    for row in m['pipework']['elements']:
        if row['role'].endswith('header'): row['dn']=150
    p=bundle(m,tmp_path).project
    svg=build_station_sheet(p)
    ids={e.attrib['data-component'] for e in elements(svg,'data-component')}
    assert {'ПС1','ПС2','ПН1','ПН2'}<=ids
    assert not elements(svg,'data-auxiliary')
    assert not any(r['id'].startswith(('ВО','СК','ИО')) for r in spec_rows(p))
    assert 'M304,78 l-3,-1.2' in svg  # flow arrow is clear of the reducer at 311
    # At suction the large header is left; at discharge it is right.
    reducers={e.attrib['data-component']:e for e in elements(svg,'data-component') if e.attrib['data-component'].startswith(('ПС','ПН'))}
    assert next(iter(reducers['ПС1'])).attrib['d'].startswith('M118,76 V80 L124,78')
    assert next(iter(reducers['ПН1'])).attrib['d'].startswith('M314,76 V80 L308,78')


def test_v3_pdf_pages_bookmarks_text_collisions(accepted,tmp_path):
    from app.pz.fire_review_scheme import generate_review_scheme
    from pypdf import PdfReader
    import pymupdf
    from itertools import combinations
    path=generate_review_scheme(tmp_path/'v3.pdf',accepted)
    pdf=PdfReader(path)
    assert len(pdf.pages)==len(pdf.outline)==5
    assert [pdf.get_destination_page_number(b) for b in pdf.outline]==list(range(5))
    text=' '.join(p.extract_text() for p in pdf.pages)
    assert 'Обвязка и вспомогательные подключения' in text
    assert all(label in text for label in ('ВО1','ВО2','СК1','СК2','ИО2','DN100'))
    with pymupdf.open(path) as doc:
        for page in doc:
            spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans']]
            for a,b in combinations(spans,2):
                overlap=pymupdf.Rect(a['bbox']) & pymupdf.Rect(b['bbox'])
                assert overlap.width<=1 or overlap.height<=1,(page.number,a['text'],b['text'])


def test_pipework_does_not_close_architecture_and_product_gates(accepted):
    from app.pz.commission import build_commission_report
    report=build_commission_report(accepted,artifacts={'Схема насосов, зон и ГВС':True})
    rows={r['rule_id']:r for a in report.normative_audits for r in a['rows']}
    assert rows['V-GOST-A05']['status']=='missing'
    assert 'DN и заданные вспомогательные подключения' in rows['V-GOST-A05']['evidence']
    assert rows['V-GOST-A05']['blocks_release']
