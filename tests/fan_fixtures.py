"""Explicit TEST-ONLY confirmations; never added to project/demo defaults."""
from app.pz.wastewater_topology import build_wastewater_topology
from app.pz.wastewater_ventilation import FanTerminal, FanVentilationInput


def confirm_independent_fans(project):
    project.sewage.fan_ventilation = FanVentilationInput(terminals=tuple(
        FanTerminal(
            terminal_id=f"test-vent-{rid}", riser_ids=(rid,), kind="roof",
            source_ref="Синтетическая подтверждённая АР для unit-test",
            height_m=.2, diameter_mm=pipe.nominal_diameter_mm,
            opening_distance_m=4., open_end_confirmed=True,
            separate_from_other_systems=True, plastic_exposed=True, uv_protected=True,
        )
        for rid, pipe in build_wastewater_topology(project).risers.items()
        if pipe.system == "K1"
    ))
    return project
