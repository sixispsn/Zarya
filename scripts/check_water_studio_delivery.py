"""Read-only local acceptance through Studio HTTP: ordinary inputs and Samara.

Isolated temporary stores, no production data, no hand-edited Project after intake.
The final PDF contains only the two scheme files downloaded from Studio.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pypdf import PdfReader, PdfWriter

TWO_FLOOR_INPUTS = dict(
    object_name='Проверка выдачи Studio · 2 этажа', residents=20, apartments=8,
    consumer_code='residential_full_bath', hws_type='central', floors=2,
    building_height_m=6.6, fire_height_m=4.8, floor_height_m=3.3,
    basement_kind='basement', basement_floor_m=-3.1,
    roof_type='flat_non_accessible', section_fan_roof_level_m=6.6,
    water_inlet_elevation_m=-2.1, guaranteed_head_m=5,
    section_drainage='internal', storm_city='moscow', storm_roof_area_m2=252,
    hws_heater_in_scope='no',
)


def state(response):
    assert response.status_code == 200, response.text
    return response.json()


def download_checked_preview(client, current):
    """Compare actual downloaded standalone sheet with its page in IOS2."""
    current = state(client.post('/studio/api/preview', json={'revision':current['revision']}))
    preview = current['preview']
    docs = {d['kind']:d for d in preview['documents']}
    standalone = docs['scheme_pdf']
    package = docs.get('water_package_pdf') or docs['ios2_package_pdf']
    info = standalone['water_scheme']
    assert info == package['water_scheme']
    assert info['renderer'] == 'residential_cutaway', info

    def get(doc):
        url = f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}'
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert response.headers['x-zarya-preview'] == 'true'
        assert 'no-store' in response.headers['cache-control']
        return response.content

    sheet, combined = get(standalone), get(package)
    source, target = PdfReader(BytesIO(sheet)), PdfReader(BytesIO(combined))
    assert len(source.pages) == 1
    matches = [i for i,p in enumerate(target.pages)
               # PdfWriter rounds box coordinates on serialization (<1e-5 pt).
               if all(abs(float(x)-float(y)) < 1e-5
                      for x,y in zip(p.mediabox, source.pages[0].mediabox))
               # Merging may reserialize numeric literals/whitespace. Compare
               # parsed drawing operations, then rendered pixels/resources.
               and p.get_contents().operations == source.pages[0].get_contents().operations]
    assert len(matches) == 1, matches  # neither an older drawing nor a duplicate
    # Same operators are insufficient when merged resources/fonts are wrong.
    import pymupdf
    with pymupdf.open(stream=sheet, filetype='pdf') as a, pymupdf.open(stream=combined, filetype='pdf') as b:
        assert a[0].get_pixmap().samples == b[matches[0]].get_pixmap().samples
    assert source.pages[0].extract_text().strip()
    assert abs(float(source.pages[0].mediabox.width)*25.4/72-594) < .01
    report = dict(renderer=info['renderer'], svg_sha256=info['svg_sha256'],
                  package_page=matches[0]+1, package_page_matches=True,
                  file=standalone['name'], label=standalone['label'],
                  can_release=current['project_calculation']['can_release'])
    return current, sheet, report


def main():
    from fastapi.testclient import TestClient
    out = ROOT/'output/pdf/water-studio-delivery'
    out.mkdir(parents=True, exist_ok=True)
    reports, sheets = [], []
    with TemporaryDirectory(prefix='zarya-water-delivery-') as tmp:
        with patch.dict(os.environ, {
            'ZARYA_STUDIO_ENABLED':'1', 'ZARYA_PILOT_ENABLED':'0',
            'ZARYA_NORMATIVE_MONITOR_ENABLED':'0',
            'ZARYA_STUDIO_DIR':tmp+'/studio', 'ZARYA_PROJECTS_DIR':tmp+'/projects',
        }):
            from app.main import app
            with TestClient(app) as client:
                client.headers['X-Zarya-Studio'] = '1'
                current = state(client.post('/studio/api/draft'))
                current = state(client.post('/studio/api/calculate', json={
                    'revision':current['revision'], 'answers':deepcopy(TWO_FLOOR_INPUTS)}))
                current, sheet, report = download_checked_preview(client, current)
                reports.append(dict(case='ordinary_studio', **report))
                sheets.append(('2 этажа · обычный ввод Studio', sheet))
                assert not current['project_calculation']['can_release']
                current = state(client.post('/studio/api/study', json={
                    'revision':current['revision'], 'kind':'samara'}))
                current, sheet, report = download_checked_preview(client, current)
                reports.append(dict(case='samara_studio', **report))
                sheets.append(('Самара · контрольный пример Studio', sheet))
                assert not current['project_calculation']['can_release']
    final = out/'Вода_из_Studio_2_этажа_и_Самара.pdf'
    writer = PdfWriter()
    for title, content in sheets:
        writer.append(PdfReader(BytesIO(content)), outline_item=title)
    with final.open('wb') as stream:
        writer.write(stream)
    scratch = ROOT/'tmp/pdfs/water-studio-delivery'
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch/'audit.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print(final)
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
