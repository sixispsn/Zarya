from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import (
    generate_wastewater_scheme_result,
    generate_wastewater_ugo_pdf,
)
from app.pz.wastewater_registry import KIND_LABELS
from app.pz.wastewater_ugo import (
    UGO_CATALOG,
    build_wastewater_ugo_sheet,
    get_ugo_definition,
    legend_definitions,
    render_ugo,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_every_registry_kind_has_a_catalog_entry():
    assert set(KIND_LABELS) <= set(UGO_CATALOG)
    assert len(UGO_CATALOG) == len(set(UGO_CATALOG))


def test_normative_sewer_symbols_keep_table_and_position_traceability():
    expected = {
        "sink": ("табл. 3", "поз. 2"),
        "washbasin": ("табл. 3", "поз. 3"),
        "bath": ("табл. 3", "поз. 7"),
        "toilet": ("табл. 3", "поз. 11"),
        "floor_drain": ("табл. 3", "поз. 16"),
        "roof_funnel": ("табл. 3", "поз. 18"),
        "trap": ("табл. 4", "поз. 4"),
        "revision": ("табл. 4", "поз. 11"),
        "flow_direction": ("табл. 5", "поз. 1"),
    }
    for key, fragments in expected.items():
        definition = get_ugo_definition(key)
        assert definition.is_normative
        assert "ГОСТ 21.205-2016" in definition.basis
        assert all(fragment in definition.basis for fragment in fragments)


def test_recommended_and_project_symbols_are_not_presented_as_normative():
    assert get_ugo_definition("cleanout").status == "recommended"
    assert get_ugo_definition("fire_collar").status == "recommended"
    assert get_ugo_definition("outlet").status == "project"
    assert not get_ugo_definition("junction").is_normative


def test_legend_contains_only_used_kinds_plus_flow_direction():
    rows = legend_definitions(["toilet", "roof_funnel", "toilet"])
    assert [row.key for row in rows] == [
        "toilet",
        "roof_funnel",
        "flow_direction",
    ]


def test_svg_renderer_marks_symbol_key_and_unknown_as_other():
    assert 'data-ugo="toilet"' in render_ugo("toilet", 10, 20)
    assert 'data-ugo="other"' in render_ugo("not_registered", 10, 20)
    with pytest.raises(KeyError, match="неизвестный вид УГО"):
        get_ugo_definition("not_registered")


def test_scheme_legend_is_driven_by_demo_registry():
    svg = generate_wastewater_scheme_result(_project()).svg
    assert 'data-ugo="sink"' in svg
    assert 'data-ugo="flow_direction"' in svg
    assert 'data-ugo="system_k1"' in svg
    assert 'data-ugo="system_k2"' in svg
    assert 'data-ugo="roof_funnel_heated"' in svg
    assert 'data-ugo="pump"' not in svg
    assert "нормативная трассировка - лист 2" in svg


def test_ugo_sheet_is_a3_and_contains_only_used_source_classes(tmp_path):
    project = _project()
    svg = build_wastewater_ugo_sheet(project)
    assert 'width="420mm"' in svg
    assert "нормативное УГО" in svg
    assert "рекомендуемый пример" in svg
    assert "проектное обозначение" not in svg
    assert "систем К1, К2" in svg
    assert "систем К1, К2 и К3" not in svg
    assert "ГОСТ 21.205-2016, табл. 3, поз. 11" in svg

    output = tmp_path / "ugo.pdf"
    generate_wastewater_ugo_pdf(project, str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(420.0, abs=0.02)
    assert height_mm == pytest.approx(297.0, abs=0.02)
