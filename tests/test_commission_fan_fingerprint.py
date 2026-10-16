"""Fan evidence/geometry are structured fingerprint inputs, not string reprs."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request, load_request_file
from app.pz.commission import _project_fingerprint, build_commission_report
from tests.test_commission import _calculated_project
from tests.test_fan_geometry_input import fan_form


def test_absent_fan_data_preserves_existing_passport_fingerprint():
    assert _project_fingerprint(_calculated_project()) == "b954b70ef7c6318b"


@pytest.mark.parametrize("field", ["evidence", "height", "geometry", "confirmation"])
def test_nested_fan_changes_affect_fingerprint_and_do_not_mutate_inputs(field):
    request = replace(load_request_file("demo/demo_project.yaml"), **fan_form().request_fields())
    project = build_project(request)
    before = deepcopy(project)
    fingerprint = _project_fingerprint(project)
    assert build_commission_report(project).project_fingerprint == fingerprint
    assert project == before
    assert _project_fingerprint(build_project(load_request(dump_request(request)))) == fingerprint
    ventilation = project.sewage.fan_ventilation
    geometry = project.sewage.fan_geometry
    if field in {"evidence", "height"}:
        terminal = ventilation.terminals[0]
        changes = ({"source_ref": terminal.source_ref + " revised"} if field == "evidence"
                   else {"height_m": (terminal.height_m or 0) + .1})
        project.sewage.fan_ventilation = replace(
            ventilation, terminals=(replace(terminal, **changes), *ventilation.terminals[1:]))
    elif field == "geometry":
        roof = geometry.roofs[0]
        project.sewage.fan_geometry = replace(
            geometry, roofs=(replace(roof, roof_level_m=roof.roof_level_m + .1), *geometry.roofs[1:]))
    else:
        project.sewage.fan_geometry = replace(geometry, confirmed=False)
    assert _project_fingerprint(project) != fingerprint


def test_unknown_objects_are_not_silently_stringified():
    project = _calculated_project()
    project.sewage.design_assignment_ref = object()
    with pytest.raises(TypeError, match="not JSON serializable"):
        _project_fingerprint(project)
