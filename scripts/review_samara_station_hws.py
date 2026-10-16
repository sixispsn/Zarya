"""Reproducible local drawing review of the signed Samara calculation."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intake import samara_study
from app.pz.generator import generate_pump_zone_scheme_pdf, generate_spec_pdf
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


def main():
    folder = ROOT / "output/pdf/samara-station-hws"
    folder.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / "tmp/pdfs/samara-pump-hws"
    scratch.mkdir(parents=True, exist_ok=True)
    case = samara_study.load_case()
    draft = dict(answers=deepcopy(case["payload"]["answers"]), documents=[],
                 study=dict(snapshot=case["payload_sha256"]))
    project = samara_study.build(draft, folder, render=False)[0].project
    before = deepcopy(asdict(project))
    pdf = folder / "Самара_Насосная_Т3_Т4.pdf"
    generate_pump_zone_scheme_pdf(project, str(pdf))
    generate_spec_pdf(project, str(folder / "Самара_Спецификация_ИОС2.pdf"))
    for number, svg in enumerate(build_pump_zone_scheme_pages(project), 1):
        (scratch / f"sheet-{number}.svg").write_text(svg)
    assert asdict(project) == before, "Drawing altered calculation data"
    print(pdf)


if __name__ == "__main__":
    main()
