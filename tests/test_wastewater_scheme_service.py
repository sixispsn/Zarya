from copy import deepcopy
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_scheme_service import (
    assess_wastewater_scheme_readiness,
    generate_wastewater_scheme,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_canonical_release_uses_registry_building_pdf(tmp_path):
    output = tmp_path / "scheme.pdf"

    result = generate_wastewater_scheme(_project(), str(output))

    assert result.ready
    assert result.backend == "registry-building-v1"
    pages = PdfReader(str(output)).pages
    assert len(pages) == 2
    all_text = "\n".join(page.extract_text() or "" for page in pages)
    assert "ZARYA-DEMO-001-ИОС3.СК" in all_text
    assert "ZARYA-DEMO-001-ИОС2" not in all_text
    assert all(
        float(page.mediabox.width) * 25.4 / 72 == pytest.approx(841.0, abs=0.02)
        for page in pages
    )


def test_missing_terminal_cleanout_produces_status_without_synthetic_fitting(
    tmp_path,
):
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if row.element_id != "К1-ПрНП1"
    ]

    readiness = assess_wastewater_scheme_readiness(project)
    result = generate_wastewater_scheme(project, str(tmp_path / "blocked.pdf"))

    assert not readiness.ready
    assert any("соосным заглушённым концом" in row for row in readiness.reasons)
    assert not result.ready
    assert result.backend == "incomplete-status"
    reader = PdfReader(result.output_path)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" in text
    assert "Прочистка" not in text


def test_transition_not_linked_to_real_dn_change_blocks_release():
    project = deepcopy(_project())
    transition = next(
        row for row in project.sewage.elements
        if row.element_id == "К1-Пер1"
    )
    transition.connects_to = "КК-1"

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any("перехода" in row for row in readiness.reasons)
    assert any("не привязан" in row for row in readiness.reasons)


def test_capped_cleanout_on_through_node_is_rejected():
    project = deepcopy(_project())
    cleanout = deepcopy(next(
        row for row in project.sewage.elements
        if row.element_id == "К1-ПрНП1"
    ))
    cleanout.element_id = "К1-ПрНП2-Запрещённая"
    cleanout.section_id = "К1-Вып1"
    cleanout.connects_to = "К1-Ст2"
    project.sewage.elements.append(cleanout)

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any(
        "К1-Ст2" in row and "прочистка с заглушкой недопустима" in row
        for row in readiness.reasons
    )


def test_explicit_scheme_geometry_is_required_without_defaults():
    project = deepcopy(_project())
    project.sewage.floor_height_m = None
    project.sewage.roof_kind = "unknown"

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any("высота типового этажа" in row for row in readiness.reasons)
    assert any("вид и доступность кровли" in row for row in readiness.reasons)
