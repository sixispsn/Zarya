"""Diagnostic DTO is a copy, not a second solver or release decision."""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from app.intake.studio_project import sewage_diagnostic_summary
from app.intake.studio_intake import build_handoff_request
from app.intake.studio_store import StudioStore
from app.intake.project_builder import build_project
from app.pz.project import Project
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
from tests.test_wastewater_diagnostics import _project
from tests.test_studio_risers import building_answers, rows as risers
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_sewer_elements import rows as elements
from tests import test_studio as studio_tests

client = studio_tests.client


@pytest.mark.parametrize("missing", [None, "calculation_length_m", "nominal_diameter_mm", "manning_n"])
def test_exact_result_copy_without_mutating_project(missing):
    project = _project()
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    if missing:
        setattr(pipe, missing, None)
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    before = deepcopy(project)
    result = sewage_diagnostic_summary(project)
    assert result == asdict(project.sewage.hydraulic_assessment)
    assert project == before
    result["errors"].append("DTO only")
    assert project == before


def test_missing_and_empty_results_are_distinct():
    project = Project()
    assert sewage_diagnostic_summary(project) is None
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    assert sewage_diagnostic_summary(project) is not None


def test_existing_hydraulic_numbers_and_flags_are_not_recomputed():
    project = _project()
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-Ветв-СУ1")
    pipe.design_flow_lps = 2.758
    pipe.flow_source = "TEST-ONLY: явная нагрузка участка"
    pipe.manning_n = 0.011
    pipe.hydraulic_source = "TEST-ONLY: источник шероховатости"
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    before = deepcopy(project)
    expected = next(r for r in project.sewage.hydraulic_assessment.hydraulics
                    if r.section_id == pipe.section_id)
    actual = next(r for r in sewage_diagnostic_summary(project)["hydraulics"]
                  if r["section_id"] == pipe.section_id)
    assert actual == asdict(expected)
    assert project == before


def test_api_exact_diagnostic_reload_and_revocation(client, tmp_path):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision":state["revision"],
        "answers":{**building_answers(), "sewer_pipes":pipes(), "sewer_elements":elements(),
                   "sewage_risers":risers()}})
    assert response.status_code == 200, response.text
    state = response.json()
    calculation = state["project_calculation"]
    stored = StudioStore(tmp_path / "studio").load(state["project_id"])
    project = build_project(build_handoff_request(stored))
    expected = json.loads(json.dumps(asdict(assess_wastewater_diagnostics(project))))
    assert calculation["sewage_diagnostic_review"] == expected
    assert not calculation["can_release"]
    assert client.get("/studio/api/draft").json()["project_calculation"] == calculation
    changed_pipes = pipes()
    next(p for p in changed_pipes if p["section_id"] == "К1-М1")["calculation_length_m"] = 53
    changed = studio_tests.answer(client, state, "sewer_pipes", changed_pipes)
    assert changed["project_calculation"] is None
    response = client.post("/studio/api/calculate", json={"revision":changed["revision"]})
    assert response.status_code == 200, response.text
    current = response.json()["project_calculation"]
    check = next(r for r in current["sewage_diagnostic_review"]["linear_service_checks"]
                 if r["section_id"] == "К1-М1")
    assert check["calculation_length_m"] == 53
    assert not current["can_release"]
