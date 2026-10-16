"""Two explicit review cases; no invented passport/model for a real project."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader, PdfWriter
from app.calc.water_meters import MeterInput, calculate_meters
from app.pz.flows_bridge import meters_from_calc
from app.pz.generator import generate_metering_scheme_pdf, generate_spec_pdf
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_pipes import MeteringPipeSection
from app.pz.project import Project, FireSystem, FlowsData, BuildingPurpose


def review_project(inputs_count=1):
    p = Project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    p.document.object_name = "Жилой дом. Узлы учёта воды"
    p.document.object_part = "Один ввод" if inputs_count == 1 else "Два ввода; В2 до учёта"
    p.source.inputs_count = inputs_count
    p.source.water_use_period_h = 24
    p.flows = FlowsData(q_sec_c=1.1, q_day_c=72, q_sec_h=.6, q_day_h=36)
    p.meters = meters_from_calc(calculate_meters(MeterInput(
        inputs_count=inputs_count, q_sec_c=1.1, q_day_c=72,
        q_sec_h=.6, q_day_h=36,
    )))
    # These are drawing inputs of the review case, not a hydraulic selection.
    p.metering_detail = MeteringDetailData(
        room_number="001", room_name="Водомерная", inlet_dn=50,
        bypass_dn=50 if inputs_count == 1 else None, inlet_elevation_m=-1.5,
        fire_branch_dn=50 if inputs_count == 2 else None,
    )
    if inputs_count == 2:
        p.fire = FireSystem(required=True, network_topology="pre_meter_branch",
                            topology_basis="Заданная схема контрольного примера",
                            branch_electric_valves=True)
    return p


def mixed_pipe_sections():
    """Explicit review geometry, not project defaults or an approved assembly."""
    from app.data.pipe_catalog import STEEL_VGP_ORDINARY
    def steel(dn):
        size = STEEL_VGP_ORDINARY[dn]
        return MeteringPipeSection(material="steel", series="ВГП обыкновенная",
            nominal_dn=dn, outer_diameter_mm=size.outer_mm, wall_thickness_mm=size.wall_mm,
            joining="threaded", geometry_source="ГОСТ 3262-75, таблица 1")
    return {"inlet": steel(50), "before_meter": steel(32), "after_meter": steel(32),
            "bypass": steel(50),
            "outlet": MeteringPipeSection(material="ppr", series="VALTEC VTp.700.FB20",
                system_id="valtec_ppr",
                outer_diameter_mm=63, wall_thickness_mm=8.6, joining="socket_fusion",
                geometry_source="ПС 47472, раздел 4; PPR-FIBER-PN20-0824.pdf, стр. 1")}


def catalogue_review_project():
    """Explicit alternative for review only; never substitute in saved projects."""
    from app.data.metering_products import get_metering_catalogue
    project = review_project()
    detail = project.metering_detail
    detail.catalogue_revision = get_metering_catalogue().revision
    detail.catalogue_items = {
        "meter": "decast-vskm90-dg-dn32", "inlet_valve": "valtec-vt214-dn50",
        "meter_valves": "valtec-vt214-dn32", "filter": "valtec-vt192-dn32",
        "bypass_valve": "valtec-vt214-dn50", "check_valve": "itap-europa100-g-dn50",
        "meter_connections": "decast-vskm90-kit-dn32",
    }
    detail.design_pressure_bar, detail.water_temperature_c = 6, 25
    detail.pipe_sections = mixed_pipe_sections()
    detail.pipe_sections["outlet"] = MeteringPipeSection(
        material="ppr", series="PRO AQUA PA10018, SDR 6", system_id="proaqua_ppr",
        outer_diameter_mm=63, wall_thickness_mm=10.5, joining="socket_fusion",
        geometry_source="PRO AQUA PP-R 2026, PDF стр. 42, PA10018")
    detail.support_pipe_section = "inlet"
    detail.connection_items = {"check_valve_out": "proaqua-pa22524p"}
    detail.connection_thread_items = {"check_valve_out": "valtec-vtr582-0009"}
    detail.reducer_items = {"reducer_in": "valtec-vtr580-0907", "reducer_out": "valtec-vtr580-0907"}
    return project


def options_review_project():
    """Explicit wishes for QA; no claim that these additions are selected."""
    project = review_project()
    project.metering_detail.enhancements = {
        "technology": "ultrasonic", "telemetry": "nb_iot",
        "leak_monitoring": "requested", "tamper_monitoring": "requested",
        "valve_feedback": "requested", "assembly": "factory_module",
        "magnetic_filter": "requested", "power": "battery",
    }
    return project


if __name__ == "__main__":
    with_catalogue = "--catalogue" in sys.argv
    with_options = "--options" in sys.argv
    with_mounting = "--mounting" in sys.argv
    if with_mounting:
        with_catalogue = True
    output = Path("output/pdf/Водомерный_узел_итоговая_проверка.pdf" if with_mounting else
                  "output/pdf/Водомерный_узел_с_опциями.pdf" if with_options else
                  "output/pdf/Водомерный_узел_с_каталогом.pdf" if with_catalogue else
                  "output/pdf/Водомерный_узел_ИОС2_приложение_Г.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    with TemporaryDirectory() as temp:
        for count in ((1,) if with_catalogue or with_options else (1,2)):
            path = Path(temp) / f"case-{count}.pdf"
            project = options_review_project() if with_options else catalogue_review_project() if with_catalogue else review_project(count)
            project.metering_detail.mounting.enabled = with_mounting
            generate_metering_scheme_pdf(project, str(path))
            writer.append(PdfReader(path))
        with output.open("wb") as stream:
            writer.write(stream)
    print(output.resolve())
    if "--specification" in sys.argv:
        specification = Path("output/pdf/Спецификация_ВУ_с_опциями.pdf" if with_options else "output/pdf/Спецификация_водоснабжения_с_ВУ.pdf")
        project = options_review_project() if with_options else catalogue_review_project() if with_catalogue else review_project()
        generate_spec_pdf(project, str(specification))
        print(specification.resolve())
