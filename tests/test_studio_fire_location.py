"""Datums must not create room geometry, change hydraulics or certify a product."""
from copy import deepcopy
from itertools import combinations

import pytest

from app.intake.studio_fire_station import parse_model, summary
from app.intake.studio_fire_location import from_model
from app.data.fire_pump_geometry import reference, connection_review
from tests.test_studio_fire_pipework import pipework_model
from tests.test_fire_review_binding import bundle
from tests.test_studio_fire_review import evaluate, station_draft


def located_model():
    model = pipework_model()
    model['location'] = dict(room_number='Т-01', room_name='Пожарная насосная',
        floor_elevation_m=-3.25, suction_nozzle_elevation_m=model['pump_axis_m'],
        inlet_elevations_m={s['name']:-2.50 for s in model['supplies']},
        basis='Отдельная синтетическая привязка для контроля оформления, не данные АР реального объекта.')
    return model


@pytest.mark.parametrize('mutate', [
    lambda m:m.update(location=None),
    lambda m:m['location'].update(room_width_m=5),
    lambda m:m['location'].update(room_name=''),
    lambda m:m['location'].update(room_number='x'*21),
    lambda m:m['location'].update(basis='\n'),
    lambda m:m['location'].update(floor_elevation_m=True),
    lambda m:m['location'].update(floor_elevation_m=float('nan')),
    lambda m:m['location'].update(floor_elevation_m=m['pump_axis_m']),
    lambda m:m['location'].update(suction_nozzle_elevation_m=m['pump_axis_m']+.1),
    lambda m:m['location'].update(inlet_elevations_m={}),
    lambda m:m['location']['inlet_elevations_m'].update(other=-2.5),
    lambda m:m['location']['inlet_elevations_m'].update({m['supplies'][0]['name']:True}),
    lambda m:m['location']['inlet_elevations_m'].update({m['supplies'][0]['name']:999}),
])
def test_incomplete_or_contradictory_location_fails_closed(mutate):
    model = located_model(); mutate(model)
    with pytest.raises(ValueError): parse_model(model)


def test_optional_datums_preserve_old_inputs_and_all_hydraulic_results():
    model = located_model(); before = deepcopy(model)
    old = deepcopy(model); old.pop('location')
    parsed, old_parsed = parse_model(model), parse_model(old)
    assert parsed.network == old_parsed.network
    assert parsed.station == old_parsed.station
    assert from_model(old) is None and 'location' not in old_parsed.model
    _,_,located = evaluate(model)
    _,_,original = evaluate(old)
    for key in ('rows','static_rows','scenario_count','minimum_pass_count','pipework'):
        assert located[key] == original[key]
    assert located['input_sha256'] != original['input_sha256']
    assert model == before
    # Private archival format retains explicit input, not a derived room guess.
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    req = build_handoff_request(station_draft(model))
    assert load_request(dump_request(req)).fire_station_model == model


def test_catalogue_bare_pump_not_factory_station_and_no_automatic_retrofit():
    model = located_model(); before = deepcopy(model)
    ref = connection_review(model, 'CNP CDM32-3')
    assert ref['nozzle_dn'] == 65 and ref['height_mm'] == 1055
    assert ref['mass_kg'] == 102 and ref['nozzle_axis_from_base_mm'] == 105
    assert ref['mismatched_sides'] == ['suction','discharge']
    assert ref['selected_pn'] is None and ref['product_verified'] is False
    assert model == before
    for name in ('CNP CDMF32-3','CNP CDM32-3-2','PFFS 2 CDM32-3D','CNP CDM32-3 Ex'):
        assert reference(name) is None
    ref['dimensions_mm']['H'] = 1
    assert reference('CNP CDM32-3')['dimensions_mm']['H'] == 1055


@pytest.mark.parametrize('version', [1,2])
def test_location_does_not_require_pipework_migration(version):
    from tests.test_fire_review_binding import passing_model
    m = passing_model()
    if version == 1:
        m['schema_version'] = 1
        m.pop('pressure_review')
    before = parse_model(m)
    m['location'] = located_model()['location']
    after = parse_model(m)
    assert after.station == before.station and after.network == before.network
    assert 'pipework' not in after.model


