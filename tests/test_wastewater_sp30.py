from copy import deepcopy
from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_sp30 import audit_wastewater_sp30


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_demo_revision_schedule_and_turn_access_pass_sp30_audit():
    result = audit_wastewater_sp30(_project())
    assert result.ready
    assert result.errors == []
    assert result.warnings == []
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


def test_k2_turn_without_cleanout_is_rejected():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if not (row.kind == "cleanout" and row.section_id == "К2-Ст1")
    ]
    result = audit_wastewater_sp30(project)
    assert any("К2-Ст1" in row and "21.10" in row for row in result.errors)


def test_single_unconfirmed_lower_bend_is_rejected():
    project = deepcopy(_project())
    elbow = next(
        row for row in project.sewage.elements
        if row.kind == "elbow" and row.section_id == "К1-Ст1"
    )
    elbow.quantity = 1
    result = audit_wastewater_sp30(project)
    assert any("К1-Ст1" in row and "18.4" in row for row in result.errors)
