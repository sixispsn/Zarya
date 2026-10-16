from copy import deepcopy
from dataclasses import replace

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.wastewater_fan_geometry import FanGeometryInput
from app.pz.wastewater_fan_binding import (
    fan_details_from_project,
    build_bound_fan_preview_svgs,
)
from app.web.fan_inputs import FanFormInput
from tests.fan_binding_fixture import fan_binding_fixture
from tests.test_yaml_io import GOOD


def geometry():
    _, data = fan_binding_fixture()
    return FanGeometryInput(
        data.roofs, data.valves, True, "Контрольная геометрия; не рабочий проект"
    )


def fan_form():
    _, data = fan_binding_fixture()
    return FanFormInput(data.evidence, geometry(), 6.6)


def test_yaml_builder_roundtrip_preserves_geometry_and_old_projects():
    req = load_request(GOOD)
    assert req.wastewater_fan_geometry is None
    assert "fan_geometry:" not in dump_request(req)
    req = replace(req, **fan_form().request_fields())
    restored = load_request(dump_request(req))
    assert restored == req
    project = build_project(restored)
    assert project.sewage.fan_geometry == geometry()
    assert project.sewage.fan_ventilation == req.wastewater_fan_ventilation
    assert project.sewage.roof_relative_elevation_m == 6.6


def test_saved_geometry_drives_exactly_the_same_drawing_without_mutation():
    project, data = fan_binding_fixture()
    project.sewage.fan_geometry = FanGeometryInput.from_mapping(geometry().to_mapping())
    before = deepcopy(project)
    resolved = fan_details_from_project(project)
    assert resolved == data
    assert build_bound_fan_preview_svgs(
        project, resolved
    ) == build_bound_fan_preview_svgs(project, data)
    assert project == before


def test_geometry_confirmation_does_not_bypass_normative_checks():
    project, _ = fan_binding_fixture()
    project.sewage.fan_geometry = geometry()
    project.sewage.fan_ventilation = replace(
        project.sewage.fan_ventilation, external_ventilation_verified=None
    )
    with pytest.raises(ValueError, match="validation not complete"):
        fan_details_from_project(project)


@pytest.mark.parametrize("confirmed", [False, None])
def test_unconfirmed_geometry_cannot_drive_binding(confirmed):
    project, _ = fan_binding_fixture()
    project.sewage.fan_geometry = (
        replace(geometry(), confirmed=False) if confirmed is False else None
    )
    with pytest.raises(ValueError, match="не подтверждена"):
        fan_details_from_project(project)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "4.4", None])
def test_geometry_rejects_non_numeric_levels(bad):
    value = geometry().to_mapping()
    value["roofs"][0]["risers"][0]["lower_port_m"] = bad
    with pytest.raises(ValueError):
        FanGeometryInput.from_mapping(value)


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "duplicate",
        "wrong_drain",
        "inverted",
        "missing_source",
        "empty_confirmed",
        "same_axis",
    ],
)
def test_geometry_rejects_structural_errors(change):
    value = geometry().to_mapping()
    roof = value["roofs"][0]
    if change == "unknown":
        value["silent_default"] = True
    if change == "duplicate":
        value["roofs"].append(deepcopy(roof))
    if change == "wrong_drain":
        roof["condensate_riser_id"] = roof["risers"][1]["riser_id"]
    if change == "inverted":
        roof["risers"][0]["collector_m"] = 9
    if change == "missing_source":
        value["confirmation_ref"] = ""
    if change == "empty_confirmed":
        value["roofs"], value["valves"] = [], []
    if change == "same_axis":
        roof["risers"][1]["x_m"] = roof["risers"][0]["x_m"]
    with pytest.raises(ValueError):
        FanGeometryInput.from_mapping(value)


def test_invalid_yaml_geometry_reports_the_input_path():
    with pytest.raises(YamlFormatError, match=r"sewage.fan_geometry"):
        load_request(GOOD + "\nsewage:\n  fan_geometry: {confirmed: yes}\n")


@pytest.mark.parametrize(
    "change",
    ["members", "kind", "roof", "duplicate_member", "missing_detail", "no_roof"],
)
def test_form_validates_geometry_group_links(change):
    import json

    value = fan_form().to_mapping()
    if change == "members":
        value["fan_ventilation"]["terminals"][0]["riser_ids"][0] = "wrong"
    if change == "kind":
        value["fan_ventilation"]["terminals"][0]["kind"] = "unknown"
    if change == "roof":
        value["roof_level"] = 7
    if change == "duplicate_member":
        value["fan_ventilation"]["terminals"][1]["riser_ids"] = ["К1-Ст1"]
    if change == "missing_detail":
        value["fan_geometry"]["valves"] = []
    if change == "no_roof":
        value["roof_level"] = None
    with pytest.raises(ValueError):
        FanFormInput.parse(json.dumps(value))
