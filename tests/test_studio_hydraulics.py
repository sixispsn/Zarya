"""Studio calls the accepted solver and never substitutes cold losses for hot."""

from copy import deepcopy
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics
from app.intake.studio_hydraulics import validate_sections
from app.intake.studio_intake import (
    answer_field, build_handoff_request, calculate_draft, head_missing, public_draft,
)
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import dump_request, load_request
from app.main import app


ROWS = [
    dict(section_id="Ввод", role="input", length_m=12, inner_diameter_mm=40,
         roughness_mm=0.1, flow_lps=None, material="Труба по заданию"),
    dict(section_id="В1-1", role="internal", length_m=16, inner_diameter_mm=26,
         roughness_mm=0.01, flow_lps=0.35, material="Труба по заданию"),
]


def draft(hot=False):
    d = dict(revision=0, answers={}, documents=[])
    for key, value in dict(
        residents=20, consumer_code="residential_full_bath", floors=2,
        apartments=8, building_height_m=6.6, fire_height_m=4.8,
        hws_type="central" if hot else "none", h_geom_m=6, guaranteed_head_m=5,
        h_apartment_c_meter_m=0.5, h_apartment_h_meter_m=0.7,
        hws_heater_in_scope="no", pressure_loss_mode="sections", v1_sections=ROWS,
    ).items():
        answer_field(d, key, value)
    d["calculation"] = calculate_draft(d)
    return d


def test_studio_sections_use_existing_solver_and_current_flow():
    d = draft()
    req = build_handoff_request(d)
    expected = calculate_v1_hydraulics([V1SectionInput(**asdict(row)) for row in req.v1_sections])
    result = calculate_project(d)
    assert result["hydraulics"] == asdict(expected)
    assert result["head"]["ready"]
    assert result["head"]["paths"][0]["head"]["h_losses_dynamic_m"] == pytest.approx(
        round(expected.total_loss_m + result["head"]["paths"][0]["meter_loss_m"], 2))
    assert all(row["local_loss_factor"] == .3 for row in result["hydraulics"]["sections"])
    before = req.v1_sections[0].flow_lps
    d["project_calculation"] = result
    d["preview"] = {"old": "document"}
    answer_field(d, "residents", 100)
    assert d["project_calculation"] is None and d["preview"] is None
    after = build_handoff_request(d)
    assert after.v1_sections[0].flow_lps > before
    assert after.v1_sections[1].flow_lps == .35


def test_heater_scope_changes_auto_inlet_to_total_current_demand():
    d = draft(hot=True)
    cold = build_handoff_request(d).v1_sections[0].flow_lps
    answer_field(d, "hws_heater_in_scope", "yes")
    req = build_handoff_request(d)
    assert req.v1_sections[0].flow_lps == calculate_draft(d)["total"]["q_sec"]
    assert req.v1_sections[0].flow_lps > cold


def test_unknown_heater_scope_does_not_guess_automatic_inlet_flow():
    d = draft(hot=True)
    answer_field(d, "hws_heater_in_scope", None)
    assert not build_handoff_request(d).v1_sections
    result = calculate_project(d)
    assert result["hydraulics"] is None and not result["head"]["ready"]


def test_cold_route_does_not_complete_hot_route_or_pump():
    d = draft(hot=True)
    result = calculate_project(d)
    assert result["hydraulics"]
    cold, hot = result["head"]["paths"]
    assert cold["complete"] and not hot["complete"]
    assert hot["head"]["h_required_m"] is None
    assert "отдельный расчёт потерь труб по трассе Т3" in hot["missing"]
    assert not result["head"]["ready"] and result["pumps"] is None
    assert not result["can_release"] and result["can_preview"]
    assert "t3_sections" in head_missing(d)
    answer_field(d, "t3_loss_mode", "ready")
    answer_field(d, "h_il_hot_m", 7)
    result = calculate_project(d)
    assert result["head"]["ready"]
    hot = result["head"]["paths"][1]
    assert any(value == 7 and "∑Hil" in label for label, value in hot["head"]["components"])


@pytest.mark.parametrize("rows", [None, ROWS[:1], ROWS[1:]])
def test_incomplete_route_does_not_turn_missing_part_into_zero(rows):
    d = draft()
    answer_field(d, "h_il_m", 999)
    answer_field(d, "h_vvod_m", 999)
    answer_field(d, "v1_sections", rows)
    req = build_handoff_request(d)
    assert not req.v1_sections
    assert req.source_data.h_il_m is None and req.source_data.h_vvod_m is None
    assert "v1_sections" in head_missing(d)
    result = calculate_project(d)
    assert result["hydraulics"] is None and not result["head"]["ready"]


def test_legacy_ready_totals_and_mode_switch_are_explicit():
    d = draft()
    answer_field(d, "pressure_loss_mode", None)
    answer_field(d, "h_il_m", 3)
    answer_field(d, "h_vvod_m", 1)
    assert build_handoff_request(d).source_data.h_il_m == 3
    assert not build_handoff_request(d).v1_sections
    assert calculate_project(d)["head"]["ready"]
    answer_field(d, "pressure_loss_mode", "sections")
    assert build_handoff_request(d).source_data.h_il_m is None
    assert calculate_project(d)["hydraulics"] is not None


