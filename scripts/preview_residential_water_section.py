"""Reproducible read-only Samara cutaway, not a new hydraulic calculation."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cairosvg
from app.intake import samara_study
from app.pz.generator import generate_scheme_result


def main():
    draft=dict(revision=0,answers={},documents=[])
    samara_study.initialize(draft,None)
    with TemporaryDirectory() as tmp:
        p=samara_study.build(draft,tmp,render=False)[0].project
    # Same division as IOS2 orchestration: the existing В2 sheet is separate.
    # The selected consumer profile is read from the request, not supplied by
    # the preview as a hidden replacement for user inputs.
    p=deepcopy(p)
    p.fire.required=False
    p.fire_pumps.required=False
    before=deepcopy(asdict(p))
    result=generate_scheme_result(p)
    assert 'data-residential-water-section=' in result.svg
    assert before==asdict(p)
    out=ROOT/'output/pdf/water-residential-section'
    scratch=ROOT/'tmp/pdfs/water-residential-section'
    out.mkdir(parents=True,exist_ok=True); scratch.mkdir(parents=True,exist_ok=True)
    (scratch/'section.svg').write_text(result.svg,encoding='utf-8')
    target=out/'Самара_В1_Т3_Т4_характерный_разрез.pdf'
    cairosvg.svg2pdf(bytestring=result.svg.encode('utf-8'),write_to=str(target))
    print(target)
    print('\n'.join(result.warnings))


if __name__=='__main__':
    main()
