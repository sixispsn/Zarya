from copy import deepcopy
from pathlib import Path
import re
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


def _replace_index(value: str, old: int, new: int) -> str:
    replacements = (
        (f"Ст{old}", f"Ст{new}"),
        (f"Вент{old}", f"Вент{new}"),
        (f"Ветв-СУ{old}", f"Ветв-СУ{new}"),
        (f"Ветв-Кух{old}", f"Ветв-Кух{new}"),
        (f"Ун{old}", f"Ун{new}"),
        (f"Ум{old}", f"Ум{new}"),
        (f"Ван{old}", f"Ван{new}"),
        (f"Мой{old}", f"Мой{new}"),
        (f"Р{old}", f"Р{new}"),
        (f"Вр{old}", f"Вр{new}"),
        (f"-0{old}", f"-0{new}"),
        (f" {old}", f" {new}"),
    )
    for source, target in replacements:
        value = value.replace(source, target)
    return value


def _project_with_linear_riser_count(count: int):
    """Expand the confirmed demo topology without adding inferred values."""
    assert count >= 1
    project = deepcopy(_demo_project())
    pipes = project.sewage.pipes
    elements = project.sewage.elements

    k1_riser_template = deepcopy(next(row for row in pipes if row.section_id == "К1-Ст2"))
    k1_branch_templates = deepcopy([
        row for row in pipes if row.system == "K1" and row.to_node == "К1-Ст2"
        and "ответвление" in row.purpose
    ])
    k1_fixture_templates = deepcopy([
        row for row in elements
        if row.element_id in {"К1-Ун2", "К1-Ум2", "К1-Ван2", "К1-Мой2"}
    ])
    k1_revision_templates = deepcopy([
        row for row in elements
        if row.system == "K1" and row.kind == "revision" and row.section_id == "К1-Ст2"
    ])
    k1_collector_template = deepcopy(next(row for row in pipes if row.section_id == "К1-М1"))
    k1_outlet = next(row for row in pipes if row.section_id == "К1-Вып1")
    k1_elbow_template = deepcopy(next(row for row in elements if row.element_id == "К1-ОтвСт2"))
    k1_tee_template = deepcopy(next(row for row in elements if row.element_id == "К1-ТрСт2"))
    k1_transition = next(row for row in elements if row.element_id == "К1-Пер1")

    k2_riser_template = deepcopy(next(row for row in pipes if row.section_id == "К2-Ст2"))
    k2_funnel_template = deepcopy(next(row for row in elements if row.element_id == "К2-Вр2"))
    k2_revision_templates = deepcopy([
        row for row in elements
        if row.system == "K2" and row.kind == "revision" and row.section_id == "К2-Ст2"
    ])
    k2_collector_template = deepcopy(next(row for row in pipes if row.section_id == "К2-М1"))
    k2_outlet = next(row for row in pipes if row.section_id == "К2-Вып1")
    k2_elbow_template = deepcopy(next(row for row in elements if row.element_id == "К2-ОтвСт2"))
    k2_tee_template = deepcopy(next(row for row in elements if row.element_id == "К2-ТрСт2"))
    k2_transition = next(row for row in elements if row.element_id == "К2-Пер1")

    if count == 1:
        project.sewage.pipes = [
            row for row in pipes
            if row.section_id not in {
                "К1-Ст2", "К1-Ветв-СУ2", "К1-Ветв-Кух2", "К1-М1",
                "К2-Ст2", "К2-М1",
            }
        ]
        project.sewage.elements = [
            row for row in elements
            if row.element_id not in {
                "К1-Ун2", "К1-Ум2", "К1-Ван2", "К1-Мой2",
                "К1-ОтвСт2", "К1-ТрСт2", "К2-Вр2", "К2-ОтвСт2", "К2-ТрСт2",
            }
            and not (row.system == "K1" and row.kind == "revision" and row.section_id == "К1-Ст2")
            and not (row.system == "K2" and row.kind == "revision" and row.section_id == "К2-Ст2")
        ]
        elements = project.sewage.elements
        k1_outlet.from_node = "К1-Ст1"
        k2_outlet.from_node = "К2-Ст1"
        next(row for row in elements if row.element_id == "К1-ОтвСт1").connects_to = "К1-Вып1"
        cleanout = next(row for row in elements if row.element_id == "К1-ПрНП1")
        cleanout.section_id = "К1-Вып1"
        k1_transition.section_id = "К1-Вып1"
        k1_transition.connects_to = "К1-Ст1"
        next(row for row in elements if row.element_id == "К2-ОтвСт1").connects_to = "К2-Вып1"
        cleanout = next(row for row in elements if row.element_id == "К2-ПрНП1")
        cleanout.section_id = "К2-Вып1"
        k2_transition.section_id = "К2-Вып1"
        k2_transition.connects_to = "К2-Ст1"
        return project

    for index in range(3, count + 1):
        riser = deepcopy(k1_riser_template)
        for field in ("section_id", "from_node", "to_node", "room"):
            setattr(riser, field, _replace_index(getattr(riser, field), 2, index))
        pipes.append(riser)
        for template in k1_branch_templates:
            row = deepcopy(template)
            for field in ("section_id", "from_node", "to_node", "room"):
                setattr(row, field, _replace_index(getattr(row, field), 2, index))
            pipes.append(row)
        for template in k1_fixture_templates:
            row = deepcopy(template)
            for field in (
                "element_id", "section_id", "connects_to", "room_number", "room_name",
            ):
                setattr(row, field, _replace_index(getattr(row, field), 2, index))
            elements.append(row)
        for template in k1_revision_templates:
            row = deepcopy(template)
            for field in ("element_id", "section_id", "room_name"):
                setattr(row, field, _replace_index(getattr(row, field), 2, index))
            row.layout_column = index
            elements.append(row)
        elbow = deepcopy(k1_elbow_template)
        elbow.element_id = f"К1-ОтвСт{index}"
        elbow.section_id = f"К1-Ст{index}"
        elements.append(elbow)
        tee = deepcopy(k1_tee_template)
        tee.element_id = f"К1-ТрСт{index}"
        tee.connects_to = f"К1-Ст{index}"
        elements.append(tee)

        riser = deepcopy(k2_riser_template)
        for field in ("section_id", "from_node", "to_node", "room"):
            setattr(riser, field, _replace_index(getattr(riser, field), 2, index))
        pipes.append(riser)
        funnel = deepcopy(k2_funnel_template)
        for field in ("element_id", "section_id", "connects_to", "room_name"):
            setattr(funnel, field, _replace_index(getattr(funnel, field), 2, index))
        elements.append(funnel)
        for template in k2_revision_templates:
            row = deepcopy(template)
            for field in ("element_id", "section_id", "connects_to", "room_name"):
                setattr(row, field, _replace_index(getattr(row, field), 2, index))
            row.layout_column = index + count
            elements.append(row)
        elbow = deepcopy(k2_elbow_template)
        elbow.element_id = f"К2-ОтвСт{index}"
        elbow.section_id = f"К2-Ст{index}"
        elements.append(elbow)
        tee = deepcopy(k2_tee_template)
        tee.element_id = f"К2-ТрСт{index}"
        tee.connects_to = f"К2-Ст{index}"
        elements.append(tee)

    pipes[:] = [
        row for row in pipes
        if not (row.system in {"K1", "K2"} and "магистраль" in row.purpose)
    ]
    for index in range(1, count):
        row = deepcopy(k1_collector_template)
        row.section_id = f"К1-М{index}"
        row.from_node = f"К1-Ст{index}"
        row.to_node = f"К1-Ст{index+1}"
        if index > 1:
            row.nominal_diameter_mm = 150
            row.outer_diameter_mm = 160.0
            row.wall_thickness_mm = 4.9
        pipes.append(row)
        row = deepcopy(k2_collector_template)
        row.section_id = f"К2-М{index}"
        row.from_node = f"К2-Ст{index}"
        row.to_node = f"К2-Ст{index+1}"
        if index > 1:
            row.nominal_diameter_mm = 150
            row.outer_diameter_mm = 160.0
            row.wall_thickness_mm = 9.5
        pipes.append(row)
    k1_outlet.from_node = f"К1-Ст{count}"
    k2_outlet.from_node = f"К2-Ст{count}"

    for index in range(1, count + 1):
        k1_outgoing = f"К1-М{index}" if index < count else "К1-Вып1"
        k2_outgoing = f"К2-М{index}" if index < count else "К2-Вып1"
        next(row for row in elements if row.element_id == f"К1-ОтвСт{index}").connects_to = k1_outgoing
        next(row for row in elements if row.element_id == f"К2-ОтвСт{index}").connects_to = k2_outgoing
        if index == 1:
            cleanout = next(row for row in elements if row.element_id == "К1-ПрНП1")
            cleanout.section_id = k1_outgoing
            cleanout = next(row for row in elements if row.element_id == "К2-ПрНП1")
            cleanout.section_id = k2_outgoing
        else:
            tee = next(row for row in elements if row.element_id == f"К1-ТрСт{index}")
            tee.section_id = k1_outgoing
            tee.dn_mm = 150
            tee.type_mark = "DN150×100; 45°; без заглушки"
            tee = next(row for row in elements if row.element_id == f"К2-ТрСт{index}")
            tee.section_id = k2_outgoing
            tee.dn_mm = 150
            tee.type_mark = "DN150×100; 45°; PN10; без заглушки"
    k1_transition.section_id = "К1-М2" if count > 2 else "К1-Вып1"
    k1_transition.connects_to = "К1-Ст2"
    k2_transition.section_id = "К2-М2" if count > 2 else "К2-Вып1"
    k2_transition.connects_to = "К2-Ст2"
    return project


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
    assert [
        tuple((revision.element_id, revision.floor_no, revision.elevation_m)
              for revision in row.revisions)
        for row in result.k2_risers
    ] == [
        (("К2-Р1-Н", 1, 0.8), ("К2-Р1-40", 14, 39.8)),
        (("К2-Р2-Н", 1, 0.8), ("К2-Р2-40", 14, 39.8)),
    ]
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
    assert result.k2_collectors[0].dn_mm == 100
    assert result.k2_outlet.section_id == "К2-Вып1"
    assert result.k2_outlet.dn_mm == 150
    assert [
        (row.node_id, row.section_id, row.placement)
        for row in result.k2_transitions
    ] == [("К2-Ст2", "К2-Вып1", "upstream-before-junction")]


