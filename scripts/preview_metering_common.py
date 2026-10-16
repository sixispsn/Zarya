"""Current Samara calculation, explicit common-meter design variant for review.

No signed source, meter flow/loss or pump duty is changed. Missing bypass
geometry remains missing; this is not a ready-for-construction package.
"""
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.intake import samara_study
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import build_metering_detail_pages
    from app.pz.water_station_drafting import build_pump_zone_scheme_pages
    ensure_drafting_font_registered()
    with TemporaryDirectory() as tmp:
        draft = dict(revision=0, answers={}, documents=[])
        samara_study.initialize(draft,None)
        baseline = samara_study.build(draft,Path(tmp),render=False)[0].project
        project = deepcopy(baseline)
        project.metering_detail.inlet_metering_mode = 'common'
        project.metering_detail.common_topology = 'gost_g1'
        project.document.object_part = 'Вариант общего ВУ. Проверка компоновки'
        before = asdict(project)
        writer = PdfWriter()
        for title, pages in (
            ('Общий ВУ и два ввода', build_metering_detail_pages(project)),
            ('Насосная В1 и ГВС', build_pump_zone_scheme_pages(project, include_review=True)),
        ):
            writer.add_outline_item(title,len(writer.pages))
            for svg in pages:
                writer.add_page(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0])
        assert asdict(project) == before
        for key,value in asdict(baseline).items():
            if key not in ('document','metering_detail'):
                assert before[key] == value,key
        output = Path('output/pdf/vu-common/Самара_общий_ВУ_и_насосная.pdf')
        output.parent.mkdir(parents=True,exist_ok=True)
        writer.write(output)
        print(output.resolve())
        print(len(writer.pages),'pages; calculation unchanged')


if __name__ == '__main__':
    main()
