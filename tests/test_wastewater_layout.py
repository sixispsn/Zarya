from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_layout import (
    PointMm,
    RectMm,
    WastewaterElementPlacement,
    WastewaterFloorGroup,
    WastewaterLayoutMode,
    WastewaterNodePlacement,
    WastewaterRoutePlacement,
    WastewaterSchemeLayout,
    WastewaterSlab,
    audit_wastewater_layout,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def _valid_layout() -> WastewaterSchemeLayout:
    groups = [
        WastewaterFloorGroup(
            group_id=f"floor-{floor}",
            label=f"{floor} этаж",
            floors=(floor,),
            elevation_m=(floor - 1) * 3.0,
            y_mm=500.0 - floor * 20.0,
            source_ref="АР: этажность; building.height_m / floors",
        )
        for floor in range(1, 17)
    ]
    group = groups[0]
    start = WastewaterNodePlacement(
        placement_id="node-kitchen-1",
        node_id="К1-Мой1",
        system="K1",
        point=PointMm(100.0, 180.0),
        group_id=group.group_id,
        source_ref="sewer_pipes:К1-Ветв-Кух1.from_node",
    )
    end = WastewaterNodePlacement(
        placement_id="node-riser-1",
        node_id="К1-Ст1",
        system="K1",
        point=PointMm(220.0, 180.0),
        group_id=group.group_id,
        kind="riser",
        source_ref="sewer_pipes:К1-Ветв-Кух1.to_node",
    )
    route = WastewaterRoutePlacement(
        route_id="route-kitchen-1",
        section_id="К1-Ветв-Кух1",
        system="K1",
        from_placement_id=start.placement_id,
        to_placement_id=end.placement_id,
        points=(start.point, PointMm(180.0, 180.0), end.point),
        group_id=group.group_id,
        source_ref="sewer_pipes:К1-Ветв-Кух1",
    )
    element = WastewaterElementPlacement(
        placement_id="fixture-sink-1",
        element_id="К1-Мой1",
        point=PointMm(100.0, 165.0),
        group_id=group.group_id,
        source_ref="sewer_elements:К1-Мой1; АР: типовой этаж",
    )
    return WastewaterSchemeLayout(
        mode=WastewaterLayoutMode.STANDALONE,
        floor_groups=groups,
        nodes=[start, end],
        routes=[route],
        elements=[element],
    )


def test_layout_is_ready_only_when_geometry_is_linked_to_project_registry():
    audit = audit_wastewater_layout(_project(), _valid_layout())
    assert audit.ready
    assert audit.errors == []
    assert audit.warnings == []


def test_layout_rejects_invented_sections_elements_and_mismatched_endpoints():
    layout = _valid_layout()
    route = layout.routes[0]
    layout.routes[0] = WastewaterRoutePlacement(
        route_id=route.route_id,
        section_id="К1-НЕСУЩЕСТВУЮЩИЙ",
        system=route.system,
        from_placement_id=route.from_placement_id,
        to_placement_id=route.to_placement_id,
        points=(PointMm(101.0, 180.0), route.points[-1]),
        group_id=route.group_id,
        source_ref=route.source_ref,
    )
    placement = layout.elements[0]
    layout.elements[0] = WastewaterElementPlacement(
        placement_id=placement.placement_id,
        element_id="К1-НЕСУЩЕСТВУЮЩИЙ",
        point=placement.point,
        group_id=placement.group_id,
        source_ref=placement.source_ref,
    )

    audit = audit_wastewater_layout(_project(), layout)
    codes = {row.code for row in audit.errors}
    assert not audit.ready
    assert "route.section" in codes
    assert "route.endpoint" in codes
    assert "element.registry" in codes


def test_layout_rejects_reversed_project_topology_and_unproved_geometry():
    layout = _valid_layout()
    route = layout.routes[0]
    layout.routes[0] = WastewaterRoutePlacement(
        route_id=route.route_id,
        section_id=route.section_id,
        system=route.system,
        from_placement_id=route.to_placement_id,
        to_placement_id=route.from_placement_id,
        points=(route.points[-1], route.points[0]),
        group_id=route.group_id,
        source_ref="",
    )

    audit = audit_wastewater_layout(_project(), layout)
    codes = [row.code for row in audit.errors]
    assert codes.count("route.topology") == 2
    assert "route.source" in codes


def test_architecture_underlay_mode_requires_a_confirmed_underlay():
    layout = _valid_layout()
    layout.mode = WastewaterLayoutMode.ARCHITECTURE_UNDERLAY

    audit = audit_wastewater_layout(_project(), layout)
    assert any(row.code == "underlay.missing" for row in audit.errors)


def test_every_floor_must_have_its_own_band_without_omissions():
    layout = _valid_layout()
    layout.floor_groups = [
        WastewaterFloorGroup(
            group_id="typical",
            label="Этажи 1-16",
            floors=tuple(range(1, 17)),
            elevation_m=0.0,
            y_mm=180.0,
            source_ref="АР: типовые этажи",
        )
    ]

    audit = audit_wastewater_layout(_project(), layout)
    assert any(row.code == "floor_group.individual" for row in audit.errors)

    layout = _valid_layout()
    layout.floor_groups.pop(7)
    audit = audit_wastewater_layout(_project(), layout)
    assert any(
        row.code == "floor.coverage" and "8" in row.message
        for row in audit.errors
    )


def test_basement_requires_one_diagonally_hatched_foundation_slab():
    layout = _valid_layout()
    layout.floor_groups.append(WastewaterFloorGroup(
        group_id="basement",
        label="Подвал",
        floors=(0,),
        elevation_m=-3.0,
        y_mm=520.0,
        kind="basement",
        source_ref="АР: разрез",
    ))

    audit = audit_wastewater_layout(_project(), layout)
    assert any(row.code == "slab.foundation_missing" for row in audit.errors)

    layout.slabs.append(WastewaterSlab(
        slab_id="foundation",
        frame=RectMm(80.0, 520.0, 680.0, 14.0),
        kind="basement_foundation_slab",
        hatch="none",
        source_ref="АР: плита подвала",
    ))
    audit = audit_wastewater_layout(_project(), layout)
    assert any(row.code == "slab.foundation_hatch" for row in audit.errors)

    layout.slabs[0] = WastewaterSlab(
        slab_id="foundation",
        frame=RectMm(80.0, 520.0, 680.0, 14.0),
        kind="basement_foundation_slab",
        hatch="diagonal",
        source_ref="АР: плита подвала",
    )
    assert audit_wastewater_layout(_project(), layout).ready