def test_building_resolver_rejects_k2_transition_after_first_equal_dn_node():
    project = _demo_project()
    transition = next(
        row for row in project.sewage.elements
        if row.element_id == "К2-Пер1"
    )
    transition.section_id = "К2-М1"
    transition.connects_to = "К2-Ст1"

    result = resolve_wastewater_building_project_inputs(project)

    assert not result.complete
    assert result.k2_transitions == ()
    assert any(
        "К2-Пер1" in row and "отдельный переход" in row
        for row in result.diagnostics
    )


@pytest.mark.parametrize("count", (1, 2, 5))
def test_registry_chain_supports_one_two_and_many_risers(count):
    project = _project_with_linear_riser_count(count)
    project.sewage.pipes.reverse()  # порядок строк не должен управлять трассой

    inputs = resolve_wastewater_building_project_inputs(project)

    assert inputs.complete, inputs.diagnostics
    assert [row.stack.riser_id for row in inputs.k1_risers] == [
        f"К1-Ст{index}" for index in range(1, count + 1)
    ]
    assert [row.riser_id for row in inputs.k2_risers] == [
        f"К2-Ст{index}" for index in range(1, count + 1)
    ]
    assert len(inputs.k1_collectors) == max(0, count - 1)
    assert len(inputs.k2_collectors) == max(0, count - 1)


