import asyncio
from dataclasses import replace
from pathlib import Path

from starlette.datastructures import FormData
from pypdf import PdfReader

from app.analysis.architecture_confirmation import (
    ConfirmedArchitectureSectionInput,
    PdfFloorSectionConfirmation,
    PdfScaleConfirmation,
    PdfSectionCellConfirmation,
    PdfSectionCutConfirmation,
    confirmed_architecture_section_to_mapping,
)
from app.analysis.architecture_import_store import ArchitectureImportStore
from app.analysis.architecture_pdf import PdfPlanPoint
from app.analysis.architecture_wastewater_binding import (
    ConfirmedArchitectureWastewaterBinding,
    ConfirmedReceiverPlacement,
    ConfirmedRiserFloorPlacement,
    architecture_wastewater_binding_from_mapping,
    architecture_wastewater_binding_to_mapping,
    audit_architecture_wastewater_binding,
    build_bound_wastewater_layout,
)
from app.pz.project import (
    Project,
    SewageRiserSpec,
    SewerElementSpec,
    SewerPipeSpec,
)
from app.pz.wastewater_layout import audit_wastewater_layout
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope,
    build_wastewater_structure_svg,
)
from app.intake.project_store import ProjectStore
from app.intake.yaml_io import load_request_file
from tests.test_architecture_pdf import _request as _web_request, _vector_pdf


def _architecture(*, two_floors: bool = False):
    scale = PdfScaleConfirmation(
        PdfPlanPoint(0, 0),
        PdfPlanPoint(100, 0),
        4.0,
    )
    cut = PdfSectionCutConfirmation(
        PdfPlanPoint(0, 50),
        PdfPlanPoint(300, 50),
    )

    def floor(number: int):
        prefix = f"F{number}"
        return PdfFloorSectionConfirmation(
            page_number=number,
            floor=number,
            elevation_m=(number - 1) * 3.0,
            clear_height_m=3.0,
            scale=scale,
            cut=cut,
            cells=(
                PdfSectionCellConfirmation(
                    f"{prefix}-101", 0, 100, "101", "Кухня"
                ),
                PdfSectionCellConfirmation(
                    f"{prefix}-102", 100, 250, "102", "Санузел"
                ),
                PdfSectionCellConfirmation(
                    f"{prefix}-SHAFT", 250, 300, "Ш1", "Шахта", "shaft"
                ),
            ),
        )

    floors = (floor(1), floor(2)) if two_floors else (floor(1),)
    return ConfirmedArchitectureSectionInput(
        plan_id="АР-ПДФ-01",
        cut_id="1-1",
        source_name="Планы АР.pdf",
        source_sha256="a" * 64,
        floors=floors,
    )


def _binding(*, two_floors: bool = False):
    risers = [
        ConfirmedRiserFloorPlacement(
            "R-K1-1-F1",
            "К1-Ст1",
            "K1",
            1,
            "F1-SHAFT",
            11.0,
            100,
            "АР, лист 1; подтверждено проектировщиком",
        )
    ]
    if two_floors:
        risers.append(ConfirmedRiserFloorPlacement(
            "R-K1-1-F2",
            "К1-Ст1",
            "K1",
            2,
            "F2-SHAFT",
            11.0,
            100,
            "АР, лист 2; подтверждено проектировщиком",
        ))
    receivers = (
        ConfirmedReceiverPlacement(
            "P-SINK-F1",
            "К1-Мой1",
            "sink",
            "K1",
            1,
            "F1-102",
            6.0,
            0.5,
            1,
            50,
            "К1-Ст1",
            "АР, лист 1, помещение 101",
        ),
        ConfirmedReceiverPlacement(
            "P-WC-F1",
            "К1-Ун1",
            "toilet",
            "K1",
            1,
            "F1-102",
            9.5,
            0.15,
            1,
            100,
            "К1-Ст1",
            "АР, лист 1, помещение 102",
        ),
    )
    return ConfirmedArchitectureWastewaterBinding(
        plan_id="АР-ПДФ-01",
        cut_id="1-1",
        architecture_source_sha256="a" * 64,
        risers=tuple(risers),
        receivers=receivers,
    )


