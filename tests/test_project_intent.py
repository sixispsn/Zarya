from pathlib import Path

import pytest

from app.intake.project_builder import build_project
from app.intake.project_intent import (
    ProjectIntent,
    as_project_intent,
    unwrap_project_intent,
)
from app.intake.yaml_io import CURRENT_PROJECT_SCHEMA_VERSION, load_request_file


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def test_project_intent_wraps_existing_request_without_changing_builder_output():
    request = load_request_file(str(DEMO))
    intent = ProjectIntent(request, source_kind="yaml", source_ref=str(DEMO))

    assert intent.schema_version == CURRENT_PROJECT_SCHEMA_VERSION
    assert unwrap_project_intent(intent) is request
    assert as_project_intent(request).request is request
    assert build_project(intent) == build_project(request)


def test_project_intent_yaml_roundtrip_uses_versioned_contract():
    intent = ProjectIntent.from_yaml(DEMO.read_text(encoding="utf-8"))
    restored = ProjectIntent.from_yaml(intent.dump_yaml())
    assert restored.request == intent.request


def test_project_intent_rejects_unknown_schema_version():
    request = load_request_file(str(DEMO))
    with pytest.raises(ValueError, match="неподдерживаемую версию"):
        ProjectIntent(request, schema_version=CURRENT_PROJECT_SCHEMA_VERSION + 1)
