"""Render two read-only examples through the production water dispatcher."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import asdict, replace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.intake import samara_study
from app.intake.yaml_io import load_request_file
from app.intake.project_builder import build_project
from app.pz.generator import generate_scheme_pdf
from app.pz.water_building_section import water_section_model


def examples():
    # Supplied small-building AR/levels remain unchanged. Central HWS, height
    # and the +4.3 fixture datum are explicit QA assumptions, not decisions
    # backfilled into the user's YAML. This script does not calculate a network.
    request = load_request_file(str(ROOT/'demo/residential_2floors_8apartments.yaml'))
    request.hws_type = 'central'
    request.building_height_m = 6.6
    request.fire_height_m = 4.8
    request.source_data.elev_fixture_m = 4.3
    small = build_project(request)
    small.fire.required = False
    small.metering_detail.inlet_elevation_m = -2.0
    small.document = replace(small.document,sheet_title='В1, Т3, Т4. Характерный разрез',
        object_part='Условно: ГВС, излив +4,30')
    case = samara_study.load_case()
    draft = dict(answers=deepcopy(case['payload']['answers']),documents=[],study=dict(snapshot=case['payload_sha256']))
    with TemporaryDirectory() as tmp:
        samara = samara_study.build(draft,tmp,render=False)[0].project
    samara = deepcopy(samara)
    # Same split as ios2_orchestrator: confirmed V2 has its own existing sheet.
    samara.fire.required = False
    samara.fire_pumps.required = False
    return (('Вода_2_этажа_общий_разрез.pdf',small),('Самара_вода_общий_разрез.pdf',samara))


def main():
    out = ROOT/'output/pdf/water-unified-section'
    out.mkdir(parents=True,exist_ok=True)
    for name,project in examples():
        before = deepcopy(asdict(project))
        generate_scheme_pdf(project,str(out/name))
        assert asdict(project) == before
        print(out/name)
        print(water_section_model(project))


if __name__ == '__main__':
    main()
