"""Export the approval-only Samara В1 fragment; never mutate case or dispatcher."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import cairosvg
from app.intake import samara_study
from app.pz.water_floor_fragment import build_water_floor_fragment


def main():
    case = samara_study.load_case()
    draft = dict(answers=deepcopy(case['payload']['answers']),documents=[],
                 study=dict(snapshot=case['payload_sha256']))
    with TemporaryDirectory() as tmp:
        project = samara_study.build(draft,tmp,render=False)[0].project
    before = deepcopy(asdict(project))
    result = build_water_floor_fragment(project,profile="residential_full_bath")
    assert asdict(project) == before
    out = ROOT/'output/pdf/water-floor-fragment'
    tmp = ROOT/'tmp/pdfs/water-floor-fragment'
    out.mkdir(parents=True,exist_ok=True)
    tmp.mkdir(parents=True,exist_ok=True)
    (tmp/'fragment.svg').write_text(result.svg,encoding='utf-8')
    pdf = out/'В1_этаж_и_подвал_фрагмент.pdf'
    cairosvg.svg2pdf(bytestring=result.svg.encode('utf-8'),write_to=str(pdf))
    print(pdf)
    for warning in result.warnings:
        print(warning)


if __name__ == '__main__':
    main()
