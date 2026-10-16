"""Synthetic frame QA, never rewrites the signed Samara project or its PDFs."""
# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from reportlab.lib.units import mm
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.ios2_orchestrator import design_ios2
from app.pz.project import DocumentInfo
from app.pz import generator as g
from app.calc.ring_hydraulics import analyze_ring_resilience
from tests.test_hydraulic_report_render import _report_and_project
from tests.test_resilience_render import _net


def main():
    temp = ROOT / 'tmp/pdfs/annex-frame-review'
    out = ROOT / 'output/pdf/annex-frame-review'
    temp.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    project = design_ios2(build_project(load_request_file('demo/demo_project.yaml')),
                         output_dir=str(temp), render_documents=False).project
    project.document = DocumentInfo(cipher='QA-ИОС2',
        object_name='Контроль рамок на синтетических данных. Не для проектной выдачи',
        review_notes=('Проверка программного обеспечения, не проект реального объекта.',))
    hydraulic, fire_project = _report_and_project()
    fire_project.document = deepcopy(project.document)
    resilience = analyze_ring_resilience(_net(), 2)
    original = {name: deepcopy(asdict(getattr(project, name))) for name in ('flows', 'pumps', 'fire_pumps')}
    jobs = [
        ('СО водоснабжения', lambda p: g.generate_spec_pdf(project, p)),
        ('СО водоотведения', lambda p: g.generate_wastewater_spec_pdf(project, p)),
        ('Расчёт В1 и Т3', lambda p: g.generate_v1_calculation_pdf(project, p)),
        ('Расчёт К1 и К2', lambda p: g.generate_wastewater_calculation_pdf(project, p)),
        ('Дождевая вода', lambda p: g.generate_rainwater_reuse_pdf(project, p)),
        ('Нормативный контроль', lambda p: g.generate_commission_control_pdf(project, p)),
        ('Гидравлика В2', lambda p: g.generate_hydraulic_report_pdf(fire_project, hydraulic, p)),
        ('Живучесть В2', lambda p: g.generate_resilience_pdf(fire_project, resilience, p)),
        ('Задание В2', lambda p: g.generate_tz_pdf(fire_project, p)),
        ('Исходные данные В2', lambda p: g.generate_tu_pdf(fire_project, p)),
    ]
    paths, titles = [], []
    for number, (title, generate) in enumerate(jobs, 1):
        path = temp / f'{number:02}.pdf'
        generate(str(path))
        pdf = fitz.open(path)
        for i, page in enumerate(pdf, 1):
            dx = 210 if page.rect.width / mm > 400 else 0
            top = 237 if i == 1 else 277
            text = page.get_text()
            assert text.count('Изм.') == 1, (title, i)
            assert 'QA-ИОС' in text, (title, i)
            region = fitz.Rect((185+dx)*mm, 267*mm, (205+dx)*mm, 277*mm) if i == 1 else (
                fitz.Rect((195+dx)*mm, 284*mm, (205+dx)*mm, 292*mm))
            assert page.get_text(clip=region).strip() == str(len(pdf) if i == 1 else i), (title, i)
            if not dx:
                words = [w for w in page.get_text('words') if w[0]/mm > 21 and w[1]/mm < top]
                assert max(w[3]/mm for w in words) < top - 4.9, (title, i)
            page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(temp / f'{number:02}-{i:02}.png')
        print(title, len(pdf), flush=True)
        paths.append(str(path))
        titles.append(title + ' — контрольный пример')
    assert {name: asdict(getattr(project, name)) for name in original} == original
    target = out / 'Проверка_рамок_СО_и_приложений.pdf'
    g.merge_pdfs(paths, str(target), section_titles=titles)
    print(target)


if __name__ == '__main__':
    main()
