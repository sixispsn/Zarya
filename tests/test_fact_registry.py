from pathlib import Path

from app.intake.facts import FactStatus, build_fact_registry
from app.intake.project_intent import ProjectIntent


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def test_fact_registry_preserves_value_source_and_dependencies():
    intent = ProjectIntent.from_yaml(
        DEMO.read_text(encoding="utf-8"), source_ref=str(DEMO),
    )
    registry = build_fact_registry(intent)

    consumers = registry.get("consumers.total")
    assert consumers.value == 480
    assert consumers.status == FactStatus.DERIVED
    assert consumers.dependencies == ("consumers.groups",)

    guaranteed = registry.get("source.guaranteed_head")
    assert guaranteed.value == 32.0
    assert guaranteed.unit == "м"
    assert guaranteed.source_kind == "tu_or_design_assignment"
    assert "DEMO-ТУ-01" in guaranteed.source_ref


def test_fact_registry_marks_missing_sewer_topology_as_stage_r():
    intent = ProjectIntent.from_yaml(DEMO.read_text(encoding="utf-8"))
    intent.request.sewer_pipes = []
    intent.request.sewer_elements = []

    topology = build_fact_registry(intent).get("sewage.topology")
    assert topology.status == FactStatus.STAGE_R
    assert "ГОСТ Р 21.620-2023" in topology.normative_refs[0]


def test_fact_registry_tracks_exact_scheme_geometry_separately():
    intent = ProjectIntent.from_yaml(DEMO.read_text(encoding="utf-8"))
    geometry = build_fact_registry(intent).get("sewage.scheme_geometry")

    assert geometry.status == FactStatus.USER_DECLARED
    assert geometry.value == {
        "floor_height_m": 3.0,
        "roof_kind": "flat_non_accessible",
    }


def test_fact_registry_is_json_ready():
    registry = build_fact_registry(
        ProjectIntent.from_yaml(DEMO.read_text(encoding="utf-8"))
    )
    payload = registry.to_dict()
    assert payload["counts"]["user_declared"] > 0
    assert all(isinstance(row["systems"], list) for row in payload["facts"])
