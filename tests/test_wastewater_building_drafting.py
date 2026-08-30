from pathlib import Path
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_building_drafting import (
    audit_wastewater_building_svgs,
    build_wastewater_building_assembly,
    build_wastewater_building_svgs,
    generate_wastewater_building_pdf_from_project,
)
from app.pz.wastewater_project_inputs import (
    resolve_wastewater_building_project_inputs,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _demo_project():
    return build_project(load_request_file(str(DEMO)))


def _demo_assembly():
    inputs = resolve_wastewater_building_project_inputs(_demo_project())
    return build_wastewater_building_assembly(
        inputs,
        floor_height_m=3.0,
        roof_kind="flat_non_accessible",
    )


def test_building_resolver_keeps_two_independent_k1_stacks_and_exact_k2():
    result = resolve_wastewater_building_project_inputs(_demo_project())

    assert result.complete
    assert [row.stack.riser_id for row in result.k1_risers] == [
        "К1-Ст1",
        "К1-Ст2",
    ]
    assert [
        [fixture.fixture_id for fixture in row.stack.fixtures_by_floor[1]]
        for row in result.k1_risers
    ] == [
        ["К1-Мой1", "К1-Ун1", "К1-Ум1", "К1-Ван1"],
        ["К1-Ун2", "К1-Ум2", "К1-Ван2", "К1-Мой2"],
    ]
    assert [row.revision_floors for row in result.k1_risers] == [
        (1, 4, 7, 10, 13, 16),
        (1, 4, 7, 10, 13, 16),
    ]
    assert [row.riser_id for row in result.k2_risers] == ["К2-Ст1", "К2-Ст2"]
    assert [row.lower_cleanout_element_ids for row in result.k1_risers] == [
        ("К1-ПрНП1",),
        (),
    ]
    assert [row.lower_cleanout_element_ids for row in result.k2_risers] == [
        ("К2-ПрНП1",),
        (),
    ]
    assert [row.lower_junction_element_ids for row in result.k1_risers] == [
        (),
        ("К1-ТрСт2",),
    ]
    assert [row.lower_junction_element_ids for row in result.k2_risers] == [
        (),
        ("К2-ТрСт2",),
    ]
    assert [row.funnel_quantity for row in result.k2_risers] == [2, 2]
    assert all(
        row.funnel_symbol_kind == "roof_funnel_heated"
        for row in result.k2_risers
    )
    assert result.k1_collectors[0].section_id == "К1-М1"
    assert result.k1_outlet.section_id == "К1-Вып1"
    assert result.k2_collectors[0].section_id == "К2-М1"
    assert result.k2_outlet.section_id == "К2-Вып1"


def test_building_resolver_blocks_unlinked_k2_funnel_and_missing_transition():
    project = _demo_project()
    funnel = next(
        row for row in project.sewage.elements if row.element_id == "К2-Вр1"
    )
    funnel.connects_to = "К2-Ст99"
    project.sewage.elements = [
        row
        for row in project.sewage.elements
        if not (row.system == "K2" and row.kind == "transition")
    ]

    result = resolve_wastewater_building_project_inputs(project)

    assert not result.complete
    assert any("ровно с одной" in row for row in result.diagnostics)
    assert any("перехода" in row for row in result.diagnostics)


def test_combined_floors_sheet_uses_shared_grid_and_no_fictional_k2_service():
    floors_svg, _ = build_wastewater_building_svgs(_demo_assembly())
    root = ElementTree.fromstring(floors_svg)

    assert root.get("width") == "841mm"
    assert root.get("height") == "594mm"
    assert floors_svg.count('data-floor-assembly="') == 6
    assert floors_svg.count('data-building-floor="') == 3
    assert 'data-floor-assembly="К1-Ст1-Сборка-Этаж-16"' in floors_svg
    assert 'data-floor-assembly="К1-Ст2-Сборка-Этаж-16"' in floors_svg
    assert floors_svg.count('data-ugo="roof_funnel_heated"') == 2
    assert "К2-Вр1" in floors_svg and "2 шт.; DN100" in floors_svg
    assert floors_svg.count('data-building-revision="К1-') == 4
    assert 'data-building-revision="К2-' not in floors_svg
    assert "К2 ⌀100" in floors_svg
    assert "К2 не соединяется с К1" in floors_svg


def test_combined_basement_uses_exact_edges_transitions_and_outlets_beyond_wall():
    _, basement_svg = build_wastewater_building_svgs(_demo_assembly())
    root = ElementTree.fromstring(basement_svg)

    assert root.get("width") == "841mm"
    assert root.get("height") == "594mm"
    for line_id in ("К1-М1", "К1-Вып1", "К2-М1", "К2-Вып1"):
        assert f'data-building-pipe-line="{line_id}"' in basement_svg
        assert f'data-pipe-line-id="{line_id}"' in basement_svg
    assert 'data-building-transition="К1-Пер1"' in basement_svg
    assert 'data-building-transition="К2-Пер1"' in basement_svg
    assert basement_svg.count('data-fitting="lower_elbow_45"') == 4
    assert basement_svg.count('data-fitting="service_wye_45"') == 2
    assert basement_svg.count('data-fitting="through_wye_45"') == 2
    assert 'data-building-revision="K2' not in basement_svg
    assert basement_svg.count('data-basement-cleanout=') == 2
    assert basement_svg.count('data-cleanout-axis="collinear"') == 2
    assert basement_svg.count('data-basement-through-junction=') == 2
    assert basement_svg.count('data-through-axis="open"') == 2
    assert basement_svg.count('data-fitting="cleanout_cap_fitting"') == 2
    for element_id in ("К1-ПрНП1", "К2-ПрНП1"):
        assert f'data-basement-cleanout="{element_id}"' in basement_svg
    for element_id in ("К1-ТрСт2", "К2-ТрСт2"):
        assert f'data-basement-through-junction="{element_id}"' in basement_svg
    assert 'data-basement-revision="К2-Р2-ТП"' in basement_svg
    assert "проточный косой тройник без заглушки" in basement_svg
    assert "за грань здания" in basement_svg
    assert "0,010" in basement_svg
    assert basement_svg.count("0,008") >= 2
    assert "i=" not in basement_svg and "i =" not in basement_svg


def test_combined_graphic_audit_passes_for_registry_driven_demo():
    assembly = _demo_assembly()
    svgs = build_wastewater_building_svgs(assembly)

    assert audit_wastewater_building_svgs(assembly, svgs) == ()


def test_combined_building_pdf_has_two_a1_landscape_pages(tmp_path):
    output = tmp_path / "building-k1-k2.pdf"

    generate_wastewater_building_pdf_from_project(
        str(output),
        _demo_project(),
        floor_height_m=3.0,
        roof_kind="flat_non_accessible",
    )

    pages = PdfReader(str(output)).pages
    assert len(pages) == 2
    for page in pages:
        width_mm = float(page.mediabox.width) * 25.4 / 72
        height_mm = float(page.mediabox.height) * 25.4 / 72
        assert width_mm == pytest.approx(841.0, abs=0.1)
        assert height_mm == pytest.approx(594.0, abs=0.1)
    text = "".join(page.extract_text() for page in pages)
    compact = "".join(text.split())
    assert "К1-Ст1" in text and "К1-Ст2" in text
    assert "К2-Вр1" in text and "К2-Вр2" in text
    assert "ВыпускК1-Вып1DN150заграньздания" in compact
    assert "ВыпускК2-Вып1DN150заграньздания" in compact
