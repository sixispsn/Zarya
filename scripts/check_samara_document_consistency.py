"""Download and cross-check Samara IOS2/IOS3 through isolated real Studio HTTP.

No production access, invented inputs, hand-edited Project, or frozen-case rebuild.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader
import pymupdf


def state(response):
    assert response.status_code == 200, response.text
    return response.json()


def match_pages(source, target):
    """Verify both content operators and pixels after the final PDF merge."""
    a, b = PdfReader(BytesIO(source)), PdfReader(BytesIO(target))
    matches = []
    with pymupdf.open(stream=source, filetype="pdf") as ra, pymupdf.open(stream=target, filetype="pdf") as rb:
        for i, page in enumerate(a.pages):
            found = [j for j, p in enumerate(b.pages)
                     if all(abs(float(x)-float(y)) < 1e-5 for x, y in zip(page.mediabox, p.mediabox))
                     and page.get_contents().operations == p.get_contents().operations]
            assert len(found) == 1, (i, found)
            j = found[0]
            assert ra[i].get_pixmap().samples == rb[j].get_pixmap().samples
            matches.append(j+1)
    return matches


def checked_outline(reader):
    """Check nested destinations after composition, not just outline presence."""
    entries = []
    def walk(rows, depth=0):
        for row in rows:
            if isinstance(row, list):
                walk(row, depth + 1)
            else:
                index = reader.get_destination_page_number(row)
                assert index is not None and 0 <= index < len(reader.pages), row
                entries.append(dict(title=row.title, page=index + 1, depth=depth))
    walk(reader.outline)
    assert entries
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'output/pdf/samara-consistency')
    args = parser.parse_args()
    from fastapi.testclient import TestClient
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="zarya-samara-consistency-") as tmp:
        with patch.dict(os.environ, {
            "ZARYA_STUDIO_ENABLED":"1", "ZARYA_PILOT_ENABLED":"0",
            "ZARYA_NORMATIVE_MONITOR_ENABLED":"0",
            "ZARYA_STUDIO_DIR":tmp+"/studio", "ZARYA_PROJECTS_DIR":tmp+"/projects",
        }):
            from app.main import app
            with TestClient(app) as client:
                client.headers["X-Zarya-Studio"] = "1"
                current = state(client.post("/studio/api/draft"))
                current = state(client.post("/studio/api/study", json={"revision":current["revision"], "kind":"samara"}))
                current = state(client.post("/studio/api/preview", json={"revision":current["revision"]}))
                preview = current["preview"]
                docs = {d["kind"]:d for d in preview["documents"]}
                assert len({d["model_hash"] for d in docs.values()}) == 1
                assert not current["project_calculation"]["can_release"]
                files = {}
                for kind, doc in docs.items():
                    response = client.get(f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}')
                    assert response.status_code == 200
                    assert response.headers["x-zarya-preview"] == "true"
                    files[kind] = response.content

    # Keep the actual HTTP output even when a subsequent audit finds a new
    # discrepancy. It must be inspectable, never silently called a passed run.
    component_dir = out/'components'
    component_dir.mkdir(exist_ok=True)
    for kind, content in files.items():
        (component_dir/(kind+'.pdf')).write_bytes(content)

    water, sewer = files["ios2_package_pdf"], files["ios3_package_pdf"]
    report = dict(model_hash=next(iter(docs.values()))["model_hash"],
                  can_release=False, calculation=current["project_calculation"], matches={})
    water_parts = ("pz_pdf", "fire_station_design_pdf", "scheme_pdf", "metering_scheme_pdf",
                   "pump_zone_scheme_pdf", "spec_pdf", "fire_station_scheme_pdf")
    sewer_parts = ("wastewater_pz_pdf", "wastewater_scheme_pdf", "wastewater_spec_pdf", "wastewater_ugo_pdf",
                   "wastewater_calculation_pdf", "wastewater_balance_pdf")
    for kind in water_parts:
        report["matches"][kind] = match_pages(files[kind], water)
    for kind in sewer_parts:
        report["matches"][kind] = match_pages(files[kind], sewer)
    for content, parts in ((water, water_parts), (sewer, sewer_parts)):
        checked = {i for kind in parts for i in report["matches"][kind]}
        assert checked == set(range(1, len(PdfReader(BytesIO(content)).pages)+1))

    def text(data):
        return " ".join(" ".join(p.extract_text() for p in PdfReader(BytesIO(data)).pages).split())

    wt, st = text(water), text(sewer)
    for heading in ('Расход К1 по формуле для стояков', 'Проверка характерных стояков К1'):
        assert heading not in wt and heading in st, heading
    assert 'Паспорт проекта и нормативный контроль' not in wt
    assert all(s in wt for s in ("11,466", "50,25", "14,78", "58,22", "48,924", "3,263", "63,000"))
    assert "-2,19" not in text(files["metering_scheme_pdf"])
    assert "-2,20" in text(files["metering_scheme_pdf"])
    assert "Qрасч=11,466" in text(files["spec_pdf"])
    assert "не уставка ПЧ" in text(files["spec_pdf"])
    for kind in ('pz_pdf', 'metering_scheme_pdf', 'spec_pdf'):
        # SVG fonts may omit word-space glyphs in PDF extraction.
        assert 'ВСКМ90ДГ' in text(files[kind]).replace(' ', ''), kind
    assert all(v in text(files['metering_scheme_pdf']) for v in ('0,450', '0,120', '1,451', '3,479', '4,703'))
    assert '1 комплект на узел × 2 узлов' in text(files['spec_pdf'])
    spec_text = text(files['spec_pdf'])
    # Cold branch remains a separate meter row; the hot/heater branch now
    # belongs to its own detailed graph, with one kit owning both ends.
    assert spec_text.count('1 комплект × 1 счётчик ветви; не на каждый ввод') == 1
    assert spec_text.count('1 комплект на узел × 1 узлов; две присоединительные детали в комплекте; один расчётный узел ветви, не на каждый ввод') == 1
    assert 'К поз. Г.7; один комплект на узел' in spec_text
    assert 'К поз. Г.3.1, Г.3.2 и Г.4.1' in spec_text
    metering_reader = PdfReader(BytesIO(files['metering_scheme_pdf']))
    hot_pages = [i + 1 for i, p in enumerate(metering_reader.pages)
                 if 'ВУ-Г.' in (p.extract_text() or '')]
    assert len(hot_pages) == 5, hot_pages  # three detail sheets + two service-audit sheets
    assert 'Вводной учёт воды: узлов — 2; по одному счётчику DN50 на каждом вводе.' in wt
    report['hot_meter_detail'] = dict(system='В1', kind='before_heater',
        sheets=hot_pages, position='Г.7', instances=1,
        installation_complete=False)
    report['hot_meter_detail']['package_sheets'] = [report['matches']['metering_scheme_pdf'][i-1]
                                                   for i in hot_pages]
    assert any('ВУ-Г.' in row['title'] for row in checked_outline(PdfReader(BytesIO(water))))
    assert 'Комплект присоединительных частей ДЕКАСТ ВСКМ 90 DN50' in spec_text
    assert spec_text.count('Комплект присоединительных частей ДЕКАСТ ВСКМ 90 DN32') == 2
    report['meter_node_kits'] = dict(total=2, cold=1, hot=1,
        main_model='decast-vskm90-kit-dn50', branch_model='decast-vskm90-kit-dn32',
        basis='one kit per counted meter; included supply not purchased twice',
        mounting_length_confirmed=False)
    for page in PdfReader(BytesIO(files['spec_pdf'])).pages:
        # No overflow orphan row on a new sheet without its column headings.
        assert 'Поз.' in page.extract_text() and 'Поставщик' in page.extract_text()
    for system in ('В1', 'Т3'):
        assert spec_text.count(f'1 узел {system} на квартиру × 143 квартир') == 4
        assert f'1 РД на ввод × 98 квартир' in spec_text
    for mark in ('VT.214.N; DN15', 'VT.386; DN15', 'EUROPA 100 (G); DN15', 'OR.224.G; DN15'):
        assert spec_text.count(mark) == 2, mark
    assert spec_text.count('ВСКМ 90 ДГ; DN15') == 4  # two meters plus two kit rows
    for system in ('В1', 'Т3'):
        assert f'1 комплект на счётчик {system} × 143 узлов' in spec_text
    assert 'повторно не закупать' in spec_text and 'уставка по подбору' in spec_text
    assert spec_text.count('VTr.582.N; G1/2 НР/НР') == 4
    assert spec_text.count('PE-X Ø20×2 × евроконус 3/4 ВР') == 4
    assert spec_text.count('Евроконус 3/4 НР × G1/2 НР') == 4
    assert spec_text.count('1 фитинг × 143 узлов') == 4
    assert spec_text.count('1 переходник × 143 узлов') == 4
    assert 'подтяжки каждые 6 мес.' in spec_text
    assert spec_text.count('1 соединение × 143 узлов') == 2
    assert spec_text.count('1 соединение × 98 узлов') == 2
    assert 'габариты в источниках расходятся' in spec_text
    assert all(mark in spec_text for mark in ('0,217 л/с', '0,23 л/с', '0,683 м', '0,767 м',
                                              'не паспортное h(Q)', 'Предварительное предложение'))
    report['apartment_products'] = dict(dn_cold=15, dn_hot=15, residents=3,
        flows_lps=[.217,.230], reference_losses_m=[.683,.767], status='preliminary',
        models=['ДЕКАСТ ВСКМ 90 ДГ','VALTEC VT.214.N','VALTEC VT.386','ITAP EUROPA 100 (G)'],
        kits_per_system=143, regulator_candidate='Officine Rigamonti OR.224.G.04', setting_bar=None)
    report['apartment_connections'] = dict(pipe_requirement='PE-X 20×2 × G1/2 male',
        pipe_end_connections_per_system=286,
        pipe_fitting_article='VT.4410.NE.20', pipe_fittings_per_system=286,
        pipe_adapter_article='VTr.580.NE.040E', pipe_adapters_per_system=286,
        pipe_adapter_dimensions_status='conflict', service_access_required=True,
        valve_filter_nipples_per_system=143, filter_regulator_nipples_per_system=98,
        nipple_candidate='VTr.582.N.0004', nipple_dimensions_status='conflict',
        installation_complete=False, quantities_basis='accepted_apartment_unit_schedule')
    for system in ('В1', 'Т3', 'Т4'):
        assert f'Число стояков {system} не задано' in spec_text
    assert 'Оценка по площади, не обмер трасс' in spec_text
    report['quantity_review'] = dict(apartments=143, cold_units=143, hot_units=143,
        cold_regulators=98, hot_regulators=98, riser_counts=None,
        note='Количество РД по принятой поэтажной компоновке; OR.224.G DN15 — кандидат, уставка не назначена')
    assert "Расчётный расход Qрасч 11,466 м³/ч" in wt
    assert "Требуемый напор насоса Hтреб 50,25 м" in wt
    assert "Воронка водосточная для внутреннего водостока с электрообогревом" in " ".join(text(files["wastewater_spec_pdf"]).split())
    assert all(s in st for s in ("4,785", "11,518", "63,000", "10,000", "Уклон, ‰", "КК-1", "ДК-1"))
    assert "В2: проверены характерные" not in st
    assert "512/512" in wt and "13824" in wt
    horizontal = current['project_calculation']['wastewater']['horizontal_k1']
    assert horizontal['status'] == 'verified'
    assert horizontal['flow_result']['fixtures_count'] == 636
    assert horizontal['flow_result']['receiving_length_m'] == 10
    assert horizontal['result']['design_flow_lps'] == 3.561
    for kind in ('wastewater_calculation_pdf', 'wastewater_pz_pdf', 'wastewater_scheme_pdf'):
        assert '3,561' in text(files[kind]), kind
    for kind in ('wastewater_calculation_pdf', 'wastewater_pz_pdf'):
        assert all(v in text(files[kind]) for v in ('Учебные N=636', '104,60', '0,808', '0,51', 'не паспортное'))
    for kind, name in (('metering_scheme_pdf', 'Самара_водомерные_узлы.pdf'),
                       ('spec_pdf', 'Самара_спецификация_ИОС2.pdf'),
                       ('wastewater_scheme_pdf', 'Самара_схема_К1_К2.pdf'),
                       ('wastewater_calculation_pdf', 'Самара_расчёт_К1_К2.pdf')):
        path = out/name
        path.write_bytes(files[kind])
        report[kind] = dict(file=str(path), sha256=sha256(files[kind]).hexdigest())
    for key, data in (("ИОС2", water), ("ИОС3", sewer)):
        pdf = PdfReader(BytesIO(data))
        bookmarks = checked_outline(pdf)
        path = out/f"{key}_Самара_сверка.pdf"
        path.write_bytes(data)
        report[key] = dict(file=str(path), pages=len(pdf.pages), sha256=sha256(data).hexdigest(),
                          bookmarks=bookmarks)
    (out/"audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != "calculation"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
