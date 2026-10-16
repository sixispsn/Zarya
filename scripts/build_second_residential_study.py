"""Build the second house's principle SECTION; plan markup is debug-only."""
import argparse
from pathlib import Path

from app.architecture.residential_plan_study import load_plan_study
from app.pz.residential_plan_study_pdf import generate_plan_study_pdf
from app.pz.residential_plan_section import generate_plan_section_pdf


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home()/"Downloads/1677505735_list-1.jpg")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-debug", action="store_true", help="Internal source markup, not the delivered drawing")
    args = parser.parse_args()
    study = load_plan_study(root/"demo/residential_second_layout.study.json")
    filename = "Второй_дом_разметка_К1_и_подвала.pdf" if args.plan_debug else "Второй_дом_принципиальная_схема_К1.pdf"
    output = args.output or root/"output/pdf"/filename
    print(generate_plan_study_pdf(output, study, args.source) if args.plan_debug else generate_plan_section_pdf(output, study))
    print(f"Connectivity: {len(study.paths())} source paths, {len(study.groups)} stacks, {len(study.routes)} separate outlets")


if __name__ == "__main__":
    main()
