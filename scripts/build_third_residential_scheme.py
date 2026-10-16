"""Generate the third residential K1/K2 section after legacy parity checks."""
import argparse
import os
from pathlib import Path
import shutil

from app.architecture.residential_section_case import load_residential_section_case
from app.pz.residential_case_section import generate_residential_case_pdf


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=root/'demo/residential_3floors_accessible_roof.json')
    parser.add_argument('--output', type=Path, default=root/'output/pdf/Трёхэтажный_дом_К1_К2_принципиальная.pdf')
    parser.add_argument('--node', default=os.environ.get('NODE_BINARY') or shutil.which('node'))
    args = parser.parse_args()
    if not args.node:
        parser.error('Node is required to verify the actual legacy calculator before PDF export')
    case = load_residential_section_case(args.case)
    print(generate_residential_case_pdf(args.output, case, node=args.node, root=root))
    print(f'{len(case.drainage_paths())} source paths; legacy parity verified; release_ready={case.release_ready}')


if __name__ == '__main__':
    main()
