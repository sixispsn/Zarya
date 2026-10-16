"""Read-only transfer of canonical results, not a second calculation."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.calc.sewage import (
    DomesticSewageResult, SewageRiserInput, calculate_sewage_system, check_sewage_system,
)
from app.intake.studio_project import sewage_riser_summary
from app.pz.project import Project
from tests import test_studio as studio_tests
from tests.test_studio_risers import building_answers, rows
from tests.test_studio_sewer_pipes import rows as pipes

client = studio_tests.client


@pytest.mark.parametrize("ventilation,dn,flow", [
    ("ventilated", 110, 1), ("ventilated", 110, 20),
    ("unventilated", 110, 1), ("ventilated", 111, 1),
])
def test_summary_is_exact_independent_result_copy(ventilation, dn, flow):
    project = Project()
    project.sewage.result = calculate_sewage_system(2, 1.6, [SewageRiserInput(
        "К1-Ст1", flow, "pp", ventilation, dn, 110, 87.5)])
    before = deepcopy(project.sewage.result)
    result = sewage_riser_summary(project)
    assert result == asdict(before)
    assert project.sewage.result == before
    result["risers"][0]["note"] = "mutated DTO"
    assert project.sewage.result == before


def test_missing_result_is_not_reconstructed():
    assert sewage_riser_summary(Project()) is None


def test_real_api_result_roundtrip_and_revocation(client):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision":state["revision"],
        "answers":{**building_answers(), "sewer_pipes":pipes(), "sewage_risers":rows()}})
    assert response.status_code == 200, response.text
    state = response.json()
    calculation = state["project_calculation"]
    summary = calculation["sewage_riser_review"]
    expected = check_sewage_system(DomesticSewageResult(**summary["total"]),
        [SewageRiserInput(**row) for row in rows()])
    assert summary["risers"] == [asdict(row) for row in expected.risers]
    assert not calculation["can_release"]
    assert client.get("/studio/api/draft").json()["project_calculation"] == calculation
    changed = studio_tests.answer(client, state, "sewage_risers", rows()[:1])
    assert changed["project_calculation"] is None
    response = client.post("/studio/api/calculate", json={"revision":changed["revision"]})
    assert response.status_code == 200
    current = response.json()["project_calculation"]
    assert len(current["sewage_riser_review"]["risers"]) == 1
    assert not current["can_release"]
