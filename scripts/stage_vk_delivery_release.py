"""Stage only reviewed water delivery/HWS and horizontal K1 files over live code."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

RELEASE = '20261007-vk-delivery'
BASE = '20261005-section-elevations'
FILES = '''
app/api/pumps.py
app/calc/hws_circulation.py
app/calc/hws_stage_p.py
app/calc/pumps.py
app/calc/sewage_horizontal.py
app/calc/v1_hydraulics.py
app/calc/water_demand.py
app/data/booster_controls.py
app/data/pipe_catalog.py
app/intake/project_builder.py
app/intake/request_dto.py
app/intake/samara_study.py
app/intake/studio_hws.py
app/intake/studio_intake.py
app/intake/studio_project.py
app/intake/studio_section.py
app/intake/yaml_io.py
app/normative/audit_matrix.py
app/pz/aux_schemes.py
app/pz/building_cutaway.py
app/pz/compliance.py
app/pz/generator.py
app/pz/hws_building_drafting.py
app/pz/hws_presentation.py
app/pz/hws_stage_p.py
app/pz/impact.py
app/pz/ios2_orchestrator.py
app/pz/project.py
app/pz/residential_case_section.py
app/pz/residential_concept_section.py
app/pz/scheme.py
app/pz/section_construction.py
app/pz/section_main_hydraulics.py
app/pz/small_residential_calculation.py
app/pz/small_residential_calculation_pdf.py
app/pz/small_residential_section.py
app/pz/spec.py
app/pz/templates/frame.css
app/pz/templates/hws_description.html
app/pz/templates/pump_table.html
app/pz/templates/spec_table.html
app/pz/templates/subitems_public.html
app/pz/templates/subitems_residential.html
app/pz/templates/t3_hydraulic_table.html
app/pz/templates/wastewater_calculation_body.html
app/pz/templates/wastewater_pz_body.html
app/pz/templates/wastewater_scheme_body.html
app/pz/templates/water_materials.html
app/pz/templates/water_pressure_review.html
app/pz/wastewater_diagnostics.py
app/pz/wastewater_gost.py
app/pz/wastewater_graphic_exports.py
app/pz/wastewater_presentation.py
app/pz/wastewater_scheme.py
app/pz/water_apartment_assembly.py
app/pz/water_building_section.py
app/pz/water_control_review.py
app/pz/water_document_binding.py
app/pz/water_floor_fragment.py
app/pz/water_pipe_binding.py
app/pz/water_regulation_plan.py
app/pz/water_residential_section.py
app/pz/water_scheme_delivery.py
app/pz/water_static_review.py
app/pz/water_station_drafting.py
app/schemas/hws_circulation.py
app/schemas/pumps.py
app/web/static/studio.js
app/web/static/studio_configurator.js
app/web/studio.py
app/web/templates/studio.html
app/web/wizard.py
demo/samara_section_3_2.basis.json
demo/samara_station_review.json
demo/samara_water_review_assumptions.json
legacy/approved_functions.js
legacy/archive/sp30_calculator.pre-2026-09-21.html
legacy/circulation_inputs.html
legacy/sp30_calculator.html
'''.split()


def main():
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    assert not a.output.exists();a.output.mkdir(parents=True)
    manifest={}
    for name in FILES:
        data=(root/name).read_bytes();base=a.baseline/name
        assert not base.exists() or base.read_bytes()!=data, name
        dest=a.output/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest[name]=dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None)
    assert manifest['legacy/archive/sp30_calculator.pre-2026-09-21.html']['sha256']=='ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788'
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    deploy=a.output/'deploy';deploy.mkdir()
    (deploy/'Dockerfile').write_text(f'FROM zarya-release:{BASE}\nUSER root\n'
        f'ENV ZARYA_BUILD_COMMIT={RELEASE}\nCOPY app/ /app/app/\nCOPY demo/ /app/demo/\nCOPY legacy/ /app/legacy/\n'
        'RUN chmod -R a+rX /app/app /app/demo /app/legacy\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.samara_study import load_case; assert load_case()"\n')
    (deploy/'release.override.yaml').write_text(f'services:\n  app:\n    image: zarya-release:{RELEASE}\n'
        f'    environment:\n      ZARYA_BUILD_COMMIT: {RELEASE}\n')
    activation=(root/'deploy/activate-studio-ios2.sh').read_text().replace('20261005-studio-ios2',RELEASE).replace(
        '20261005-samara-vk',BASE).replace('restored-pre-studio','restored-pre-vk-delivery')
    (deploy/'activate.sh').write_text(activation)
    scripts=a.output/'scripts';scripts.mkdir()
    for name in ('verify_backup_restore.py','verify_pilot_container.py','verify_vk_delivery_release.py',
                 'check_water_studio_delivery.py','release_tree_snapshot.py'):
        shutil.copyfile(root/'scripts'/name,scripts/name)
    print(json.dumps(dict(release=RELEASE,files=len(manifest),output=str(a.output))))


if __name__=='__main__': main()
