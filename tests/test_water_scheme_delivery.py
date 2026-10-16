"""One current water drawing across intake, preview, package and saved links."""
from copy import deepcopy
from dataclasses import asdict

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request, IntakeError
from app.intake.studio_project import STUDIO_HANDOFF_VERSION, calculate_project
from app.intake.pilot_objects import calculation_stamp
from app.pz.generator import generate_scheme_result, generate_scheme_pdf
from app.pz.ios2_orchestrator import IOS2DesignBundle
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION, describe_scheme
from app.web import studio
from app.web.wizard import _bundle_documents
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft

client = studio_tests.client


def ordinary_draft(**overrides):
    return draft(floor_height_m=3.3, basement_kind='basement', basement_floor_m=-3.1,
                 roof_type='flat_non_accessible', section_fan_roof_level_m=6.6,
                 **({'water_inlet_elevation_m': -2.1} | overrides))


def test_ordinary_inputs_reach_new_renderer_without_assistant_geometry():
    d = ordinary_draft()
    before = deepcopy(d)
    project = build_project(build_handoff_request(d))
    original = deepcopy(asdict(project))
    assert project.metering_detail.inlet_elevation_m == -2.1
    assert describe_scheme(generate_scheme_result(project))['renderer'] == 'residential_cutaway'
    assert asdict(project) == original and d == before


@pytest.mark.parametrize('value', [None, -4, 0, 1])
def test_missing_or_outside_basement_inlet_never_gets_a_fake_mark(value):
    d = ordinary_draft()
    answer_field(d, 'water_inlet_elevation_m', value)
    project = build_project(build_handoff_request(d))
    assert project.metering_detail.inlet_elevation_m == value
    result = generate_scheme_result(project)
    info = describe_scheme(result)
    assert info['renderer'] == 'unified_cutaway'
    assert 'не применён' in info['note'] and 'ввода' in info['note']
    docs, _ = _bundle_documents(IOS2DesignBundle(project, scheme_pdf='/tmp/scheme.pdf',
                                                water_scheme_delivery=info))
    doc = next(d for d in docs if d['kind'] == 'scheme_pdf')
    assert doc['state'] == 'preliminary' and doc['water_scheme'] == info
    assert doc['state_note'] == info['note']


@pytest.mark.parametrize('value', ['nan', 'inf', True, 1001])
def test_inlet_validation(value):
    with pytest.raises(IntakeError):
        answer_field(ordinary_draft(), 'water_inlet_elevation_m', value)


def test_exact_selected_svg_exported_without_second_selection(tmp_path, monkeypatch):
    project = build_project(build_handoff_request(ordinary_draft()))
    result = generate_scheme_result(project)
    def forbidden(*args, **kwargs):
        raise AssertionError('A reviewed drawing must not be rebuilt for PDF')
    monkeypatch.setattr('app.pz.generator.generate_scheme_result', forbidden)
    path = generate_scheme_pdf(project, str(tmp_path/'water.pdf'), scheme_result=result)
    page = PdfReader(path).pages[0]
    assert float(page.mediabox.width)*25.4/72 == pytest.approx(594)
    assert float(page.mediabox.height)*25.4/72 == pytest.approx(420)


@pytest.mark.parametrize('kind', ['preview', 'package'])
@pytest.mark.parametrize('outdated', ['render_version', 'handoff_version', 'stamp'])
def test_stale_pdf_hidden_and_direct_access_revoked_without_deleting_archive(client, monkeypatch, tmp_path, kind, outdated):
    state = studio_tests.new(client)
    did = state['project_id']
    store = studio.StudioStore(tmp_path/'studio')
    with store.edit(did, state['revision']) as d:
        source = ordinary_draft()
        d['answers'] = source['answers']
        d['project_calculation'] = calculate_project(d)
        ident = 'a'*32
        d[kind] = dict(state='ready' if kind=='package' else 'preview', id=ident, run_id=ident,
                       documents=[dict(name='water.pdf', kind='scheme_pdf')],
                       render_version=DOCUMENT_RENDER_VERSION, handoff_version=STUDIO_HANDOFF_VERSION,
                       stamp=calculation_stamp(d))
        d[kind][outdated] = 'old'
    path = store.folder(did)/'previews'/ident/'water.pdf'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'%PDF-old-archive')
    before = store.load(did)
    result = client.get('/studio/api/draft').json()
    assert result[kind] is None and result['documents_need_refresh']
    assert result['revision'] == before['revision']
    assert store.load(did) == before and path.exists()
    assert client.get(f'/studio/api/{kind}/{ident}/files/water.pdf').status_code == 404
    if kind == 'package':
        assert client.get(f'/studio/api/package/{ident}/download').status_code == 404


def test_preview_stamp_survives_recalculation_but_not_renderer_upgrade(client, monkeypatch, tmp_path):
    from scripts.check_water_studio_delivery import download_checked_preview
    state = studio_tests.new(client)
    data = ordinary_draft()
    state = client.post('/studio/api/calculate', json={
        'revision': state['revision'],
        'answers': {k:v['value'] for k,v in data['answers'].items()},
    }).json()
    state, pdf, report = download_checked_preview(client, state)
    assert report['renderer'] == 'residential_cutaway' and report['package_page_matches']
    saved = deepcopy(state['preview'])
    assert saved['render_version'] == DOCUMENT_RENDER_VERSION
    state = client.post('/studio/api/calculate', json={'revision':state['revision']}).json()
    assert state['preview'] == saved and not state['documents_need_refresh']
    assert not state['project_calculation']['can_release']
    monkeypatch.setattr(studio, 'DOCUMENT_RENDER_VERSION', 'next-renderer')
    result = client.get('/studio/api/draft').json()
    assert result['preview'] is None and result['documents_need_refresh']
    doc = next(d for d in saved['documents'] if d['kind']=='scheme_pdf')
    assert client.get(f'/studio/api/preview/{saved["id"]}/files/{doc["name"]}').status_code == 404
    # Recalculation of the inputs cannot make the old preview current again.
    state = client.post('/studio/api/calculate', json={'revision':state['revision']}).json()
    assert state['preview'] is None
