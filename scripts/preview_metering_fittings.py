"""Size/modern-options regression cases; never defaults for a real project."""
from io import BytesIO
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.preview_metering_flanged import flanged_review_project


def review(dn):
    p = flanged_review_project(dn)
    d = p.metering_detail
    d.catalogue_items.pop("filter")
    d.enhancements = {"magnetic_filter":"vodopribor_fmf_replace", "telemetry":"saures_r7",
                      "leak_monitoring":"saures_nbiot_point"}
    d.service_selection_mode = "catalogue_proposal"
    d.gauge_pressure_mode = "variable"
    if dn == 100:
        d.fitting_items = {"bypass_start":"vodopribor-tee-dn100x100",
                           "bypass_end":"vodopribor-tee-dn100x100"}
    p.document.object_name = f"Размерная проверка ВУ DN{dn}, ФМФ и диспетчеризация"
    return p


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import layout_contents
    ensure_drafting_font_registered()
    writer = PdfWriter()
    for dn in (100,250):
        project = review(dn)
        pages = layout_contents(project)
        for i, content in enumerate(pages,1):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                   '<rect width="420" height="297" fill="white"/>'+content+_frame(project,i,len(pages))+'</svg>')
            writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    output = Path("output/pdf/ВУ_фасонина_и_современные_опции.pdf")
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)
    print(output.resolve())


if __name__ == "__main__":
    main()
