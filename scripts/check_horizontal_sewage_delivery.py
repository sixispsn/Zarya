"""Ordinary Studio HTTP -> real downloadable calculation PDF. No project edits."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader
from scripts.check_water_studio_delivery import TWO_FLOOR_INPUTS, state

INPUTS = dict(TWO_FLOOR_INPUTS,
    object_name="Контроль формулы (7) · 20 жителей · N=32 · L=10 м",
    section_k1_flow_basis="whole_building", section_k1_fixtures_count=32,
    section_k1_receiving_length_m=10,
    section_k1_dn_mm=100, section_k1_slope=.01,
    section_k1_outer_diameter_mm=110, section_k1_wall_thickness_mm=3.4,
    section_k1_material="pp", section_k1_manning_n=.011,
    section_k1_roughness_source="Контрольное n=0,011; не паспорт изделия",
    section_k1_source_ref="Контрольные исходные N=32, L=10 м; не данные реального объекта",
)
INTERPOLATED_INPUTS = dict(INPUTS,
    object_name="Контроль интерполяции Ks · 20 жителей · N=33 · L=8,5 м",
    section_k1_fixtures_count=33, section_k1_receiving_length_m=8.5,
    section_k1_source_ref="Синтетический контроль N=33, L=8,5 м; не данные реального объекта",
)


def check(client, *, interpolated=False):
    current = state(client.post('/studio/api/draft'))
    current = state(client.post('/studio/api/calculate', json={
        'revision':current['revision'], 'answers':INTERPOLATED_INPUTS if interpolated else INPUTS}))
    assert current['calculation']['sewage_flow'] == 2.293
    assert current['calculation']['total']['q_hr'] == 1.268
    current = state(client.post('/studio/api/preview', json={'revision':current['revision']}))
    preview = current['preview']
    docs = {row['kind']:row for row in preview['documents']}
    doc = docs['wastewater_calculation_pdf']
    response = client.get(f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}')
    assert response.status_code == 200, response.text
    assert 'no-store' in response.headers['cache-control']
    pdf = response.content
    content = ' '.join('\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages).split())
    expected_values = (('1,130', '0,48625', '8,5', 'линейной интерполяцией по N и L',
                        'не отдельное предписание СП', 'N=32, L=7', 'N=36, L=10')
                       if interpolated else ('1,104', '0,47', 'точной ячейки'))
    for expected in (*expected_values, '1,268', 'формула (7)', 'таблица 5.1'):
        assert expected in content, expected
    assert not current['project_calculation']['can_release']
    return pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interpolated', action='store_true', help='Check N=33, L=8.5; keep the exact-cell fixture unchanged')
    args = parser.parse_args()
    from fastapi.testclient import TestClient
    with TemporaryDirectory(prefix='zarya-horizontal-') as tmp, patch.dict(os.environ, {
        'ZARYA_STUDIO_ENABLED':'1', 'ZARYA_PILOT_ENABLED':'0',
        'ZARYA_NORMATIVE_MONITOR_ENABLED':'0',
        'ZARYA_STUDIO_DIR':tmp+'/studio', 'ZARYA_PROJECTS_DIR':tmp+'/projects',
    }):
        from app.main import app
        with TestClient(app) as client:
            client.headers['X-Zarya-Studio'] = '1'
            pdf = check(client, interpolated=args.interpolated)
    name = 'К1_расчёт_Studio_интерполяция_Ks.pdf' if args.interpolated else 'К1_расчёт_Studio_формула_7.pdf'
    output = ROOT/'output/pdf/sewage-horizontal'/name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf)
    print(output)


if __name__ == '__main__':
    main()