def _project():
    project = Project()
    project.building.floors_above = 1
    project.sewage.risers = [SewageRiserSpec(riser_id="К1-Ст1")]
    project.sewage.pipes = [
        SewerPipeSpec(
            system="K1",
            section_id="К1-Ст1",
            purpose="стояк К1",
            outer_diameter_mm=110,
            wall_thickness_mm=3.4,
            from_node="К1-Вент1",
            to_node="К1-Ст1",
            elevation_start_m=3.0,
            elevation_end_m=0.0,
        ),
        SewerPipeSpec(
            system="K1",
            section_id="К1-Ветв1",
            purpose="этажное ответвление К1",
            nominal_diameter_mm=100,
            outer_diameter_mm=110,
            wall_thickness_mm=3.4,
            from_node="К1-Мой1",
            to_node="К1-Ст1",
            slope_per_mille=20,
            elevation_start_m=0.5,
            elevation_end_m=0.05,
        ),
        SewerPipeSpec(
            system="K1",
            section_id="К1-Вып1",
            purpose="выпуск К1",
            outer_diameter_mm=160,
            wall_thickness_mm=4.9,
            from_node="К1-Ст1",
            to_node="КК-1",
            slope_per_mille=8,
            elevation_start_m=-0.2,
            elevation_end_m=-0.3,
            absolute_elevation_start_m=100.0,
            absolute_elevation_end_m=99.9,
        ),
    ]
    project.sewage.elements = [
        SewerElementSpec(
            element_id="К1-Мой1",
            system="K1",
            kind="sink",
            typical_quantity=1,
            floor_from=1,
            room_number="102",
            room_name="Санузел",
            elevation_m=0.5,
            dn_mm=50,
            section_id="К1-Ветв1",
            connects_to="К1-Ун1",
        ),
        SewerElementSpec(
            element_id="К1-Ун1",
            system="K1",
            kind="toilet",
            typical_quantity=1,
            floor_from=1,
            room_number="102",
            room_name="Санузел",
            elevation_m=0.15,
            dn_mm=100,
            section_id="К1-Ветв1",
            connects_to="К1-Ст1",
        ),
        SewerElementSpec(
            element_id="К1-ВыпЭ1",
            system="K1",
            kind="outlet",
            floor_from=0,
            section_id="К1-Вып1",
            connects_to="КК-1",
        ),
    ]
    return project


def test_confirmed_binding_roundtrip_is_lossless():
    value = _binding(two_floors=True)

    restored = architecture_wastewater_binding_from_mapping(
        architecture_wastewater_binding_to_mapping(value)
    )

    assert restored == value


def test_binding_accepts_only_explicit_points_inside_rooms_and_shafts():
    issues = audit_architecture_wastewater_binding(
        _architecture(),
        _binding(),
    )

    assert issues == ()

    wrong_shaft = replace(
        _binding().risers[0],
        shaft_cell_id="F1-102",
        station_m=8.0,
    )
    wrong_wc = replace(_binding().receivers[1], dn_mm=50, station_m=12.5)
    broken = replace(
        _binding(),
        risers=(wrong_shaft,),
        receivers=(_binding().receivers[0], wrong_wc),
    )
    codes = {
        row.code
        for row in audit_architecture_wastewater_binding(
            _architecture(),
            broken,
        )
    }

    assert "riser.shaft" in codes
    assert "receiver.dn" in codes
    assert "receiver.station" in codes


def test_riser_offset_must_be_confirmed_on_the_upper_floor():
    architecture = _architecture(two_floors=True)
    binding = _binding(two_floors=True)
    shifted = replace(binding.risers[1], station_m=10.5)
    binding = replace(binding, risers=(binding.risers[0], shifted))

    assert "riser.offset_unconfirmed" in {
        row.code
        for row in audit_architecture_wastewater_binding(architecture, binding)
    }

    confirmed = replace(shifted, offset_from_below_confirmed=True)
    binding = replace(binding, risers=(binding.risers[0], confirmed))
    assert "riser.offset_unconfirmed" not in {
        row.code
        for row in audit_architecture_wastewater_binding(architecture, binding)
    }