def test_five_risers_are_paginated_without_losing_topology():
    project = _project_with_linear_riser_count(5)
    inputs = resolve_wastewater_building_project_inputs(project)
    assembly = build_wastewater_building_assembly(
        inputs,
        floor_height_m=3.0,
        roof_kind="flat_non_accessible",
    )

    svgs = build_wastewater_building_svgs(assembly)
    joined = "".join(svgs)

    assert len(svgs) == 5  # три надземных фрагмента + два подвальных
    assert audit_wastewater_building_svgs(assembly, svgs) == ()
    assert joined.count('data-sheet-total="6"') == 5
    assert joined.count('data-basement-cleanout=') == 2
    assert joined.count('data-basement-through-junction=') == 8
    assert joined.count('data-building-transition="К1-Пер1"') == 1
    assert joined.count('data-building-transition="К2-Пер1"') == 1
    assert all("продолжение на листе 4" in svg for svg in svgs[:2])
    assert "продолжение на листе 5" in svgs[2]
    for system in ("К1", "К2"):
        for index in range(1, 6):
            assert f"{system}-Ст{index}" in joined


def test_five_riser_pdf_has_five_a1_pages(tmp_path):
    output = tmp_path / "five-risers.pdf"

    generate_wastewater_building_pdf_from_project(
        str(output),
        _project_with_linear_riser_count(5),
        floor_height_m=3.0,
        roof_kind="flat_non_accessible",
    )

    pages = PdfReader(str(output)).pages
    assert len(pages) == 5
    assert all(
        float(page.mediabox.width) * 25.4 / 72 == pytest.approx(841.0, abs=0.1)
        and float(page.mediabox.height) * 25.4 / 72 == pytest.approx(594.0, abs=0.1)
        for page in pages
    )


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


