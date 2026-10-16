"""Local API proof for object-specific L06. No production or frozen results."""
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from scripts.build_samara_section_study import load_basis, make_draft
from tests.test_studio_fire_review import review_model
from tests.test_fire_review_binding import passing_model


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--adopt',action='store_true',help='Separate positive fixture; does not modify the negative model')
    parser.add_argument('--full-package', action='store_true', help='Audit complete ordinary Studio output; requires --adopt')
    parser.add_argument('--pipework', action='store_true', help='Explicit separate synthetic pipework fixture; requires --adopt')
    parser.add_argument('--location', action='store_true', help='Explicit synthetic room datums; requires --pipework')
    parser.add_argument('--fittings-scope', action='store_true', help='Explicit equivalent-zeta scope for the QA model; requires --location')
    parser.add_argument('--meter-products', action='store_true', help='Audit current passport binding in ordinary Studio; requires --fittings-scope')
    parser.add_argument('--output-dir', help='Keep an independent set of QA artifacts')
    args = parser.parse_args()
    adopted = args.adopt
    if args.full_package and not adopted:
        parser.error('--full-package requires --adopt')
    if args.pipework and not adopted:
        parser.error('--pipework requires --adopt')
    if args.location and not args.pipework:
        parser.error('--location requires --pipework')
    if args.fittings_scope and not args.location:
        parser.error('--fittings-scope requires --location')
    if args.meter_products and not args.fittings_scope:
        parser.error('--meter-products requires --fittings-scope')
    output = Path(args.output_dir or ("output/pdf/studio-meter-products" if args.meter_products else
                  "output/pdf/studio-ios2-checked" if args.fittings_scope else
                  "output/pdf/studio-fire-location" if args.location else
                  "output/pdf/studio-fire-pipework" if args.pipework else
                  "output/pdf/studio-vk-package" if args.full_package else
                  "output/pdf/studio-fire-adopted" if adopted else "output/pdf/studio-fire-review")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = {k:v["value"] for k,v in make_draft(load_basis())["answers"].items()}
    inputs.update(fire_topology="separate", fire_station_model=passing_model() if adopted else review_model())
    if args.pipework:
        from tests.test_studio_fire_pipework import pipework_model
        inputs['fire_station_model'] = pipework_model()
    if args.location:
        from tests.test_studio_fire_location import located_model
        inputs['fire_station_model'] = located_model()
    if args.fittings_scope:
        from tests.test_studio_fire_fittings import scoped_model
        inputs['fire_station_model'] = scoped_model()
    with TemporaryDirectory(prefix="zarya-review-qa-") as folder, patch.dict(os.environ, {
        "ZARYA_STUDIO_ENABLED":"1", "ZARYA_PILOT_ENABLED":"0", "ZARYA_NORMATIVE_MONITOR_ENABLED":"0",
        "ZARYA_STUDIO_DIR":folder+"/studio", "ZARYA_PROJECTS_DIR":folder+"/projects"}):
        from app.main import app
        with TestClient(app) as client:
            client.headers["X-Zarya-Studio"] = "1"
            def state(response):
                assert response.status_code == 200, response.text
                return response.json()
            current = state(client.post("/studio/api/draft"))
            current = state(client.post("/studio/api/calculate", json={"revision":current["revision"], "answers":inputs}))
            calculation = current["project_calculation"]
            result = current["project_calculation"]["fire_station"]["pressure_review"]
            if args.location:
                station = calculation['fire_station']
                assert station['location'] == inputs['fire_station_model']['location']
                assert station['pump_geometry']['mismatched_sides'] == ['suction','discharge']
            if args.fittings_scope:
                assert station['pump_geometry']['fittings_coverage']['included']
            assert result["scenario_count"] == 45 and result["minimum_pass_count"] == (45 if adopted else 42)
            assert not current["project_calculation"]["can_release"]
            current = state(client.post("/studio/api/preview", json={"revision":current["revision"]}))
            documents = {r["kind"]:r for r in current["preview"]["documents"]}
            row = documents["fire_pressure_review_pdf"]
            url = f'/studio/api/preview/{current["preview"]["id"]}/files/{row["name"]}'
            response = client.get(url)
            assert response.status_code == 200
            pdf = PdfReader(BytesIO(response.content))
            assert pdf.outline
            text = " ".join(p.extract_text() for p in pdf.pages)
            assert "45" in text and (adopted or "42" in text) and "Диафрагмы" in text
            path = output / "В2_диафрагмы_и_ремонтные_режимы.pdf"
            path.write_bytes(response.content)
            if adopted:
                from pypdf import PdfWriter
                writer=PdfWriter()
                for kind,title in [('pump_selection_pdf','Насос: ПЗ и расчёт'),
                                   ('fire_pressure_review_pdf','Проверка диафрагм'),
                                   ('fire_station_scheme_pdf','В2: насосная, стояки и узлы'),('spec_pdf','Спецификация: фрагмент В2')]:
                    item=documents[kind]
                    doc_url=f'/studio/api/preview/{current["preview"]["id"]}/files/{item["name"]}'
                    reply=client.get(doc_url)
                    assert reply.status_code==200
                    source=PdfReader(BytesIO(reply.content))
                    (output/item['name']).write_bytes(reply.content)
                    pages=list(range(len(source.pages)))
                    if kind=='spec_pdf':
                        pages=[i for i,p in enumerate(source.pages) if 'Диафрагма ПК' in p.extract_text() or 'CNP CDM32-3' in p.extract_text()]
                    assert pages
                    writer.add_outline_item(title,len(writer.pages))
                    for i in pages: writer.add_page(source.pages[i])
                path=output/'В2_насос_диафрагмы_узлы_спецификация.pdf'
                with path.open('wb') as stream: writer.write(stream)
            if args.full_package:
                from pypdf import PdfWriter
                parts = [
                    ('water_package_pdf', 'ИОС2. ПЗ, расчёты, схемы и спецификация'),
                    ('wastewater_package_pdf', 'ИОС3. ПЗ, расчёты, схема и спецификация'),
                ]
                inventory, texts = [], {}
                for kind, item in documents.items():
                    doc_url = f'/studio/api/preview/{current["preview"]["id"]}/files/{item["name"]}'
                    reply = client.get(doc_url)
                    assert reply.status_code == 200, (kind, reply.text)
                    source = PdfReader(BytesIO(reply.content))
                    (output / item['name']).write_bytes(reply.content)
                    texts[kind] = ' '.join(page.extract_text() or '' for page in source.pages)
                    inventory.append(dict(kind=kind, name=item['name'], pages=len(source.pages)))
                assert 'NPSH' not in texts['wastewater_pz_pdf']
                assert 'резервного пожарного насоса' not in texts['wastewater_pz_pdf']
                assert 'Для резервного пожарного насоса' in texts['pz_pdf']
                assert 'Предварительная спецификация оборудования' in texts['pz_pdf']
                assert 'Расчётный расход хозяйственно-бытовых стоков' not in texts['pz_pdf']
                consistency = {}
                if args.meter_products:
                    meters = calculation['meters']
                    assert [(r['dn'],r['h_a']) for r in meters] == [(50,1.451),(32,3.479),(32,4.703)]
                    assert [r['q_min_passport_m3h'] for r in meters] == [.45,.12,.12]
                    assert all(r['ok_v'] is None and r['q_min_hourly_m3h'] is None for r in meters)
                    assert [r['product']['hydraulic_evidence']['at_flow_m3h'] for r in meters] == [30,12,12]
                    assert all(r['product']['hydraulic_evidence']['exact_loss_m'] is None for r in meters)
                    for kind in ('pz_pdf', 'metering_scheme_pdf'):
                        normalized = ''.join(texts[kind].split())
                        assert 'Δp≤0,1МПа' in normalized, kind
                        assert '12.15' in normalized, kind
                    for kind in ('pz_pdf', 'metering_scheme_pdf', 'spec_pdf'):
                        assert 'ВСКМ90ДГ' in ''.join(texts[kind].split()), kind
                    assert 'Подбор моделей узлов учёта' in texts['metering_scheme_pdf']
                if args.fittings_scope:
                    pump = calculation['fire_station']['pump']
                    for kind in ('pz_pdf', 'pump_selection_pdf', 'fire_station_input_pdf', 'fire_station_scheme_pdf'):
                        normalized = texts[kind].replace(',', '.')
                        assert pump['model'] in normalized
                        assert f"{pump['wp_q']:.3f}" in normalized and f"{pump['wp_h']:.3f}" in normalized
                    assert pump['model'] in texts['spec_pdf']
                    gate = next(g for g in calculation['quality']['gates'] if g['gate_id']=='documentation')
                    assert gate['state']=='blocked'
                    assert any(f['source']=='normative_audit' for f in gate['findings'])
                    consistency = dict(pump_and_duty_match=True, pump_in_spec=True,
                        fittings_scope_explicit=True, missing_gost_inputs_not_green=True)
                writer = PdfWriter()
                for kind, title in parts:
                    assert kind in documents, kind
                    if kind == 'water_package_pdf':
                        assert documents[kind]['state'] != 'ready'
                        # The same ordinary Studio PDF is delivered to the user;
                        # QA must no longer construct a more complete IOS2 itself.
                        (output/'ИОС2_контрольный_комплект.pdf').write_bytes(
                            (output/documents[kind]['name']).read_bytes())
                    writer.append(str(output / documents[kind]['name']), outline_item=title, import_outline=True)
                path = output / 'ВК_контрольный_комплект_Studio.pdf'
                with path.open('wb') as stream:
                    writer.write(stream)
                combined = PdfReader(path)
                def count_bookmarks(items):
                    count = 0
                    for item in items:
                        if isinstance(item, list):
                            count += count_bookmarks(item)
                        else:
                            assert 0 <= combined.get_destination_page_number(item) < len(combined.pages)
                            count += 1
                    return count
                bookmark_count = count_bookmarks(combined.outline)
                assert bookmark_count > len(parts)  # nested source bookmarks survived
                release = state(client.post('/studio/api/package', json={'revision': current['revision']}))
                assert release['package']['state'] == 'blocked'
                current = release
                (output / 'audit.json').write_text(json.dumps(dict(
                    fixture='Separate positive ordinary-Studio QA model; not approved real-project inputs',
                    calculation=calculation, documents=inventory, release=current['package'],
                    combined_parts=[kind for kind, _ in parts], bookmarks=bookmark_count,
                    consistency=consistency,
                ), ensure_ascii=False, indent=2, allow_nan=False))
            with TestClient(app) as other:
                other.headers["X-Zarya-Studio"] = "1"
                state(other.post("/studio/api/draft"))
                assert other.get(url).status_code == 404
            state(client.patch("/studio/api/answer", json={"revision":current["revision"],
                "field":"fire_station_model", "value":None}))
            assert client.get(url).status_code == 404
            (output/"review.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
            (output/"model.json").write_text(json.dumps(inputs["fire_station_model"],ensure_ascii=False,indent=2))
            (output/"answers.json").write_text(json.dumps(inputs,ensure_ascii=False,indent=2))
            print(json.dumps(dict(pdf=str(path),pages=len(PdfReader(path).pages),scenarios=result["scenario_count"],
                minimum_pass=result["minimum_pass_count"],private_and_revocation=True),ensure_ascii=False))


if __name__ == "__main__":
    main()
