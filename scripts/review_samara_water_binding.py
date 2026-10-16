"""Render the signed Samara example through the real V1/spec generators.

No frozen calculation, legacy HTML or user project is changed.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intake import samara_study
from app.pz.generator import generate_scheme_pdf, generate_spec_pdf
from app.pz.scheme import build_scheme
from app.pz.water_pipe_binding import bind_v1_pipes


def main():
    folder = ROOT / "output/pdf/samara-water-v1"
    folder.mkdir(parents=True, exist_ok=True)
    case = samara_study.load_case()
    draft = dict(answers=deepcopy(case["payload"]["answers"]), documents=[],
                 study=dict(snapshot=case["payload_sha256"]))
    bundle, fingerprint = samara_study.build(draft, folder, render=False)
    project = bundle.project
    before = deepcopy(asdict(project))
    drawing = deepcopy(project)
    # Same separation as ios2_orchestrator: V2 has its own sheets.
    drawing.fire.required = False
    drawing.fire_pumps.required = False
    generate_scheme_pdf(drawing, str(folder / "Схема_В1_Самара.pdf"))
    generate_spec_pdf(project, str(folder / "Спецификация_ИОС2_Самара.pdf"))
    assert asdict(project) == before, "Presentation must not alter calculation inputs/results"
    report = dict(snapshot=fingerprint,
                  geometry={k: asdict(v) for k, v in bind_v1_pipes(project).items()},
                  flows=asdict(project.flows), source=asdict(project.source),
                  warnings=build_scheme(drawing).warnings)
    (folder / "binding-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(folder)


if __name__ == "__main__":
    main()
