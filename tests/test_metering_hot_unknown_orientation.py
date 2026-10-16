"""A missing legacy orientation is not a malformed per-node override."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.commission import build_commission_report
from app.pz.ios2_orchestrator import design_ios2
from app.pz.meter_products import evaluate_meter_product
from app.pz.metering_hot_node import hot_meter_view
from app.pz.metering_orientation import meter_orientation
from app.pz.metering_product_selection import resolve_metering_products


@pytest.fixture(scope="module")
def demo_project():
    request = load_request_file("demo/demo_project.yaml")
    return design_ios2(build_project(request), render_documents=False).project


def hot_selection(view):
    return resolve_metering_products(
        view, view.node_meter, bypass=False, electric_bypass=False,
    )


def test_missing_hot_orientation_stays_unknown_without_false_gate(demo_project):
    project = deepcopy(demo_project)
    before = deepcopy(asdict(project))
    assert project.metering_detail.meter_mounting == "unknown"
    assert project.metering_detail.validate() == []
    view = hot_meter_view(project)
    assert view.metering_detail.validate() == []
    assert view.metering_detail.meter_orientations == {}
    assert meter_orientation(view.metering_detail, "hot") == "unknown"
    assert view.metering_detail.meter_mounting == "unknown"
    assert not hot_selection(view).errors
    report = build_commission_report(project)
    check = next(c for c in report.checks if c.code == "VU-HOT-COMPOSITION")
    assert not check.blocking
    assert "требуют подтверждения" in check.result
    # Removing a false composition failure must not approve passport minima.
    assert next(c for c in report.checks if c.code == "CALC-03").blocking
    assert asdict(project) == before


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("axis", ["horizontal_dial_up", "vertical_up", "vertical_down"])
def test_known_hot_orientation_retains_scalar_fallback_and_override(demo_project, explicit, axis):
    project = deepcopy(demo_project)
    detail = project.metering_detail
    detail.meter_mounting = "unknown" if explicit else axis
    detail.meter_orientations = {"hot": axis} if explicit else {}
    before = deepcopy(asdict(project))
    view = hot_meter_view(project)
    assert view.metering_detail.validate() == []
    assert meter_orientation(view.metering_detail, "hot") == axis
    assert view.metering_detail.assembly_orientation == axis
    assert asdict(project) == before


@pytest.mark.parametrize("axis,explicit", [
    ("sideways", False), ("sideways", True), ("unknown", True), ("", False),
])
def test_malformed_orientation_is_not_silently_discarded(demo_project, axis, explicit):
    project = deepcopy(demo_project)
    if explicit:
        project.metering_detail.meter_orientations["hot"] = axis
    else:
        project.metering_detail.meter_mounting = axis
    assert project.metering_detail.validate()
    view = hot_meter_view(project)
    assert view.metering_detail.validate()
    assert hot_selection(view).errors
    # Invalid input is rejected before the commission can inspect its branches.
    with pytest.raises(ValueError, match="metering_detail"):
        build_commission_report(project)


def test_unknown_hot_axis_does_not_borrow_cold_axis_or_passport_minimum(demo_project):
    project = deepcopy(demo_project)
    detail = project.metering_detail
    detail.meter_orientations = {"cold": "vertical_up"}
    detail.meter_selection_mode = "catalogue_proposal"
    detail.catalogue_revision = get_metering_catalogue().revision
    before = deepcopy(asdict(project))
    view = hot_meter_view(project)
    assert meter_orientation(view.metering_detail, "hot") == "unknown"
    selection = hot_selection(view)
    assert not selection.errors
    position = next(p for p in selection.positions if p.role == "meter")
    assert any("положение и направление потока" in p for p in position.pending)
    check = evaluate_meter_product(view, view.node_meter)
    assert check.minimum_ok is None
    assert check.evidence.q_min_passport_m3h is None
    assert asdict(project) == before
