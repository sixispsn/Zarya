"""Roof choices must reach rain/fan models, not only change a select label."""
import pytest

from app.intake.project_store import ProjectStore
from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, public_draft
from app.intake.studio_roofs import ROOF_CHOICES, roof_rule
from app.intake.studio_study import initialize_study, calculate_study
from app.intake.yaml_io import dump_request, load_request
from tests import test_studio as studio_tests
from tests.test_studio_study import start

client = studio_tests.client
new, answer, values = studio_tests.new, studio_tests.answer, studio_tests.values


def test_five_visible_choices_and_ambiguous_legacy_roof(client):
    state = new(client)
    assert state["options"]["roof_type"] == [
        {"value": key, "label": label} for key, label in ROOF_CHOICES.items()
    ]
    assert len(state["options"]["roof_type"]) == 5
    assert not {"sloped", "flat"} & set(ROOF_CHOICES)
    assert not state["roof_ventilation"]["minimum_height_m"]
    state = answer(client, state, "roof_type", "flat")
    assert values(state)["roof_type"]["value"] == "flat"
    assert state["roof_ventilation"]["fan_kind"] == "unknown"
    assert state["roof_ventilation"]["minimum_height_m"] is None
    assert "Уточните" in state["roof_ventilation"]["note"]


@pytest.mark.parametrize("choice,rain,fan,height", [
    ("single_slope", "sloped", "single_slope", .2),
    ("sloped", "sloped", "pitched", .2),
    ("gable", "sloped", "gable", .2),
    ("flat_accessible", "flat", "flat_accessible", 3.),
    ("flat_non_accessible", "flat", "flat_non_accessible", .2),
    ("flat", "flat", "unknown", None),
    ("complex", "not_set", "complex", None),
])
def test_roof_reaches_saved_request_and_roundtrip(client, tmp_path, choice, rain, fan, height):
    state = studio_tests.residential_project(client)
    state = answer(client, state, "roof_type", choice)
    assert state["roof_ventilation"]["minimum_height_m"] == height
    response = client.post("/studio/api/handoff", json={"revision": state["revision"]})
    assert response.status_code == 200, response.text
    project_id = response.json()["next_url"].rsplit("/", 1)[-1]
    req = ProjectStore(tmp_path / "projects").load(project_id)
    assert req.roof_type == rain
    assert req.wastewater_roof_kind == fan
    restored = load_request(dump_request(req))
    assert restored.roof_type == rain and restored.wastewater_roof_kind == fan
    assert build_project(restored).sewage.roof_kind == fan
    # The roof selector is not evidence for an actual fan collector or its geometry.
    assert req.wastewater_fan_ventilation is None
    assert req.wastewater_fan_geometry is None


def test_height_note_preserves_accessible_roof_group_requirement():
    rule = roof_rule("flat_accessible")
    assert rule["minimum_group_risers"] == 4
    assert "трасса объединения подтверждается отдельно" in rule["note"]
    for key in ("sloped", "single_slope", "gable", "flat_non_accessible"):
        assert roof_rule(key)["minimum_group_risers"] is None


@pytest.mark.parametrize("kind,original", [
    ("two", "flat_non_accessible"), ("three", "flat_accessible"),
])
def test_incompatible_study_roof_cannot_reuse_fixed_drawing(client, kind, original):
    state = start(client, new(client), kind)
    assert values(state)["roof_type"]["value"] == original
    for choice in ROOF_CHOICES:
        state = client.post("/studio/api/calculate", json={
            "revision": state["revision"], "answers": {"roof_type": choice},
        }).json()
        assert values(state)["roof_type"]["value"] == choice
        assert state["project_calculation"]["can_preview"] == (choice == original)
        assert state["preview"] is None and not state["project_calculation"]["can_release"]
        if choice != original:
            assert "геометрия" in state["project_calculation"]["issues"][0]["message"]
            response = client.post("/studio/api/preview", json={"revision": state["revision"]})
            assert response.status_code == 422
    state = answer(client, state, "roof_type", original)
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert state["project_calculation"]["can_preview"]


def test_roof_edit_invalidates_stale_outputs_and_old_study_requires_clarification():
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    original_demand = draft["calculation"]
    draft.update(preview={"id": "old"}, package={"state": "ready"})
    answer_field(draft, "roof_type", "gable")
    assert all(draft[key] is None for key in ("preview", "package", "project_calculation"))
    assert draft["calculation"] == original_demand  # Water consumption is unchanged.
    answer_field(draft, "roof_type", "flat")
    assert public_draft(draft)["roof_ventilation"]["fan_kind"] == "unknown"
    assert calculate_study(draft)["state"] == "blocked"


def test_full_editor_has_separate_gable_option(client):
    response = client.get("/wizard")
    assert response.status_code == 200
    assert '<option value="gable">двускатная</option>' in response.text
    assert '<option value="single_slope">односкатная</option>' in response.text
    assert '<option value="complex">сложная / составная</option>' in response.text
    assert '<option value="pitched"' not in response.text
    assert 'data-roof-profile-control="wastewater_roof_kind"' in response.text


def test_complex_roof_has_no_fabricated_global_height_or_rain_type():
    rule = roof_rule("complex")
    assert rule["minimum_height_m"] is None
    assert rule["minimum_group_risers"] is None
    assert rule["rain_type"] == "not_set"
    assert "нужны участки" in rule["note"]
