"""Ordinary HTTP upload/calculation/PDF smoke using two disposable participants."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import time

import httpx
from pypdf import PdfReader
from weasyprint import HTML


def outline(reader):
    def walk(items):
        for item in items:
            if isinstance(item, list):
                yield from walk(item)
            else:
                number = reader.get_destination_page_number(item)
                assert 0 <= number < len(reader.pages)
                yield (str(item.title), number)
    return list(walk(reader.outline))


def section_input_contract(access, user_id, state, answers, out):
    """Check values, persisted DTO, drawing topology, PZ and quantities, not page count."""
    from app.intake.studio_store import StudioStore
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    from app.intake.project_builder import build_project
    from app.pz.wastewater_graphic_exports import representative_section_model
    from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
    from app.pz.generator import generate_wastewater_pz_html
    from app.pz.spec import build_wastewater_specification
    from xml.etree import ElementTree as ET

    values = {row['key']: row['value'] for row in state['fields']}
    keys = [k for k in answers if k.startswith(('section_fan_', 'storm_', 'section_funnel_'))]
    assert all(values[k] == answers[k] for k in keys)
    saved = StudioStore(Path(os.environ['ZARYA_STUDIO_DIR']) / '_users' / user_id).load(access.active_draft(user_id))
    request = build_handoff_request(saved)
    source = dump_request(request)
    project = build_project(load_request(source))
    model = representative_section_model(project)
    assert model.storm.funnels_count == project.storm.funnels_count == 2
    assert model.storm.risers_count == project.storm.risers_count == 1
    assert model.storm.selected_riser_dn_mm == project.storm.selected_riser_dn_mm == 100
    assert model.storm.max_riser_flow_lps == project.storm.max_riser_flow_lps == 11.518
    assert model.storm.result.q_total_l_per_s == 11.518
    assert model.funnel_heated is True and model.fan_plan.kind == 'common'
    assert model.fan.member_ids == ('К1-А', 'К1-Б', 'К1-В', 'К1-Г')
    assert model.fan_plan.diameter_mm == 100 and model.fan.space == 'technical_storey'
    assert (model.fan.space_floor_m, model.fan.collector_low_m,
            model.fan.collector_high_m, model.fan.roof_level_m) == (48, 49.5, 49.7, 51)
    svg = build_concept_section_svg(model)
    assert audit_concept_section_svg(model, svg) == ()
    root = ET.fromstring(svg)
    assert len([e for e in root.iter() if e.get('data-section-funnel')]) == 1
    assert 'data-storm-riser-dn="100"' in svg and 'data-fan-collector-dn="100"' in svg
    html = generate_wastewater_pz_html(project)
    assert model.storm.notice in html and model.fan_notice in html
    rows = [r for s in build_wastewater_specification(project).sections for r in s.rows]
    assert next(r for r in rows if r.name == 'Воронка водосточная для внутреннего водостока').qty == 2
    collector = next(r for r in rows if r.name == 'Сборный вентиляционный трубопровод К1')
    assert collector.type_mark == 'DN100' and collector.qty is None
    assert not project.sewage.pipes and not project.sewage.risers  # no fake measured network
    (out / 'section-inputs.yaml').write_text(source)
    (out / 'section-inputs.svg').write_text(svg)
    return dict(accepted=True, roof_flow_lps=11.518, riser_dn=100, funnels=2,
                pictured_funnels=1, fan_members=4, fan_dn=100, fake_lengths=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('answers', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--preview-readiness', action='store_true')
    parser.add_argument('--section-inputs', action='store_true')
    parser.add_argument('--design-basis', action='store_true')
    parser.add_argument('--section-review', action='store_true')
    parser.add_argument('--section-elevations', action='store_true')
    args = parser.parse_args()
    if args.section_elevations:
        args.section_review = True
    if args.section_review:
        args.design_basis = True
    if args.design_basis:
        args.section_inputs = True
    readiness = args.preview_readiness or args.section_inputs
    assert os.environ['ZARYA_BUILD_COMMIT'] == (
        'section-elevations-20261005' if args.section_elevations else 'section-review-20261005' if args.section_review else 'design-basis-20261005' if args.design_basis else 'section-inputs-20261005' if args.section_inputs else
        'preview-readiness-20261005' if args.preview_readiness else 'section-documents-20261005')
    assert os.environ['ZARYA_PILOT_ENABLED'] == '1'
    assert os.environ['ZARYA_PROJECTS_DIR'] == ('/data/projects' if args.live else '/tmp/zarya-smoke/projects')
    if not args.live:
        assert os.environ['ZARYA_DEPLOY_SMOKE'] == '1'
    base = 'https://zaryaproekt.ru' if args.live else 'http://127.0.0.1:8000'
    for _ in range(100):
        try:
            if httpx.get(base + '/health', timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    else:
        raise AssertionError('Server unavailable')
    from app.intake.pilot_access import AccessStore
    from app.intake.studio_intake import FIELD_MAP
    requested_answers = json.loads(args.answers.read_text())
    answers = {k: v for k, v in requested_answers.items() if k in FIELD_MAP}
    unsupported = sorted(set(requested_answers) - set(answers))
    if args.section_inputs:
        assert not unsupported, unsupported  # never silently drop project input
    elif args.preview_readiness:
        # Explicitly deferred input work, not silently accepted project values.
        assert set(unsupported) == {
            'storm_funnels_count', 'storm_selected_riser_dn_mm', 'storm_risers_count',
            'section_funnel_heated', 'storm_funnels_on_different_levels', 'storm_max_riser_flow_lps',
            'section_fan_mode', 'section_fan_space', 'section_fan_member_ids',
            'section_fan_working_diameter_mm', 'section_fan_opening_distance_m',
            'section_fan_plastic_exposed', 'section_fan_uv_protected',
            'section_fan_collector_low_m', 'section_fan_collector_high_m',
            'section_fan_space_floor_m', 'section_fan_roof_level_m', 'section_fan_source_ref',
        }
    access = AccessStore()
    users_before = {u['id']: u for u in access.list_users()}
    issued = []
    out = Path('/tmp/zarya-sections-qa'); out.mkdir(mode=0o700, exist_ok=True)
    summary = {'unsupported_answer_fields': unsupported}
    try:
        for name in ('A', 'B'):
            issued.append(access.issue('Автопроверка PDF разделов — временный доступ ' + name, days=1))
        headers = {'Origin': base, 'X-Zarya-Studio': '1', 'X-Zarya-Access': '1'}
        with httpx.Client(base_url=base, headers=headers, timeout=240) as a, httpx.Client(base_url=base, headers=headers, timeout=30) as b:
            for client, (_, key) in zip((a, b), issued):
                assert client.get('/studio/api/draft').status_code == 401
                r = client.post('/access/login', json={'key': key, 'remember_device': True})
                assert r.status_code == 200
                assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
                if args.live:
                    assert 'Secure' in r.headers['set-cookie']
                assert client.get('/wizard/projects').status_code == 403
                assert client.get('/access/admin').status_code == 403
            def call(method, url, **kwargs):
                r = a.request(method, url, **kwargs)
                assert r.status_code == 200, (url, r.status_code, r.text[:150])
                return r
            page = call('GET', '/studio').text
            js_version = '43-section-review' if args.section_review else '42-design-basis' if args.design_basis else '41-section-inputs' if args.section_inputs else '40-section-documents'
            assert 'studio.js?v=' + js_version in page
            js = call('GET', '/static/studio.js?v=' + js_version).text
            assert 'ИОС2 одним PDF' in js and 'ИОС3 одним PDF' in js and 'data-review-section' in js
            assert a.post('/studio/api/draft', headers={'Origin': 'https://invalid.example'}).status_code == 403
            state = call('POST', '/studio/api/draft').json()
            a.headers['X-Zarya-Draft'] = state['project_id']
            uploaded = HTML(string='<meta charset="utf-8"><p>Проверка загрузки. Исходные данные задаются отдельно.</p>').write_pdf()
            state = call('POST', '/studio/api/files', data={'revision': state['revision']},
                         files=[('files', ('Проверка.pdf', uploaded, 'application/pdf'))]).json()
            assert len(state['documents']) == 1
            file_url = '/studio/api/files/' + state['documents'][0]['id']
            assert call('GET', file_url).content == uploaded
            assert b.get(file_url).status_code == 404
            state = call('POST', '/studio/api/calculate', json={'revision': state['revision'], 'answers': answers}).json()
            calc = state['project_calculation']; meters = calc['meters']
            if args.section_inputs:
                summary['section_inputs'] = section_input_contract(access, issued[0][0], state, answers, out)
                baseline = json.loads(args.answers.with_name('baseline-calculation.json').read_text())
                for key in ('flows', 'meters', 'head', 'pumps', 'storm', 'fire_station'):
                    assert calc[key] == baseline[key], key
            assert [(r['dn'], r['h_a']) for r in meters] == [(50, 1.451), (32, 3.479), (32, 4.703)]
            assert [r['q_min_passport_m3h'] for r in meters] == [.45, .12, .12]
            assert all(r['ok_v'] is None and r['q_min_hourly_m3h'] is None for r in meters)
            pressure = calc['fire_station']['pressure_review']
            assert pressure['minimum_pass_count'] == pressure['scenario_count'] == 45
            assert not calc['can_release']
            sections = calc['review_sections']
            assert [s['id'] for s in sections] == ['ios2', 'ios3', 'common']
            original = [f for g in calc['quality']['gates'] for f in g['findings']
                        if f['state'] != 'ready' and f['source'] != 'quality_gates']
            grouped = [{k: v for k, v in f.items() if k != 'gate_id'} for s in sections for f in s['findings']]
            canonical = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
            assert canonical(grouped) == canonical(original)
            (out / 'calculation.json').write_text(json.dumps(calc, ensure_ascii=False, indent=2))
            state = call('POST', '/studio/api/preview', json={'revision': state['revision']}).json()
            if readiness:
                current = state['project_calculation']
                def findings(c):
                    return {f['code']: f for g in c['quality']['gates'] for f in g['findings']
                            if f['source'] != 'quality_gates'}
                before, after = findings(calc), findings(current)
                closed = {'V-GOST-A01', 'V-GOST-A02', 'V-GOST-A03', 'V-GOST-A06',
                          'K-GOST-A01', 'K-GOST-A02', 'K-GOST-A03'}
                assert all(before[c]['state'] == 'conditional' and after[c]['state'] == 'ready' for c in closed)
                assert all(after[c]['state'] == 'blocked' for c, f in before.items() if f['state'] == 'blocked')
                assert after['V-GOST-A07']['state'] == 'blocked'
                assert after['K2-02']['detail'] and not current['can_release']
                for key in ('flows', 'meters', 'head', 'pumps', 'storm', 'fire_station', 'sewer_scheme'):
                    assert current[key] == calc[key], key
                assert call('GET', '/studio/api/draft').json()['project_calculation'] == current
                (out / 'preview-calculation.json').write_text(json.dumps(current, ensure_ascii=False, indent=2))
                summary.update(file_checks_closed=sorted(closed),
                               preview_findings=sum(len(s['findings']) for s in current['review_sections']),
                               preview_blockers=current['quality']['blocking_count'],
                               calculations_unchanged=True)
            if args.section_review:
                from verify_section_review_release import verify
                state, summary['section_review'] = verify(call, b, state, out)
            if args.section_elevations:
                current = state['section_review']['current']
                data = call('GET',f'/studio/api/preview/{current["preview_id"]}/files/{current["filename"]}').content
                text = '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(data)).pages)
                for value in ('Абс. +97,60', 'Абс. +97,70', '-0,65', '-0,80', 'Учебно принято 100,00'):
                    assert ''.join(value.split()) in ''.join(text.replace('−','-').split()), value
                assert 'studio_configurator.js?v=14-section-elevations' in page
                before = call('GET','/studio/api/draft').json()
                bad = a.patch('/studio/api/answer',json={'revision':state['revision'],
                    'field':'section_k1_start_invert_m','value':-3})
                assert bad.status_code == 422, (bad.status_code,bad.text[:200])
                assert call('GET','/studio/api/draft').json() == before
                summary['section_elevations'] = dict(absolute_outlets=[97.6,97.7], main_starts=[-.65,-.8],
                    counter_slope_rejected=True, same_private_pdf=True)
            docs = {d['kind']: d for d in state['preview']['documents']}
            urls = []; pages = {}; bookmarks = {}
            for kind in ('pz_pdf', 'scheme_pdf', 'metering_scheme_pdf', 'pump_zone_scheme_pdf',
                         'fire_station_scheme_pdf', 'spec_pdf', 'water_package_pdf', 'wastewater_package_pdf'):
                d = docs[kind]
                if kind.endswith('package_pdf'):
                    assert d['state'] in {'preliminary', 'incomplete'}
                url = f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}'
                urls.append(url); response = call('GET', url)
                assert b.get(url).status_code == 404
                assert response.headers['x-zarya-preview'] == 'true'
                pdf = PdfReader(BytesIO(response.content))
                if kind == 'pz_pdf':
                    text = ' '.join(p.extract_text() or '' for p in pdf.pages)
                    assert 'Расчётный расход хозяйственно-бытовых стоков' not in text
                if args.section_inputs and kind == 'wastewater_package_pdf':
                    text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
                    assert 'Общая вытяжка' in text and 'К1-В' in text and 'К1-Г' in text
                    assert 'DN стояка К2 не задан' not in text and 'DN уточнить' not in text
                    assert '11,518' in text and '49,50' in text and '49,70' in text
                (out / d['name']).write_bytes(response.content)
                pages[kind] = len(pdf.pages); bookmarks[kind] = len(outline(pdf))
            assert pages['water_package_pdf'] == 46
            assert pages['water_package_pdf'] == sum(v for k, v in pages.items() if not k.endswith('package_pdf'))
            assert pages['wastewater_package_pdf'] > 0
            assert bookmarks['water_package_pdf'] >= 20
            state = call('POST', '/studio/api/package', json={'revision': state['revision']}).json()
            assert state['package']['state'] == 'blocked'
            if readiness:
                assert all(findings(state['project_calculation'])[code]['state'] == 'ready' for code in closed)
                state = call('POST', '/studio/api/calculate', json={'revision': state['revision']}).json()
                assert all(findings(state['project_calculation'])[code]['state'] == 'ready' for code in closed)
            changed_field, changed_value = (('storm_selected_riser_dn_mm', 150) if args.section_inputs
                                             else ('fire_station_model', None))
            state = call('PATCH', '/studio/api/answer', json={'revision': state['revision'], 'field': changed_field, 'value': changed_value}).json()
            if args.section_review:
                assert state['section_review']['state'] == 'stale'
                summary['section_review']['revoked_on_input_change'] = True
            assert all(a.get(url).status_code == 404 for url in urls)
            if args.section_inputs:
                assert state['preview'] is None
                state = call('POST', '/studio/api/calculate', json={'revision': state['revision']}).json()
                assert state['project_calculation']['storm'] == calc['storm']
                assert next(row for row in state['fields'] if row['key'] == changed_field)['value'] == 150
            if args.design_basis:
                from verify_design_basis_release import verify
                state, summary['design_basis'], basis_urls = verify(call, b, state, calc, out)
                assert all(a.get(url).status_code == 404 for url in basis_urls)
            if not args.live:
                state = call('POST', '/studio/api/study', json={'revision': state['revision'], 'kind': 'samara'}).json()
                a.headers['X-Zarya-Draft'] = state['project_id']
                state = call('POST', '/studio/api/preview', json={'revision': state['revision']}).json()
                d = next(d for d in state['preview']['documents'] if d['kind'] == 'vk_package_pdf')
                frozen_data = call('GET', f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}').content
                pdf = PdfReader(BytesIO(frozen_data))
                # Existing Samara references now appear in IOS2 as well: one extra PZ page.
                assert len(pdf.pages) == (53 if args.design_basis else 52)
                if args.design_basis:
                    assert 'Исходные данные для проектирования' in pdf.pages[0].extract_text()
                    assert 'ТЕСТ-ПЗ' not in '\n'.join(p.extract_text() or '' for p in pdf.pages)
                    outline(pdf)
                    (out / 'frozen-samara.pdf').write_bytes(frozen_data)
                summary['frozen_vk_pages'] = len(pdf.pages)
            for client in (a, b):
                assert client.post('/access/logout').status_code == 303
                assert client.get('/studio/api/draft').status_code == 401
            summary.update(status='PASS', live=args.live, pages=pages, bookmarks=bookmarks,
                           scenarios=45, upload=True, private_pdfs=True, revocation=True,
                           findings=len(original), sections=3, release_still_blocked=True)
    finally:
        for uid, _ in issued:
            access.revoke(uid)
        after = {u['id']: u for u in access.list_users()}
        assert all(after[k] == value for k, value in users_before.items()), 'Existing participants changed'
    summary['temporary_users_revoked'] = True
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
