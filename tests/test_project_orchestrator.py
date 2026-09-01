from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.project_intent import ProjectIntent
from app.intake.yaml_io import load_request_file
from app.pz.ios2_orchestrator import design_ios2
from app.pz.project_orchestrator import design_project


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def test_design_project_facade_is_identical_to_existing_pipeline(tmp_path):
    old_request = load_request_file(str(DEMO))
    new_request = load_request_file(str(DEMO))

    old = design_ios2(
        build_project(old_request),
        output_dir=str(tmp_path / "old"),
        render_documents=False,
    )
    new = design_project(
        ProjectIntent(new_request, source_kind="yaml", source_ref=str(DEMO)),
        output_dir=str(tmp_path / "new"),
        render_documents=False,
    )

    assert new.project == old.project
    assert new.status == old.status
    assert new.warnings == old.warnings
    assert new.project.flows == old.project.flows
    assert new.project.pumps == old.project.pumps
