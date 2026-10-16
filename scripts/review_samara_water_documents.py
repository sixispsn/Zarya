"""Rebuild and reconcile the agreed common-G.1 Samara IOS2 review variant.

Uses the normal document pipeline and the current signed-study initializer.
The signed baseline stays unchanged. The only variant inputs are the agreed
common meter topology and a review label; calculations are not patched here.
Unknown new piping losses, NPSH and service drainage remain unconfirmed.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader
from app.intake import samara_study
from app.pz.generator import generate_scheme_result
from app.pz.ios2_orchestrator import design_ios2
from app.pz.spec import build_specification
from app.pz.water_package import PARTS, missing_water_parts
from app.pz.water_station_drafting import build_pump_zone_scheme_pages, station_counts
from app.pz.water_station_review import review_station, factory_component_ids
from scripts.check_samara_document_consistency import match_pages, checked_outline


def assert_variant_scope(baseline, variant):
    expected = deepcopy(asdict(baseline))
    expected['metering_detail']['inlet_metering_mode'] = 'common'
    expected['metering_detail']['common_topology'] = 'gost_g1'
    expected['document']['object_part'] = 'Вариант общего ВУ. Проверка компоновки'
    assert asdict(variant) == expected, 'Изменения вне согласованной компоновки ВУ'


def assert_unique_owners(rows, required_ids):
    counts = Counter(key for row in rows for key in row.component_ids)
    duplicates = {key: count for key, count in counts.items() if count != 1}
    assert not duplicates, f'Повторный учёт компонентов: {duplicates}'
    missing = sorted(key for key in required_ids if counts[key] != 1)
    assert not missing, f'Нет единственного владельца в СО: {missing}'
    return counts


def audit_model(project):
    before = deepcopy(asdict(project))
    rows = [r for section in build_specification(project, scope='water').sections for r in section.rows]
    station_pages = build_pump_zone_scheme_pages(project, include_building_section=False)
    links = {e.get('data-spec-component') for svg in station_pages
             for e in ET.fromstring(svg).iter() if e.get('data-spec-component')}
    counts = assert_unique_owners(rows, links | set(factory_component_ids(project)))
    for key, dn in (('meter', 50), ('meter_cold', 32), ('hot:meter', 32)):
        owner = next(r for r in rows if key in r.component_ids)
        assert owner.qty == 1 and f'DN{dn}' in owner.name, key
    assert sum(r.qty for r in rows if 'station_assembly' in r.component_ids) == 1
    assert station_counts(project.pumps) == (1, 1)
    assert abs(project.pumps.q_design_m3h - 11.466) < 1e-9
    assert abs(project.pumps.h_design_m - 50.25) < 1e-9
    domestic = deepcopy(project)
    domestic.fire.required = False
    domestic.fire_pumps.required = False
    drawing = ET.fromstring(generate_scheme_result(domestic).svg)
    assert drawing.get('data-residential-water-section') == 'approval'
    fixtures = [e for e in drawing.iter() if e.get('data-fragment-component') == 'fixture']
    assert len(fixtures) == 24
    assert not any('data-residential-water-section' in svg for svg in station_pages)
    review = review_station(project)
    assert review['supported'] and not review['hydraulic_capacity_confirmed']
    assert not review['operation_approved']
    for key, value in (('new_losses', 'Не подтверждены'), ('npsh', 'Требует увязки')):
        assert next(r for r in review['hydraulic'] if r['id'] == key)['value'] == value
    assert asdict(project) == before, 'Аудит изменил проект'
    return dict(component_ids=len(counts), station_spec_links=sorted(links),
                characteristic_fixture_symbols=len(fixtures), building_sections=1,
                pump=dict(working=1, reserve=1, q_m3h=project.pumps.q_design_m3h,
                          h_m=project.pumps.h_design_m),
                station_review=review)


def pdf_text(path):
    return ' '.join(' '.join(p.extract_text() or '' for p in PdfReader(path).pages).split())


def audit_pdf(bundle):
    assert not missing_water_parts(bundle), missing_water_parts(bundle)
    package = Path(bundle.water_package_pdf).read_bytes()
    reader = PdfReader(bundle.water_package_pdf)
    matches = {}
    for key, _ in PARTS:
        path = getattr(bundle, key, None)
        if path:
            matches[key] = match_pages(Path(path).read_bytes(), package)
    pages = [page for indices in matches.values() for page in indices]
    assert sorted(pages) == list(range(1, len(reader.pages) + 1)), 'Пропуск/повтор листов'
    text = pdf_text(bundle.water_package_pdf)
    for heading in ('Расход К1 по формуле для стояков', 'Проверка характерных стояков К1',
                    'Паспорт проекта и нормативный контроль'):
        assert heading not in text, heading
    for key in ('pz_pdf', 'pump_zone_scheme_pdf', 'spec_pdf'):
        part = pdf_text(getattr(bundle, key))
        assert '11,466' in part and '50,25' in part, key
    pz = pdf_text(bundle.pz_pdf)
    assert 'один общий ВУ' in pz and 'DN50' in pz
    assert 'по одному счётчику DN50 на каждом вводе' not in pz
    assert '75,63' in pz and '80,25' in pz
    assert 'Не подтверждены' in pdf_text(bundle.pump_zone_scheme_pdf)
    for page in PdfReader(bundle.spec_pdf).pages:
        text = page.extract_text() or ''
        assert 'Поз.' in text and 'Поставщик' in text, 'Продолжение СО без шапки'
    return dict(pages=len(reader.pages), matches=matches,
                bookmarks=checked_outline(reader), sha256=sha256(package).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'output/pdf/samara-water-documents')
    parser.add_argument('--scratch-dir', type=Path, default=ROOT/'tmp/pdfs/water-final-audit')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    baseline = samara_study.build(draft, args.scratch_dir, render=False)[0].project
    baseline_before = deepcopy(asdict(baseline))
    _, station, result, _ = samara_study.inputs(draft)
    project = deepcopy(baseline)
    project.metering_detail.inlet_metering_mode = 'common'
    project.metering_detail.common_topology = 'gost_g1'
    project.document.object_part = 'Вариант общего ВУ. Проверка компоновки'
    assert_variant_scope(baseline, project)
    report = dict(scope='Контрольная сборка Самары с согласованным общим ВУ Г.1',
                  release_approved=False, model=audit_model(project))
    bundle = design_ios2(project, output_dir=str(args.scratch_dir), fire_station=station,
                         fire_station_design=result, render_documents=True)
    assert_variant_scope(baseline, project)
    assert asdict(baseline) == baseline_before
    # Publish a successful review only after the actual merged PDF passes.
    report['pdf'] = audit_pdf(bundle)
    report['warnings'] = bundle.warnings
    report['calculation_unchanged'] = True
    target = args.output_dir/'Самара_ИОС2_общий_ВУ_сверка.pdf'
    target.write_bytes(Path(bundle.water_package_pdf).read_bytes())
    report['pdf']['file'] = str(target.resolve())
    (args.output_dir/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target.resolve())
    print(f"{report['pdf']['pages']} pages; {len(report['pdf']['bookmarks'])} bookmarks; calculation unchanged")
    for key, indices in report['pdf']['matches'].items():
        print(f'{key}: {indices[0]}-{indices[-1]}')


if __name__ == '__main__':
    main()
