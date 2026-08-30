from copy import deepcopy
from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.project import SewerElementSpec
from app.pz.wastewater_sp30 import audit_wastewater_sp30


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_demo_preserves_revision_schedule_and_confirms_all_lower_turn_access():
    result = audit_wastewater_sp30(_project())
    assert result.ready
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "логика1.pdf" in result.warnings[0]
    assert "п. 18.4" in result.warnings[0]
    assert result.revision_floors["К1-Ст1"] == [1, 4, 7, 10, 13, 16]
    assert result.revision_floors["К1-Ст2"] == [1, 4, 7, 10, 13, 16]
    assert any("18.30" in row for row in result.notes)


def test_revision_gap_over_three_floors_is_rejected():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if not (
            row.kind == "revision"
            and row.section_id == "К1-Ст1"
            and row.floor_from in {4, 7}
        )
    ]
    result = audit_wastewater_sp30(project)
    assert any("этажах 1 и 10" in row for row in result.errors)


def test_k2_turn_access_can_be_confirmed_by_revisions_without_wye_cleanouts():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if not (row.system == "K2" and row.kind == "cleanout")
    ]
    for index in (1, 2):
        project.sewage.elements.append(SewerElementSpec(
            element_id=f"К2-Р{index}-1",
            system="K2",
            kind="revision",
            name="Ревизия внутреннего водостока",
            floor_from=1,
            dn_mm=100,
            section_id=f"К2-Ст{index}",
            service_direction="downstream",
            service_fitting="revision_opening",
            accessible=True,
        ))
    result = audit_wastewater_sp30(project)
    assert not any("К2-Ст" in row for row in result.errors)


def test_single_unconfirmed_lower_bend_is_rejected():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if row.element_id != "К1-ПрНП1"
    ]
    result = audit_wastewater_sp30(project)
    assert any("К1-Ст1" in row and "18.4" in row for row in result.errors)


def test_capped_cleanout_is_rejected_when_an_incoming_main_occupies_the_axis():
    project = deepcopy(_project())
    project.sewage.elements.append(SewerElementSpec(
        element_id="К1-Ошибочная-Прочистка-Ст2",
        system="K1",
        kind="cleanout",
        name="Недопустимая заглушённая прочистка",
        floor_from=0,
        dn_mm=100,
        section_id="К1-Вып1",
        connects_to="К1-Ст2",
        type_mark="DN100; 45°",
        service_direction="downstream",
        service_fitting="wye_45",
        accessible=True,
    ))

    result = audit_wastewater_sp30(project)

    assert any(
        "К1-Ошибочная-Прочистка-Ст2" in row
        and "перекрыла бы поток" in row
        for row in result.errors
    )