@pytest.fixture(scope='module')
def located_bundle(tmp_path_factory):
    return bundle(located_model(), tmp_path_factory.mktemp('station-location'))


def test_location_in_output_api_spec_and_gate_without_fake_readiness(located_bundle):
    from app.pz.fire_review_binding import spec_rows
    from app.pz.commission import build_commission_report
    p = located_bundle.project
    data = summary(located_bundle)
    assert data['location'] == located_model()['location']
    assert data['pump_geometry']['mismatched_sides'] == ['suction','discharge']
    rows = spec_rows(p)
    assert 'патрубки DN65' in rows[0]['mark'] and rows[0]['qty'] == 2
    assert 'Переходы к ветвям и потери увязать' in rows[0]['note']
    # No extra reducers/resistances are invented to make the product look ready.
    assert not any(r['id'].startswith(('ПС','ПН')) for r in rows)
    report = build_commission_report(p, artifacts={'Схема насосов, зон и ГВС':True})
    gates = {r['rule_id']:r for a in report.normative_audits for r in a['rows']}
    gate = gates['V-GOST-A05']
    assert gate['status'] == 'missing' and gate['blocks_release']
    assert 'проходки заданы явно' in gate['evidence']
    assert 'привязки помещения не подтверждены' not in gate['evidence']
    assert 'переходы к патрубкам' in gate['evidence']
    from app.pz.generator import generate_pz_html, generate_pump_selection_html
    for html in (generate_pz_html(p), generate_pump_selection_html(p)):
        assert 'Помещение' in html or 'помещение Т-01' in html
        assert 'патрубки DN65' in html and 'синтетическая привязка' in html


def test_three_distinct_datums_and_wall_crossings_in_same_sheet(located_bundle):
    from app.pz.fire_principle_scheme import build_station_sheet
    from tests.test_fire_principle_scheme import elements
    svg = build_station_sheet(located_bundle.project)
    marks = {e.attrib['data-level-mark']:float(e.attrib['data-elevation-m'])
             for e in elements(svg, 'data-level-mark')}
    assert marks == {'inlet-1':-2.5, 'inlet-2':-2.5, 'pump-axis':-2.45, 'station-floor':-3.25}
    assert len(elements(svg,'data-inlet-wall')) == 4
    assert 'Помещение Т-01' in svg and 'Точка подключения -2,19' in svg
    assert 'Пол и помещение насосной уточнить' not in svg
    assert 'Размещение условное; не монтажный план' in svg


def test_changed_location_requires_fresh_documents(located_bundle):
    from app.pz.fire_review_binding import validate_binding
    p = deepcopy(located_bundle.project)
    p.fire_station_model_input['location']['room_number'] = 'Т-02'
    with pytest.raises(ValueError): validate_binding(p)


def test_pdf_location_readable_and_report_keeps_source(located_bundle, tmp_path):
    import pymupdf
    from pypdf import PdfReader
    from app.pz.fire_review_scheme import generate_review_scheme
    from app.pz.fire_station_input_report import render_station_input_report
    p = located_bundle.project
    path = generate_review_scheme(tmp_path/'station.pdf', p)
    pdf = PdfReader(path)
    assert len(pdf.pages) == len(pdf.outline) == 5
    assert 'Т-01' in pdf.pages[0].extract_text()
    with pymupdf.open(path) as doc:
        for page in doc:
            spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans']]
            for a,b in combinations(spans,2):
                overlap=pymupdf.Rect(a['bbox']) & pymupdf.Rect(b['bbox'])
                assert overlap.width<=1 or overlap.height<=1,(page.number,a['text'],b['text'])
    report = render_station_input_report(tmp_path/'inputs.pdf', p, located_bundle.fire_station_result)
    text = ' '.join(page.extract_text() for page in PdfReader(report).pages)
    assert 'Привязка насосной' in text and 'синтетическая привязка' in text
    assert 'патрубки DN65' in text and '1055' in text
