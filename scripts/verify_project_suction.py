"""Reproducible synthetic output QA; never edits Samara or a user's project."""
# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader
from app.intake.studio_store import StudioStore
from app.intake.studio_intake import answer_visible_form, build_handoff_request
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.ios2_orchestrator import design_ios2
from app.pz.generator import generate_pump_selection_pdf, generate_pz_pdf, generate_balance_pdf
from app.pz.suction_check import project_context, review_suction
from app.schemas.pump_suction import ProjectSuctionInput


def main():
    out = ROOT / 'output/pdf/suction-project-check'
    temp = ROOT / 'tmp/pdfs/suction-project-check'
    out.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='zarya-suction-qa-') as folder:
        _, draft = StudioStore(folder).create()
        answer_visible_form(draft, dict(residents=20, apartments=8,
            consumer_code='residential_full_bath', floors=2, building_height_m=6.6,
            fire_height_m=4.8, hws_type='central', inputs_count=2, guaranteed_head_m=5,
            h_geom_m=6, pressure_loss_mode='ready', h_il_m=3, h_vvod_m=1,
            t3_loss_mode='ready', h_il_hot_m=4, hws_heater_in_scope='no'), [])
        req = build_handoff_request(draft)
        project = design_ios2(build_project(req), output_dir=folder, render_documents=False).project
        context = project_context(project)
        route = context['routes'][0]
        req.suction_check = ProjectSuctionInput.model_validate(dict(
            fingerprint=context['fingerprint'], route_id=route['id'],
            path_basis='Синтетический последовательный режим одного пути; не решение потокораспределения Г.1.',
            balance=dict(pressure_kind='absolute', pressure_bar=1, source_elevation_m=0,
                pump_elevation_m=2, vapor_head_m=.2, max_flow_m3h=12, temperature_c=10,
                basis='Условные числа только для проверки программной интеграции. Не данные реального объекта.',
                npshr_m=6, npshr_basis='Условное значение при 12 м³/ч, не паспорт насоса.'),
            losses=[dict(id='QA-1', covers=route['required_components'], loss_m=1,
                flow_m3h=12, temperature_c=10, basis='Условная полная потеря 1 м для проверки переноса.')],
        )).model_dump()
        project = design_ios2(build_project(load_request(dump_request(req))),
                             output_dir=folder, render_documents=False).project
    assert review_suction(project)['result']['balance']['check_ok'] is True
    project.document.cipher = 'QA-NPSHA'
    project.document.object_name = 'Проверка интеграции на синтетических данных. Не для проектной выдачи'
    project.document.review_notes = ['Контрольный прогон программного обеспечения; не проект реального объекта.']
    before = deepcopy(asdict(project))
    target = out / 'Проверка_переноса_NPSHa.pdf'
    pz_target = out / 'Проверка_рамки_ПЗ.pdf'
    balance_target = out / 'Проверка_рамки_баланса.pdf'
    generate_pump_selection_pdf(project, str(target))
    generate_pz_pdf(project, str(pz_target))
    generate_balance_pdf(project, str(balance_target))
    assert asdict(project) == before
    report = {}
    for name, file in [('pump', target), ('pz', pz_target), ('balance', balance_target)]:
        reader = PdfReader(file)
        texts = [p.extract_text() or '' for p in reader.pages]
        report[name] = dict(file=str(file), pages=len(texts),
                           suction_pages=[i + 1 for i, t in enumerate(texts)
                                          if any(s in t for s in ('Проверка всасывания', 'NPSHa', 'QA-1', 'Состав покрытия'))])
        if name != 'balance':
            assert 'Условие выполнено' in '\n'.join(texts)
        else:
            assert len(reader.pages) == 1
            assert 'Баланс водопотребления' in texts[0]
            assert float(reader.pages[0].mediabox.width) > 1100  # separate A3 form 2
    # Keep incomplete/stale renderings as QA intermediates, not project issues.
    for state in ('incomplete', 'stale'):
        case = deepcopy(project)
        if state == 'incomplete':
            case.suction_check['losses'] = []
            expected = 'Проверка не завершена'
        else:
            case.source.h_vvod_m += 1
            expected = 'Проверка устарела'
        path = temp / (state + '.pdf')
        generate_pump_selection_pdf(case, str(path))
        reader = PdfReader(path)
        text = '\n'.join(p.extract_text() or '' for p in reader.pages)
        assert expected in text and 'Условие выполнено' not in text
        report[state] = dict(file=str(path), pages=len(reader.pages))
    (temp / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
