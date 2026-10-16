"""Explicit synthetic building for cross-page fan binding regression/preview."""
from copy import deepcopy
from dataclasses import replace

from scripts.build_fan_details import control_fan_details
from tests.test_wastewater_building_drafting import _project_with_linear_riser_count


def fan_binding_fixture():
    project = _project_with_linear_riser_count(5)
    project.building.floors_above = 2
    project.building.height_m = 6.6
    project.sewage.floor_height_m = 3.3
    project.sewage.roof_kind = "flat_accessible"
    project.sewage.roof_relative_elevation_m = 6.6
    project.document.object_name = "Контроль привязки фановых узлов (синтетический пример)"
    project.document.cipher = "FAN-BIND-CONTROL"
    template = deepcopy(project.sewage.risers[0])
    project.sewage.risers = []
    for i in range(1, 6):
        r = deepcopy(template)
        r.riser_id = f"К1-Ст{i}"
        r.ventilation = "vacuum_valve" if i == 5 else "ventilated"
        r.working_height_m = 6.6
        project.sewage.risers.append(r)
    project.sewage.elements = [e for e in project.sewage.elements if e.kind != "revision" or e.floor_from in (1, 16)]
    for e in project.sewage.elements:
        e.floor_to = min(e.floor_to, 2) if e.floor_to else e.floor_to
        if e.typical_quantity is not None:
            e.quantity = e.typical_quantity * 2
        if e.floor_from == 16:
            e.floor_from = 2
            e.elevation_m = 4.3
        if e.floor_from and e.floor_from > 2:
            e.floor_from = 2
        if e.kind == "roof_funnel":
            e.elevation_m = 6.6
    for p in project.sewage.pipes:
        if p.section_id.startswith(("К1-Ст", "К2-Ст")):
            p.elevation_start_m = 6.6 if p.system == "K2" else (4.5 if p.section_id == "К1-Ст5" else 4.4)
            p.length_m = p.elevation_start_m - (p.elevation_end_m or 0)
    data = control_fan_details()
    data = replace(data, risers=tuple(replace(r, outlet_id="КК-1") for r in data.risers),
                   roofs=tuple(replace(d, risers=tuple(replace(r, lower_port_m=4.4) for r in d.risers)) for d in data.roofs))
    project.sewage.fan_ventilation = data.evidence
    return project, data


def fan_binding_request_fixture():
    """Persistable counterpart of the same synthetic control, never user data."""
    from dataclasses import fields
    from app.intake.request_dto import SewageRiserRequest, SewerElementRequest, SewerPipeRequest
    from app.intake.yaml_io import load_request_file
    from app.pz.wastewater_fan_geometry import FanGeometryInput
    from tests.test_wastewater_building_drafting import DEMO

    project, data = fan_binding_fixture()
    req = load_request_file(str(DEMO))

    def rows(values, cls):
        return [cls(**{f.name: getattr(row, f.name) for f in fields(cls)}) for row in values]

    return replace(
        req, document=replace(req.document, object_name=project.document.object_name,
                              cipher=project.document.cipher),
        floors=2, building_height_m=6.6, fire_height_m=6.6,
        floor_elevations_m={1: 0., 2: 3.3},
        wastewater_floor_height_m=3.3, wastewater_roof_kind='flat_accessible',
        wastewater_roof_relative_elevation_m=6.6,
        wastewater_fan_ventilation=data.evidence,
        wastewater_fan_geometry=FanGeometryInput(data.roofs, data.valves, True, 'Синтетический контроль привязки'),
        sewage_risers=rows(project.sewage.risers, SewageRiserRequest),
        sewer_pipes=rows(project.sewage.pipes, SewerPipeRequest),
        sewer_elements=rows(project.sewage.elements, SewerElementRequest),
        # The five-stack graphic control does not define a transient model;
        # don't copy the two-stack demo's dynamic junctions into this fixture.
        sewer_internal_nodes=[],
    )