def test_handoff_yaml_preserves_current_sections_and_hot_scope():
    req = build_handoff_request(draft(hot=True))
    restored = load_request(dump_request(req))
    assert restored.v1_sections == req.v1_sections
    assert restored.source_data.internal_losses_scope == "cold_only"
    assert restored.source_data.h_il_hot_m is None


@pytest.mark.parametrize("key,value", [
    ("length_m", 0), ("inner_diameter_mm", -1), ("roughness_mm", "NaN"),
    ("flow_lps", None), ("flow_lps", True), ("role", "bogus"),
    ("section_id", ""), ("material", []), ("local_loss_factor", .1),
])
def test_invalid_sections_rejected(key, value):
    rows = deepcopy(ROWS)
    rows[1][key] = value
    with pytest.raises(ValueError):
        validate_sections(rows)


def test_decimal_comma_zero_roughness_and_manual_inlet_are_preserved():
    rows = deepcopy(ROWS)
    rows[0].update(roughness_mm="0", flow_lps="0,42", length_m="12,5")
    clean = validate_sections(rows)
    assert clean[0]["roughness_mm"] == 0
    assert clean[0]["flow_lps"] == .42 and clean[0]["length_m"] == 12.5
    with pytest.raises(ValueError):
        validate_sections([ROWS[0], ROWS[0]])
    with pytest.raises(ValueError):
        validate_sections(ROWS * 16)


def test_structured_api_persists_and_invalid_update_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "1")
    monkeypatch.setenv("ZARYA_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("ZARYA_PROJECTS_DIR", str(tmp_path / "projects"))
    with TestClient(app) as client:
        client.headers["X-Zarya-Studio"] = "1"
        initial = client.post("/studio/api/draft").json()
        data = draft()
        answers = {key: value["value"] for key, value in data["answers"].items()}
        response = client.post("/studio/api/calculate", json={
            "revision": initial["revision"], "answers": answers,
        })
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["project_calculation"]["hydraulics"]
        assert state["project_calculation"]["head"]["ready"]
        assert client.get("/studio/api/draft").json() == state
        bad = deepcopy(ROWS)
        bad[1]["flow_lps"] = None
        response = client.patch("/studio/api/answers", json={
            "revision": state["revision"], "answers": {"residents": 100, "v1_sections": bad},
        })
        assert response.status_code == 422
        assert client.get("/studio/api/draft").json() == state


def test_route_is_not_a_mandatory_stage_p_question():
    d = draft()
    answer_field(d, "v1_sections", None)
    d["calculation"] = calculate_draft(d)
    state = public_draft(d)
    assert not any(row["id"] == "losses" for row in state["next_steps"])
    assert "v1_sections" in state["head_missing"]
    assert "h_il_m" not in state["head_missing"] and "h_vvod_m" not in state["head_missing"]


@pytest.mark.parametrize("changed", [False, True])
def test_full_editor_preserves_sections_or_requests_recalculation(tmp_path, monkeypatch, changed):
    import asyncio
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from app.intake.project_store import ProjectStore
    from app.web import wizard

    req = build_handoff_request(draft(hot=True))
    projects = ProjectStore(str(tmp_path / "projects"))
    pid = projects.save(req)
    monkeypatch.setattr(wizard, "_STORE", projects)
    captured = []

    def capture(request, received, project_id):
        captured.append(received)
        return JSONResponse({"ok": True})

    monkeypatch.setattr(wizard, "design_request_response", capture)
    request = Request({"type": "http", "http_version": "1.1", "method": "POST",
                       "scheme": "http", "path": "/wizard/design", "root_path": "",
                       "query_string": b"", "headers": [], "server": ("testserver", 80)})
    request._form = FormData({
        "project_id": pid, "consumer1_name": "Жилая часть",
        "consumer1_code": "residential_full_bath", "consumer1_count": "100" if changed else "20",
        "hws_type": "central", "building_type": "residential", "floors": "2", "height": "6.6",
    })
    response = asyncio.run(wizard.wizard_design(request))
    if changed:
        assert not captured
        assert "Пересчитайте участки В1" in response.body.decode()
    else:
        assert captured[0].v1_sections == req.v1_sections
        assert captured[0].source_data.internal_losses_scope == "cold_only"


def test_pz_and_calculation_html_use_the_same_current_sections(tmp_path):
    from app.intake.project_builder import build_project
    from app.pz.generator import generate_pz_html, generate_v1_calculation_html
    from app.pz.ios2_orchestrator import design_ios2

    d = draft(hot=True)
    req = build_handoff_request(d)
    bundle = design_ios2(build_project(req), output_dir=str(tmp_path), render_documents=False)
    result = calculate_project(d)
    assert result["hydraulics"] == asdict(bundle.project.v1_hydraulic_result)
    assert result["head"]["paths"][0]["head"] == asdict(bundle.project.head_paths.cold.head)
    assert bundle.project.head_paths.hot.head.h_required_m is None
    pz = generate_pz_html(bundle.project)
    assert "В1-1" in pz  # Detailed section schedule belongs to the PZ.
    for html in (pz, generate_v1_calculation_html(bundle.project)):
        assert "отдельный расчёт потерь труб по трассе Т3" in html
        head = f"{bundle.project.head_paths.cold.head.h_required_m:.2f}".replace(".", ",")
        assert head in html
        assert "демонстрац" not in html.lower()
