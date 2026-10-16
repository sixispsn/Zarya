"""Same Samara control input; new levels are explicit educational assumptions.

Never modifies the saved case or any user's project. Uses the production
presentation adapter, not a separate hand-drawn PDF.
"""
import json
from pathlib import Path

from app.intake.studio_section import section_model
from app.pz.residential_concept_section import generate_concept_section_pdf, build_concept_section_svg, audit_concept_section_svg


def main():
    root = Path(__file__).resolve().parents[1]
    answers = json.loads((root / "output/pdf/studio-section-documents/answers.json").read_text())
    answers.update(section_zero_absolute_m=100,
        section_zero_source_ref="Учебно принято 100,00 м. Не геодезическая отметка объекта.",
        section_k1_start_invert_m=-.65, section_k2_start_invert_m=-.8)
    model = section_model(answers)
    output = root / "output/pdf/section-elevations"
    output.mkdir(parents=True, exist_ok=True)
    (output / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2)+"\n")
    svg = build_concept_section_svg(model)
    assert audit_concept_section_svg(model,svg) == ()
    (output / "section.svg").write_text(svg)
    generate_concept_section_pdf(output / "Схема_К1_К2.pdf", model)
    print(output / "Схема_К1_К2.pdf")


if __name__ == "__main__":
    main()
