"""Reproducible geometry checks, not a design demand for a residential building.

Every DN is selected by the unchanged hydraulic calculator from explicit test
flows. These inputs are deliberately synthetic, never project defaults.
"""
from pathlib import Path
from io import BytesIO
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calc.water_meters import MeterInput, calculate_meters
from app.data.water_meters import WATER_METERS
from app.data.metering_products import get_metering_catalogue
from app.pz.flows_bridge import meters_from_calc
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.project import FlowsData
from scripts.preview_metering_detail import review_project


def flanged_review_project(dn=250):
    p = review_project()
    index = next(i for i, m in enumerate(WATER_METERS) if m.d_mm == dn)
    average = (WATER_METERS[index-1].q_expl + WATER_METERS[index].q_expl) / 2
    q = average * 1.2 / 3.6
    p.flows = FlowsData(q_sec_c=q, q_day_c=average*24, q_sec_h=.6, q_day_h=36)
    p.meters = meters_from_calc(calculate_meters(MeterInput(
        q_sec_c=q, q_day_c=average*24, q_sec_h=.6, q_day_h=36)))
    assert p.meters.cold_meter_dn == dn, "Geometry fixture must not override a hydraulic selection"
    d = p.metering_detail = MeteringDetailData(
        inlet_dn=dn, bypass_dn=dn, inlet_elevation_m=-1.5,
        catalogue_revision=get_metering_catalogue().revision,
        design_pressure_bar=6, water_temperature_c=20,
        meter_selection_mode="catalogue_proposal", meter_mounting="horizontal_dial_up")
    d.catalogue_items = {
        "inlet_valve": f"adl-kr20-pn16-dn{dn}",
        "meter_valves": f"adl-kr20-pn16-dn{dn}",
        "filter": f"adl-is16-dn{dn}",
        "check_valve": f"ridan-nvd402r-dn{dn}",
        "bypass_valve": f"adl-kr20-pn16-dn{dn}",
    }
    d.mounting.enabled = True
    d.mounting.scale = 20 if dn >= 200 else 10
    p.document.object_name = f"Размерная проверка каталога ВУ DN{dn}"
    p.document.object_part = "Контроль геометрии; не проект жилого дома"
    return p


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import layout_contents
    ensure_drafting_font_registered()
    writer = PdfWriter()
    for dn in (65, 250):
        project = flanged_review_project(dn)
        contents = layout_contents(project)
        for i, content in enumerate(contents, 1):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                   '<rect width="420" height="297" fill="white"/>' + content + _frame(project, i, len(contents)) + '</svg>')
            writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    output = Path("output/pdf/ВУ_DN65_DN250_проверка_каталога.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)
    print(output.resolve())


if __name__ == "__main__":
    main()
