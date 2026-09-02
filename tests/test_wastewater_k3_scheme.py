from copy import deepcopy
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.project import GreaseTrapDesign, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_k3_drafting import (
    audit_wastewater_k3_svgs,
    build_wastewater_k3_svgs,
)
from app.pz.wastewater_k3_project_inputs import (
    resolve_wastewater_k3_project_inputs,
)
from app.pz.wastewater_k3_scheme_service import (
    assess_wastewater_k3_scheme_readiness,
    generate_wastewater_k3_scheme,
)
from app.pz.wastewater_scheme_service import (
    assess_wastewater_scheme_readiness,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _k3_project():
    project = deepcopy(build_project(load_request_file(str(DEMO))))
    project.document.cipher = "ZARYA-K3-001-ИОС2"
    project.document.object_name = "Предприятие общественного питания"
    project.document.object_part = "Производственная канализация кухни"
    project.building.floors_above = 1
    project.building.height_m = 3.6
    project.sewage.floor_height_m = 3.6
    project.sewage.basement_floor_elevation_m = -3.2
    project.sewage.discharge_point_k3 = "КК-3"
    project.sewage.k3_max_hourly_m3h = 1.8
    project.sewage.k3_min_hourly_m3h = 0.2
    project.sewage.treatment_required = True
    project.sewage.treatment_type = "жироуловитель"
    project.sewage.treatment_location = "техническое помещение кухни"
    project.sewage.treatment_capacity_lps = 1.0
    project.sewage.treatment_technology = "гравитационное отделение жиров"
    project.grease_trap = GreaseTrapDesign(
        preparation_type="raw",
        seats=200,
        required=True,
        decision_note="Предусмотреть предварительную очистку жиросодержащих стоков.",
    )
    project.sewage.pipes.extend((
        SewerPipeSpec(
            system="K3",
            section_id="К3-Ст1",
            purpose="стояк К3",
            material="ПП",
            standard="ГОСТ 32414-2013",
            outer_diameter_mm=110.0,
            wall_thickness_mm=3.4,
            length_m=4.0,
            nominal_diameter_mm=100,
            from_node="К3-Вент1",
            to_node="К3-Ст1",
            room="технологическая шахта",
            elevation_start_m=3.8,
            elevation_end_m=-0.2,
        ),
        SewerPipeSpec(
            system="K3",
            section_id="К3-Ветв-М1",
            purpose="этажное ответвление К3",
            material="ПП",
            standard="ГОСТ 32414-2013",
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.8,
            length_m=10.0,
            nominal_diameter_mm=50,
            slope_per_mille=30.0,
            from_node="К3-Мой1",
            to_node="К3-Ст1",
            room="М-01 — моечная кухонной посуды",
            elevation_start_m=0.45,
            elevation_end_m=0.15,
        ),
        SewerPipeSpec(
            system="K3",
            section_id="К3-Ветв-Тр1",
            purpose="этажное ответвление К3",
            material="ПП",
            standard="ГОСТ 32414-2013",
            outer_diameter_mm=50.0,
            wall_thickness_mm=1.8,
            length_m=5.0,
            nominal_diameter_mm=50,
            slope_per_mille=30.0,
            from_node="К3-Тр1",
            to_node="К3-Ст1",
            room="М-01 — моечная кухонной посуды",
            elevation_start_m=0.20,
            elevation_end_m=0.05,
        ),
        SewerPipeSpec(
            system="K3",
            section_id="К3-Вып1",
            purpose="выпуск К3",
            material="ПП",
            standard="ГОСТ 32414-2013",
            outer_diameter_mm=110.0,
            wall_thickness_mm=3.4,
            length_m=12.0,
            nominal_diameter_mm=100,
            slope_per_mille=10.0,
            from_node="К3-Ст1",
            to_node="КК-3",
            room="техническое подполье / участок выпуска",
            elevation_start_m=-0.20,
            elevation_end_m=-0.32,
            absolute_elevation_start_m=146.80,
            absolute_elevation_end_m=146.68,
        ),
    ))
    project.sewage.elements.extend((
        SewerElementSpec(
            element_id="К3-Мой1",
            system="K3",
            kind="sink",
            name="Мойка производственная двухсекционная",
            quantity=2,
            typical_quantity=2,
            floor_from=1,
            room_number="М-01",
            room_name="Моечная кухонной посуды",
            elevation_m=0.45,
            dn_mm=50,
            slope_per_mille=30.0,
            section_id="К3-Ветв-М1",
            connects_to="К3-ЖУ1",
            type_mark="по ТХ",
            standard="ТУ изготовителя",
        ),
        SewerElementSpec(
            element_id="К3-ЖУ1",
            system="K3",
            kind="grease_trap",
            name="Жироуловитель",
            quantity=1,
            typical_quantity=1,
            floor_from=1,
            room_number="М-01",
            room_name="Моечная кухонной посуды",
            elevation_m=0.25,
            dn_mm=50,
            slope_per_mille=30.0,
            section_id="К3-Ветв-М1",
            connects_to="К3-Ст1",
            type_mark="Q=1,0 л/с",
            standard="ТУ изготовителя",
        ),
        SewerElementSpec(
            element_id="К3-Тр1",
            system="K3",
            kind="floor_drain",
            name="Трап производственный",
            quantity=1,
            typical_quantity=1,
            floor_from=1,
            room_number="М-01",
            room_name="Моечная кухонной посуды",
            elevation_m=0.20,
            dn_mm=50,
            slope_per_mille=30.0,
            section_id="К3-Ветв-Тр1",
            connects_to="К3-Ст1",
            type_mark="DN50",
            standard="ГОСТ 1811-97",
        ),
        SewerElementSpec(
            element_id="К3-ОтвВ1",
            system="K3",
            kind="elbow",
            name="Отвод канализационный 45°",
            section_id="К3-Ветв-М1",
            connects_to="К3-Ст1",
            dn_mm=50,
            type_mark="DN50; 45°",
            standard="ГОСТ 32414-2013",
        ),
        SewerElementSpec(
            element_id="К3-ТрВ1",
            system="K3",
            kind="tee",
            name="Тройник канализационный косой 45°",
            section_id="К3-Ветв-М1",
            connects_to="К3-Ст1",
            dn_mm=100,
            type_mark="DN100×50; 45°",
            standard="ГОСТ 32414-2013",
        ),
        SewerElementSpec(
            element_id="К3-ОтвВ2",
            system="K3",
            kind="elbow",
            name="Отвод канализационный 45°",
            section_id="К3-Ветв-Тр1",
            connects_to="К3-Ст1",
            dn_mm=50,
            type_mark="DN50; 45°",
            standard="ГОСТ 32414-2013",
        ),
        SewerElementSpec(
            element_id="К3-ТрВ2",
            system="K3",
            kind="tee",
            name="Тройник канализационный косой 45°",
            section_id="К3-Ветв-Тр1",
            connects_to="К3-Ст1",
            dn_mm=100,
            type_mark="DN100×50; 45°",
            standard="ГОСТ 32414-2013",
        ),
        SewerElementSpec(
            element_id="К3-Р1",
            system="K3",
            kind="revision",
            name="Ревизия канализационная",
            floor_from=1,
            elevation_m=1.0,
            dn_mm=100,
            section_id="К3-Ст1",
            connects_to="К3-Ст1",
            type_mark="DN100",
            standard="ГОСТ 32414-2013",
            service_direction="both",
            service_fitting="revision_opening",
            accessible=True,
        ),
        SewerElementSpec(
            element_id="К3-ПМ1",
            system="K3",
            kind="fire_collar",
            name="Муфта противопожарная",
            floor_from=1,
            dn_mm=100,
            section_id="К3-Ст1",
            type_mark="ППМ-110",
            standard="ТУ изготовителя",
        ),
        SewerElementSpec(
            element_id="К3-ОтвСт1",
            system="K3",
            kind="elbow",
            name="Отвод канализационный 45°",
            floor_from=0,
            dn_mm=100,
            section_id="К3-Ст1",
            connects_to="К3-Вып1",
            type_mark="DN100; 45°",
            standard="ГОСТ 32414-2013",
        ),
        SewerElementSpec(
            element_id="К3-ПрНП1",
            system="K3",
            kind="cleanout",
            name="Тройник косой 45° с заглушкой (прочистка)",
            floor_from=0,
            dn_mm=100,
            section_id="К3-Вып1",
            connects_to="К3-Ст1",
            type_mark="DN100; 45°",
            standard="ГОСТ 32414-2013",
            service_direction="downstream",
            service_fitting="wye_45",
            accessible=True,
        ),
        SewerElementSpec(
            element_id="К3-ВыпЭ1",
            system="K3",
            kind="outlet",
            name="Узел выпуска производственной канализации К3",
            floor_from=0,
            dn_mm=100,
            section_id="К3-Вып1",
            connects_to="КК-3",
            type_mark="DN100",
            standard="по узлу ИОС3",
        ),
    ))
    return project


def test_k3_inputs_are_separate_complete_and_registry_backed():
    project = _k3_project()

    inputs = resolve_wastewater_k3_project_inputs(project)

    assert inputs.complete
    assert inputs.characteristic_floors == (1,)
    assert [row.riser_id for row in inputs.risers] == ["К3-Ст1"]
    assert [row.pipe.section_id for row in inputs.risers[0].branches] == [
        "К3-Ветв-М1",
        "К3-Ветв-Тр1",
    ]
    assert inputs.treatment_element_ids == ("К3-ЖУ1",)
    assert inputs.outlet and inputs.outlet.to_node == "КК-3"


def test_k3_vector_pdf_has_floor_basement_and_graphic_audit(tmp_path):
    project = _k3_project()
    inputs = resolve_wastewater_k3_project_inputs(project)
    svgs = build_wastewater_k3_svgs(project, inputs)

    assert len(svgs) == 2
    assert audit_wastewater_k3_svgs(project, inputs, svgs) == ()
    assert 'data-architecture="foundation-right"' in svgs[-1]
    assert "Выпуск К3-Вып1" in svgs[-1]
    joined = "\n".join(svgs)
    assert 'data-k3-treatment-element="К3-ЖУ1"' in joined
    assert 'data-k3-basement-cleanout="К3-ПрНП1"' in joined
    assert 'data-cleanout-axis="collinear"' in joined
    assert 'data-k3-branch-elbow="К3-ОтвВ1"' in joined
    assert 'data-k3-branch-junction="К3-ТрВ1"' in joined
    assert 'data-vector-diameter-sign="true"' in joined
    assert "i=" not in joined

    result = generate_wastewater_k3_scheme(
        project,
        str(tmp_path / "К3.pdf"),
    )

    assert result.ready
    assert result.backend == "registry-k3-gravity-v1-paginated"
    reader = PdfReader(result.output_path)
    assert len(reader.pages) == 2
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "ZARYA-K3-001-ИОС3.СК.К3" in text
    assert "Жироуловитель" in text
    assert "КК-3" in text
    assert all(
        float(page.mediabox.width) * 25.4 / 72 == pytest.approx(841.0, abs=0.02)
        for page in reader.pages
    )


def test_required_k3_treatment_without_registered_equipment_is_status(tmp_path):
    project = _k3_project()
    project.sewage.elements = [
        row for row in project.sewage.elements if row.element_id != "К3-ЖУ1"
    ]
    source = next(
        row for row in project.sewage.elements if row.element_id == "К3-Мой1"
    )
    source.connects_to = "К3-Ст1"

    readiness = assess_wastewater_k3_scheme_readiness(project)
    result = generate_wastewater_k3_scheme(
        project,
        str(tmp_path / "blocked.pdf"),
    )

    assert not readiness.ready
    assert any("не зарегистрирован жироуловитель" in row for row in readiness.reasons)
    assert not result.ready
    assert result.backend == "k3-incomplete-status"
    text = PdfReader(result.output_path).pages[0].extract_text() or ""
    assert "СХЕМА К3" in text
    assert "НЕ СФОРМИРОВАНА" in text


def test_pressure_k3_is_not_masqueraded_as_gravity():
    project = _k3_project()
    outlet = next(
        row for row in project.sewage.pipes if row.section_id == "К3-Вып1"
    )
    outlet.pressure_rated = True
    outlet.pressure_class_bar = 6.0

    readiness = assess_wastewater_k3_scheme_readiness(project)

    assert not readiness.ready
    assert any("схема напорной канализации" in row for row in readiness.reasons)


def test_k3_register_does_not_block_canonical_k1_k2_release():
    project = _k3_project()
    project.building.floors_above = 16
    project.building.height_m = 48.0
    project.sewage.floor_height_m = 3.0

    readiness = assess_wastewater_scheme_readiness(project)

    assert readiness.ready
