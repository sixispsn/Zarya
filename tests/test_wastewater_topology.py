from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_topology import build_wastewater_topology


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
