"""Reproduce apartment quantities through ordinary Studio HTTP, not Samara.

All inputs are synthetic test inputs. Does not amend any user's project, frozen
study, production server or accepted hydraulic algorithm.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from fastapi.testclient import TestClient
    from pypdf import PdfReader
    out = ROOT / 'output/pdf/apartment-units-check'
    out.mkdir(parents=True, exist_ok=True)
    answers = dict(object_name='Проверка квартирных узлов: 8 квартир', residents=20,
        apartments=8, consumer_code='residential_full_bath', floors=2, floor_height_m=3.3,
        building_height_m=6.6, fire_height_m=4.8, hws_type='central', guaranteed_head_m=5,
        h_geom_m=6, pressure_loss_mode='ready', h_il_m=3, h_vvod_m=1,
        t3_loss_mode='ready', h_il_hot_m=4, hws_heater_in_scope='no',
        basement_kind='basement', basement_floor_m=-3.1, roof_type='flat_non_accessible',
        water_inlet_elevation_m=-2.1, section_fan_roof_level_m=6.6,
        apartment_units_mode='one_per_apartment')
    def state(response):
        assert response.status_code == 200, response.text
        return response.json()
    with TemporaryDirectory(prefix='zarya-apartment-spec-') as tmp:
        with patch.dict(os.environ, {'ZARYA_STUDIO_ENABLED': '1', 'ZARYA_PILOT_ENABLED': '0',
            'ZARYA_NORMATIVE_MONITOR_ENABLED': '0', 'ZARYA_STUDIO_DIR': tmp+'/studio',
            'ZARYA_PROJECTS_DIR': tmp+'/projects'}):
            from app.main import app
            with TestClient(app) as client:
                client.headers['X-Zarya-Studio'] = '1'
                current = state(client.post('/studio/api/draft'))
                current = state(client.post('/studio/api/calculate', json={
                    'revision': current['revision'], 'answers': answers}))
                assert current['project_calculation']['can_preview']
                assert not current['project_calculation']['can_release']
                current = state(client.post('/studio/api/preview', json={'revision': current['revision']}))
                preview = current['preview']
                doc = next(d for d in preview['documents'] if d['kind'] == 'spec_pdf')
                response = client.get(f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}')
                assert response.status_code == 200 and response.headers['x-zarya-preview'] == 'true'
                pdf = response.content
    reader = PdfReader(BytesIO(pdf))
    text = '\n'.join(p.extract_text() for p in reader.pages)
    # Source multiplication must accompany each of the eight components.
    normalized = ' '.join(text.split())
    for system in ('В1', 'Т3'):
        assert normalized.count(f'1 узел {system} на квартиру × 8 квартир') == 4
    assert normalized.count('DN и модель по подбору квартирного узла') == 8
    target = out / 'Квартирные_узлы_проверка_8_квартир.pdf'
    target.write_bytes(pdf)
    report = dict(synthetic_inputs=answers, can_release=False, pages=len(reader.pages),
                  input_stamp=preview['stamp'], apartment_rows=8, quantity_per_row=8)
    (out/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(pdf=str(target), **report), ensure_ascii=False))


if __name__ == '__main__':
    main()
