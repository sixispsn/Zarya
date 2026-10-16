"""Explicit QA selections; never modify the signed Samara study or its hydraulics."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.intake import samara_study
    from app.pz.metering_supports import studio_supports
    from app.pz.metering_support_drawing import support_contents
    from app.pz.metering_detail import drawing_state, _frame
    from app.pz.metering_layout import build_metering_layout, layout_contents
    from app.pz.generator import generate_metering_scheme_pdf
    from app.pz.drafting_font import ensure_drafting_font_registered
    from scripts.preview_metering_detail import catalogue_review_project
    from scripts.preview_metering_service_matrix import review_case
    ensure_drafting_font_registered()
    out=Path('output/pdf/vu-supports'); out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as tmp:
        draft=dict(revision=0,answers={},documents=[])
        samara_study.initialize(draft,None)
        baseline=samara_study.build(draft,Path(tmp))[0].project
        p=deepcopy(baseline)
        p.document.object_part='Проверка опор; вариант компоновки, не рабочая привязка'
        p.metering_detail.mounting.supports=studio_supports(dict(
            vu_support_inlet='termoclip-09105002',vu_support_outlet='termoclip-09105002'))
        for r in p.metering_detail.mounting.supports.values():
            r['basis']='Явный QA-вариант Самары: 1 консоль до и 1 после каждого ВУ; нагрузки и стены неизвестны. Не исходное решение проекта.'
        path=out/'Самара_ВУ_проверка_опор.pdf'
        generate_metering_scheme_pdf(p,str(path))
        from dataclasses import asdict
        after,before=asdict(p),asdict(baseline)
        for key in before:
            if key not in ('metering_detail','document'):
                assert after[key]==before[key], key
        print(path.resolve())
        writer=PdfWriter()
        cases=[('ОСВУ-1 DN50 - горизонтальная труба',catalogue_review_project())]
        cases += [('Консоли - '+label,review_case(Path(tmp),orient,filter_)) for orient,filter_,label in (
            ('vertical_up','valtec_vt386','поток вверх'),('vertical_down','valtec_vt192_vtr090','поток вниз'))]
        for index,(title,q) in enumerate(cases):
            q.document.object_name=title
            q.document.object_part='Проверка генератора, не монтажный проект'
            q.metering_detail.mounting.supports=studio_supports(dict(
                vu_support_inlet='kromber-osvu1' if index==0 else 'termoclip-09105002',
                vu_support_outlet='termoclip-09105002',vu_support_height_mm=600))
            bodies=support_contents(q,drawing_state(q),build_metering_layout(q))
            writer.add_outline_item(title,len(writer.pages))
            for j,body in enumerate(bodies,1):
                svg=('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                     '<rect width="420" height="297" fill="white"/>'+body+_frame(q,j,len(bodies))+'</svg>')
                writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
        path=out/'Опоры_ВУ_три_компоновки.pdf'
        with path.open('wb') as f: writer.write(f)
        print(path.resolve(),len(writer.pages),'pages')


if __name__=='__main__':
    main()