def test_combined_floors_sheet_uses_shared_grid_and_registered_k2_revisions():
    floors_svg, _ = build_wastewater_building_svgs(_demo_assembly())
    root = ElementTree.fromstring(floors_svg)

    assert root.get("width") == "841mm"
    assert root.get("height") == "594mm"
    assert root.get("viewBox") == "0 0 2803.333 1980.000"
    assert root.get("data-sheet-format") == "A1"
    assert root.get("data-sheet-units") == "mm"
    assert root.get("data-schematic-scale") == "not-to-scale"
    assert root.get("data-font-standard") == "GOST-2.304-81"
    frame = next(
        row for row in root.iter()
        if row.get("data-drawing-frame") == "GOST-R-21.101"
    )
    scale = 10.0 / 3.0
    assert float(frame.get("x")) == pytest.approx(20.0 * scale, abs=0.1)
    assert float(frame.get("y")) == pytest.approx(5.0 * scale, abs=0.1)
    assert float(frame.get("x")) + float(frame.get("width")) == pytest.approx(
        841.0 * scale - 5.0 * scale,
        abs=0.1,
    )
    assert floors_svg.count('data-title-block="form-3"') == 1
    assert 'data-sheet-no="1" data-sheet-total="3"' in floors_svg
    assert floors_svg.count('data-floor-assembly="') == 6
    assert floors_svg.count('data-building-floor="') == 3
    assert 'data-floor-assembly="К1-Ст1-Сборка-Этаж-16"' in floors_svg
    assert 'data-floor-assembly="К1-Ст2-Сборка-Этаж-16"' in floors_svg
    assert floors_svg.count('data-ugo="roof_funnel_heated"') == 2
    assert "К2-Вр1" in floors_svg and "2 шт.; DN100" in floors_svg
    assert floors_svg.count('data-building-revision="К1-') == 12
    assert 'data-building-revision="К2-Р1-Н"' in floors_svg
    assert 'data-building-revision="К2-Р2-Н"' in floors_svg
    assert 'data-building-revision="К2-Р1-40"' in floors_svg
    assert 'data-building-revision="К2-Р2-40"' in floors_svg
    assert floors_svg.count('data-floor-reference="clean-floor"') == 16
    assert floors_svg.count('data-height-above-floor-mm="800"') == 4
    assert floors_svg.count('data-height-above-floor-mm="1000"') == 12
    assert floors_svg.count('data-revision-on-break="true"') == 10
    for riser_id in ("К1-Ст1", "К1-Ст2"):
        for floor_no in (1, 4, 7, 10, 13, 16):
            assert f'data-building-revision="{riser_id}-{floor_no}"' in floors_svg
    assert "эт. 14; отм. 39,800" in floors_svg
    assert "К2 ⌀100" in floors_svg
    assert "К2 не соединяется с К1" in floors_svg


