"""QA example via the same Studio -> request -> generator path, not Samara edits."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace


def main():
    with TemporaryDirectory(prefix='zarya-hws-stage-p-') as work:
        os.environ.update(ZARYA_PILOT_ENABLED='0', ZARYA_STUDIO_ENABLED='1',
                          ZARYA_STUDIO_DIR=work+'/studio', ZARYA_PROJECTS_DIR=work+'/projects')
        from fastapi.testclient import TestClient
        from app.main import app
        from app.intake.studio_store import StudioStore
        from app.intake.studio_intake import build_handoff_request
        from app.intake.project_builder import build_project
        from app.pz.ios2_orchestrator import design_ios2
        from app.pz.generator import generate_pz_pdf, generate_balance_pdf
        from app.pz.hws_stage_p import stage_p_circulation
        from pypdf import PdfWriter
        with TestClient(app) as client:
            client.headers['X-Zarya-Studio']='1'
            draft=client.post('/studio/api/draft').json()
            response=client.post('/studio/api/calculate',json=dict(revision=draft['revision'],answers=dict(
                building_purpose='residential',residents=20,apartments=8,floors=2,
                building_height_m=6.6,fire_height_m=4.8,hws_type='central',
                consumer_code='residential_full_bath', hws_stage_p_enabled='yes',
                hws_water_towel_rails='yes',hws_circulation_zones='1',hws_delta_t_c=5,
                hws_loss_percent=35,
            )))
            response.raise_for_status()
            draft=StudioStore(work+'/studio').load(draft['project_id'])
            project=design_ios2(build_project(build_handoff_request(draft)),
                                output_dir=work,render_documents=False).project
            project.document=replace(project.document,
                object_name='Проверочный пример укрупнённого расчёта ГВС · 20 жителей',
                review_notes=('Проверка нового режима стадии П. 35% и Δt=5 °C заданы только для этого примера. '
                              'Не полный комплект к выпуску: гидравлика, оборудование и прочие исходные не заданы.',))
            generate_pz_pdf(project,work+'/pz.pdf')
            generate_balance_pdf(project,work+'/balance.pdf')
            out=Path('output/pdf/hws_stage_p_preview.pdf');out.parent.mkdir(parents=True,exist_ok=True)
            pdf=PdfWriter();pdf.append(work+'/pz.pdf');pdf.append(work+'/balance.pdf')
            with out.open('wb') as f: pdf.write(f)
            print(out.resolve())
            print(stage_p_circulation(project))


if __name__ == '__main__':
    main()
