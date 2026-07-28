"""Предпросмотр изменений использует штатный конвейер и не сохраняет проект."""
import copy
from pathlib import Path

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.impact import ImpactValidationError, calculate_impact_preview
from app.pz.ios2_orchestrator import design_ios2
from app.schemas.impact import ImpactPreviewInput


def _request():
    return load_request(
        Path("demo/demo_project.yaml").read_text(encoding="utf-8")
    )


def _baseline(request, tmp_path):
    return design_ios2(
        build_project(request),
        output_dir=str(tmp_path),
        render_documents=False,
    )


def test_calculation_only_mode_does_not_render_documents(tmp_path):
    bundle = _baseline(_request(), tmp_path)

    assert bundle.project.flows.q_day_tot == 86.4
    assert bundle.commission_report is not None
    assert bundle.pz_pdf is None
    assert list(tmp_path.iterdir()) == []
    assert any("без генерации документов" in item for item in bundle.status)


def test_impact_recalculates_consumers_and_head_without_mutating_request(tmp_path):
    request = _request()
    baseline = _baseline(request, tmp_path / "baseline")
    preview = calculate_impact_preview(
        request,
        baseline.project,
        baseline.commission_report,
        ImpactPreviewInput(consumer_counts=[500], guaranteed_head_m=40),
    )

    assert request.consumers[0].count == 480
    assert request.source_data.guaranteed_head_m == 32
    assert preview.baseline_fingerprint != preview.preview_fingerprint
    assert preview.changed_count >= 6
    daily = next(item for item in preview.deltas if item.id == "q-day")
    assert daily.changed
    assert daily.before == "86,4"
    assert daily.after == "90,0"
    assert {"Пояснительная записка", "Расчёты В1", "Баланс ВиВ"}.issubset(
        preview.affected_documents
    )


def test_same_inputs_have_no_impact_and_keep_fingerprint(tmp_path):
    request = _request()
    baseline = _baseline(request, tmp_path / "baseline")
    preview = calculate_impact_preview(
        request,
        baseline.project,
        baseline.commission_report,
        ImpactPreviewInput(
            consumer_counts=[480],
            floors=16,
            building_height_m=48,
            fire_height_m=48,
            guaranteed_head_m=32,
        ),
    )

    assert preview.input_changes == []
    assert preview.changed_count == 0
    assert preview.affected_documents == []
    assert preview.baseline_fingerprint == preview.preview_fingerprint


def test_impact_detects_sp10_fire_requirement_transition(tmp_path):
    request = copy.deepcopy(_request())
    request.floors = 8
    request.building_height_m = 24
    request.fire_height_m = 24
    request.network = None
    baseline = _baseline(request, tmp_path / "baseline")
    assert baseline.project.fire.required is False

    preview = calculate_impact_preview(
        request,
        baseline.project,
        baseline.commission_report,
        ImpactPreviewInput(
            floors=12,
            building_height_m=36,
            fire_height_m=36,
        ),
    )
    fire = next(item for item in preview.deltas if item.id == "fire")

    assert fire.changed
    assert fire.before == "не требуется"
    assert fire.after != "не требуется"
    assert "Гидравлический расчёт В2" in preview.affected_documents
    assert any("Hgeom" in warning for warning in preview.warnings)


def test_impact_rejects_head_that_contradicts_maximum_tu_head(tmp_path):
    request = _request()
    baseline = _baseline(request, tmp_path / "baseline")

    with pytest.raises(ImpactValidationError, match="maximum_head_m"):
        calculate_impact_preview(
            request,
            baseline.project,
            baseline.commission_report,
            ImpactPreviewInput(guaranteed_head_m=80),
        )