def test_combined_basement_uses_exact_edges_transitions_and_outlets_beyond_wall():
    _, basement_svg = build_wastewater_building_svgs(_demo_assembly())
    root = ElementTree.fromstring(basement_svg)

    assert root.get("width") == "841mm"
    assert root.get("height") == "594mm"
    assert basement_svg.count('data-title-block="form-3"') == 1
    assert 'data-sheet-no="2" data-sheet-total="3"' in basement_svg
    for line_id in ("К1-М1", "К1-Вып1", "К2-М1", "К2-Вып1"):
        assert f'data-building-pipe-line="{line_id}"' in basement_svg
        assert f'data-pipe-line-id="{line_id}"' in basement_svg
    assert 'data-building-transition="К1-Пер1"' in basement_svg
    assert 'data-building-transition="К2-Пер1"' in basement_svg
    assert 'data-transition-placement="upstream-before-junction"' in basement_svg
    assert 'data-transition-placement="downstream-after-terminal-turn"' not in basement_svg
    assert basement_svg.count('data-transition-placement="upstream-before-junction"') == 2
    assert basement_svg.count('data-transition-shape="open-triangle"') == 2
    assert basement_svg.count('data-transition-fill="none"') == 2
    assert basement_svg.count('data-flat-side="downstream"') == 2
    assert basement_svg.count('data-apex-side="upstream"') == 2
    assert basement_svg.count('data-transition-joint="direct"') == 2
    assert basement_svg.count('data-fitting-gap-mm="0"') == 2
    assert 'data-adjacent-node="К1-Ст2"' in basement_svg
    assert 'data-adjacent-node="К2-Ст2"' in basement_svg
    assert basement_svg.count('data-fitting="lower_elbow_45"') == 4
    assert basement_svg.count('data-fitting="service_wye_45"') == 2
    assert basement_svg.count('data-fitting="through_wye_45"') == 2
    assert 'data-building-revision="K2' not in basement_svg
    assert basement_svg.count('data-basement-cleanout=') == 2
    assert basement_svg.count('data-cleanout-axis="collinear"') == 2
    assert basement_svg.count('data-basement-through-junction=') == 2
    assert basement_svg.count('data-through-axis="open"') == 2
    assert basement_svg.count('data-fitting="cleanout_cap_fitting"') == 2
    assert basement_svg.count('data-wall-sleeve=') == 2
    assert 'data-wall-sleeve="К1-Вып1"' in basement_svg
    assert 'data-wall-sleeve="К2-Вып1"' in basement_svg
    assert basement_svg.count('data-basement-revision-reference=') == 4
    assert "Ревизия на 1 этаже +1000 — см. лист 1" in basement_svg
    assert "Ревизия на 1 этаже +800 — см. лист 1" in basement_svg
    assert basement_svg.count('data-lower-node-callout=') == 4
    assert basement_svg.count('data-callout-target-kind="cleanout-cap"') == 2
    assert basement_svg.count('data-callout-target-kind="through-wye"') == 2
    assert "косой тройник 45° с заглушкой" in basement_svg
    assert "проходная ось открыта, без заглушки" in basement_svg
    assert "Проточный узел К1-ТрСт2" in basement_svg
    assert "Проточный узел К2-ТрСт2" in basement_svg
    assert basement_svg.count("косой тройник DN150×100, 45°") == 2
    for element_id in ("К1-ПрНП1", "К2-ПрНП1"):
        assert f'data-basement-cleanout="{element_id}"' in basement_svg
    for element_id in ("К1-ТрСт2", "К2-ТрСт2"):
        assert f'data-basement-through-junction="{element_id}"' in basement_svg
    assert 'data-basement-revision="К2-Р1-Н"' not in basement_svg
    assert 'data-basement-revision="К2-Р2-Н"' not in basement_svg
    assert "проточный косой тройник без заглушки" in basement_svg
    assert "за грань здания" in basement_svg
    assert "0,010" in basement_svg
    assert basement_svg.count("0,008") >= 2
    assert "i=" not in basement_svg and "i =" not in basement_svg
    assert basement_svg.count('data-sign-shape="acute-angle"') == 4
    assert basement_svg.count('data-lower-leg-horizontal="true"') == 4
    assert basement_svg.count('data-lower-leg-parallel-to-text="true"') == 4

    for group in (
        row for row in root.iter() if row.get("data-lower-node-callout")
    ):
        target_x = float(group.get("data-callout-target-x"))
        target_y = float(group.get("data-callout-target-y"))
        path = next(row for row in group if row.tag.endswith("path"))
        match = re.match(r"M([\d.]+),([\d.]+)", path.get("d", ""))
        assert match is not None
        assert float(match.group(1)) == pytest.approx(target_x, abs=0.05)
        assert float(match.group(2)) == pytest.approx(target_y, abs=0.05)

    for group in (
        row for row in root.iter() if row.get("data-building-transition")
    ):
        contour = next(
            row for row in group.iter()
            if row.get("data-diameter-transition")
        )
        points = [
            (float(x), float(y))
            for x, y in re.findall(r"[ML]([\d.]+),([\d.]+)", contour.get("d", ""))
        ]
        assert len(points) == 3
        # For the left-to-right basement mains, the flat side is the first
        # and third point at the larger downstream DN; the apex is upstream.
        assert points[0][0] == pytest.approx(points[2][0], abs=0.3)
        assert points[1][0] < points[0][0]