def test_binding_places_project_graph_without_inventing_rooms_or_edges():
    architecture = _architecture()
    binding = _binding()
    project = _project()

    layout = build_bound_wastewater_layout(architecture, binding, project)

    assert {row.element_id for row in layout.elements} == {"К1-Мой1", "К1-Ун1"}
    assert [row.section_id for row in layout.routes] == ["К1-Ветв1", "К1-Ст1"]
    assert [point.x for point in layout.routes[0].points] == [380.0, 555.0, 630.0]
    assert layout.routes[0].points[0] == layout.nodes[0].point
    assert layout.routes[0].points[-1] == layout.nodes[1].point
    assert audit_wastewater_layout(project, layout).ready

    svg = build_wastewater_structure_svg(
        project,
        layout,
        scope=WastewaterStructureScope.FULL_FLOOR_STACK,
    )
    assert 'data-bound-section="К1-Ветв1"' in svg
    assert 'data-bound-section="К1-Ст1"' in svg
    assert 'data-bound-element="К1-Мой1"' in svg
    assert 'data-ugo="sink"' in svg
    assert svg.count('data-ugo="trap"') == 1
    assert "№102 Санузел" in svg


def test_saved_project_link_gates_control_svg_by_exact_yaml_version(
    tmp_path,
    monkeypatch,
):
    from app.web import architecture_import as web

    architecture_store = ArchitectureImportStore(tmp_path / "architecture")
    project_store = ProjectStore(root=str(tmp_path / "projects"))
    monkeypatch.setattr(web, "_STORE", architecture_store)
    monkeypatch.setattr(web, "_PROJECT_STORE", project_store)
    monkeypatch.setattr(web, "_EXPORT_ROOT", str(tmp_path / "exports"))

    import_id = architecture_store.create("Планы АР.pdf", _vector_pdf())
    survey = architecture_store.survey(import_id)
    architecture = replace(_architecture(), source_sha256=survey.sha256)
    base_binding = _binding()
    binding = replace(
        base_binding,
        architecture_source_sha256=survey.sha256,
        receivers=(base_binding.receivers[0],),
    )
    architecture_store.save_confirmations(
        import_id,
        confirmed_architecture_section_to_mapping(architecture),
    )
    architecture_store.save_wastewater_binding(
        import_id,
        architecture_wastewater_binding_to_mapping(binding),
    )
    request_dto = load_request_file(str(
        Path(__file__).parents[1] / "demo" / "demo_project.yaml"
    ))
    project_id = project_store.save(request_dto)

    link_request = _web_request(
        f"/wizard/architecture/{import_id}/wastewater/project",
        "POST",
    )
    link_request._form = FormData([("project_id", project_id)])
    linked = asyncio.run(
        web.architecture_link_wastewater_project(link_request, import_id)
    )

    assert linked.status_code == 303
    assert architecture_store.load_project_link(import_id)["project_id"] == project_id
    workspace = web.architecture_workspace(
        _web_request(f"/wizard/architecture/{import_id}"),
        import_id,
    )
    body = workspace.body.decode("utf-8")
    assert "Скачать принципиальную схему PDF" in body
    assert "Контроль привязки по АР · SVG" in body
    assert "Инженерный граф не связан" not in body

    control = web.architecture_wastewater_control_svg(import_id)
    assert control.status_code == 200
    assert control.media_type == "image/svg+xml"
    assert 'data-bound-section="К1-Ветв-Кух1"' in control.body.decode("utf-8")

    pdf_response = web.architecture_wastewater_scheme_pdf(import_id)
    assert pdf_response.status_code == 200
    assert pdf_response.media_type == "application/pdf"
    assert Path(pdf_response.path).is_file()
    assert len(PdfReader(pdf_response.path).pages) == 2

    request_dto.apartments += 1
    project_store.save(request_dto, project_id=project_id)
    changed = web.architecture_workspace(
        _web_request(f"/wizard/architecture/{import_id}"),
        import_id,
    ).body.decode("utf-8")
    assert "Проект изменён после подтверждения связи" in changed
    assert "Скачать новую схему PDF" not in changed
    assert web.architecture_wastewater_control_svg(import_id).status_code == 422
    assert web.architecture_wastewater_scheme_pdf(import_id).status_code == 422
