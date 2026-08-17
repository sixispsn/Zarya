from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_topology import (
    GRAVITY_SOURCE_KINDS,
    build_wastewater_topology,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _request():
    return load_request_file(str(DEMO))


def test_demo_topology_uses_explicit_branches_and_graph_edges():
    topology = build_wastewater_topology(build_project(_request()))

    assert topology.ready
    assert len(topology.risers) == 4
    assert len(topology.branches) == 4
    assert len(topology.mains) == 4
    assert {
        (row.pipe.section_id, row.riser_id)
        for row in topology.branches
    } == {
        ("К1-Ветв-Кух1", "К1-Ст1"),
        ("К1-Ветв-СУ1", "К1-Ст1"),
        ("К1-Ветв-СУ2", "К1-Ст2"),
        ("К1-Ветв-Кух2", "К1-Ст2"),
    }
    assert {
        (row.section_id, row.from_node, row.to_node)
        for row in topology.mains
    } >= {
        ("К1-М1", "К1-Ст1", "К1-Ст2"),
        ("К1-Вып1", "К1-Ст2", "КК-1"),
    }
    sanitary = next(
        row for row in topology.branches
        if row.pipe.section_id == "К1-Ветв-СУ1"
    )
    assert sanitary.source_element_id == "К1-Ум1"
    assert [row.element_id for row in sanitary.elements] == [
        "К1-Ум1",
        "К1-Ван1",
        "К1-Ун1",
    ]
    assert sanitary.elements[-1].connects_to == "К1-Ст1"
    assert sanitary.has_toilet


def test_supported_gravity_sources_cover_domestic_appliances():
    assert {
        "toilet",
        "washbasin",
        "sink",
        "bath",
        "shower",
        "floor_drain",
        "washing_machine",
        "dishwasher",
    } <= GRAVITY_SOURCE_KINDS
    assert "trap" not in GRAVITY_SOURCE_KINDS
    assert "grease_trap" not in GRAVITY_SOURCE_KINDS


def test_disconnected_riser_is_rejected_instead_of_drawn_by_proximity():
    request = _request()
    main = next(row for row in request.sewer_pipes if row.section_id == "К1-М1")
    main.from_node = "Неизвестный-узел"

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any("К1-Ст1: стояк не связан" in row for row in topology.errors)


def test_fixture_directly_on_riser_is_rejected():
    request = _request()
    fixture = next(row for row in request.sewer_elements if row.element_id == "К1-Ун1")
    fixture.section_id = "К1-Ст1"

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any("непосредственно к стояку" in row for row in topology.errors)


def test_outlet_requires_relative_and_absolute_elevations():
    project = build_project(_request())
    outlet = next(row for row in project.sewage.pipes if row.section_id == "К1-Вып1")
    outlet.absolute_elevation_end_m = None

    topology = build_wastewater_topology(project)

    assert not topology.ready
    assert any("относительные и абсолютные отметки" in row for row in topology.errors)


def test_branch_cannot_start_from_an_air_node():
    request = _request()
    branch = next(
        row for row in request.sewer_pipes
        if row.section_id == "К1-Ветв-СУ1"
    )
    branch.from_node = "К1-СУ1"

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any(
        "from_node должен совпадать с первым приёмником стоков К1-Ум1" in row
        for row in topology.errors
    )


def test_toilet_must_be_last_fixture_before_riser():
    request = _request()
    washbasin = next(row for row in request.sewer_elements if row.element_id == "К1-Ум1")
    bath = next(row for row in request.sewer_elements if row.element_id == "К1-Ван1")
    toilet = next(row for row in request.sewer_elements if row.element_id == "К1-Ун1")
    washbasin.connects_to = toilet.element_id
    toilet.connects_to = bath.element_id
    bath.connects_to = "К1-Ст1"

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any(
        "К1-Ун1: унитаз должен быть последним прибором перед стояком К1-Ст1"
        in row
        for row in topology.errors
    )


def test_self_flowing_pipe_cannot_rise_without_explicit_pump():
    request = _request()
    main = next(row for row in request.sewer_pipes if row.section_id == "К1-М1")
    main.elevation_end_m = 0.0

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any(
        "К1-М1: самотечный участок должен понижаться" in row
        for row in topology.errors
    )


def test_every_riser_needs_directed_path_to_confirmed_outlet():
    request = _request()
    outlet = next(row for row in request.sewer_pipes if row.section_id == "К1-Вып1")
    outlet.from_node = "Изолированный-узел"

    topology = build_wastewater_topology(build_project(request))

    assert not topology.ready
    assert any(
        "по направлению стоков нет непрерывного пути до выпуска" in row
        for row in topology.errors
    )
    assert any("не получают стоки ни от одного стояка" in row for row in topology.errors)
