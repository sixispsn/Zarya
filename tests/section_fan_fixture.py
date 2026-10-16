"""Synthetic fan alternative on the accepted house; never write it to its YAML."""
from pathlib import Path

from app.intake.yaml_io import load_request_file
from app.pz.small_residential_fan_binding import SectionFanBinding
from app.pz.small_residential_preview import build_small_residential_preview
from app.pz.wastewater_basement_profile import basement_profile_from_request
from app.pz.wastewater_fan_drafting import FanDetailsInput
from app.pz.wastewater_fan_geometry import FanGeometryInput, FanRiserPosition, FanRoofDetail
from app.pz.wastewater_ventilation import FanRiser, FanTerminal, FanVentilationInput


def section_fan_fixture():
    req = load_request_file(str(Path(__file__).parents[1]/"demo/residential_2floors_8apartments.yaml"))
    model = build_small_residential_preview(
        req, basement=basement_profile_from_request(
            req, proposed_invert_m=-2.2, proposed_invert_basis="Предварительный предел по морозу", preview_dn_mm=100,
        ), source_ref="Исходные планы; контрольная компоновка", proposed_shafts=4,
        branch_outer_mm=50, stack_outer_mm=110, include_roof=True,
    )
    ids = tuple(f"К1-{i}" for i in range(1, 5))
    basis = "Синтетические исходные данные для контроля адаптера; не решение рабочего проекта"
    evidence = FanVentilationInput((FanTerminal(
        "К1-Вент1", ids, kind="roof", source_ref=basis,
        height_m=.2, diameter_mm=100, collector_diameter_mm=100,
        opening_distance_m=4, open_end_confirmed=True,
        separate_from_other_systems=True, condensate_drains_to_risers=True,
        cold_attic=False, plastic_exposed=True, uv_protected=True,
    ),), external_ventilation_verified=True, external_ventilation_ref=basis)
    detail = FanRoofDetail(
        "К1-Вент1", 6.6,
        tuple(FanRiserPosition(rid, i*2.5, 4.8, 5.4+i*.05) for i, rid in enumerate(ids)),
        "К1-4", "К1-1", basis,
    )
    data = FanDetailsInput(
        "flat_non_accessible", tuple(FanRiser(rid, 100, "ventilated", "К1-Вып1") for rid in ids),
        evidence, (detail,), (),
    )
    return model, SectionFanBinding(data, FanGeometryInput((detail,), (), True, basis))