def test_combined_graphic_audit_passes_for_registry_driven_demo():
    assembly = _demo_assembly()
    svgs = build_wastewater_building_svgs(assembly)

    assert audit_wastewater_building_svgs(assembly, svgs) == ()


def test_combined_graphic_audit_rejects_pipe_gap_between_transition_and_junction():
    assembly = _demo_assembly()
    floors_svg, basement_svg = build_wastewater_building_svgs(assembly)
    broken = basement_svg.replace(
        'data-fitting-gap-mm="0"', 'data-fitting-gap-mm="40"', 1
    )

    findings = audit_wastewater_building_svgs(assembly, (floors_svg, broken))

    assert any("must directly adjoin junction" in row for row in findings)


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

    font_names: list[str] = []
    embedded_opengost = False
    for page in pages:
        fonts = page["/Resources"].get("/Font", {})
        for reference in fonts.values():
            font = reference.get_object()
            candidates = [font]
            candidates.extend(
                descendant.get_object()
                for descendant in font.get("/DescendantFonts", [])
            )
            for candidate in candidates:
                font_names.append(str(candidate.get("/BaseFont", "")))
                descriptor = candidate.get("/FontDescriptor")
                if descriptor is not None:
                    descriptor = descriptor.get_object()
                    if (
                        "OpenGOSTtypeB-Regular" in str(candidate.get("/BaseFont", ""))
                        and descriptor.get("/FontFile2") is not None
                    ):
                        embedded_opengost = True
    assert any("OpenGOSTtypeB-Regular" in name for name in font_names)
    assert embedded_opengost
