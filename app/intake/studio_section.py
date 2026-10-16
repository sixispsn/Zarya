"""Input boundary for a representative section, not a measured sewer network.

No generated graphic lengths, diameters or nodes enter IOS2Request/specification.
The production scheme readiness contract remains independent and strict.
"""
from app.intake.studio_roofs import ROOF_CHOICES, roof_rule
from app.pz.normative import decide_storm_system
from app.pz.wastewater_presentation import RepresentativeSectionInput, SectionMainInput
from app.pz.section_fan import SectionFanInput
from app.pz.section_storm import SectionStormInput
from app.pz.section_main_hydraulics import current_k1_total, current_k1_hourly


def section_fan(values: dict) -> SectionFanInput:
    data = {key: values[f"section_fan_{key}"] for key in SectionFanInput.__dataclass_fields__
            if f"section_fan_{key}" in values}
    if isinstance(data.get("member_ids"), str):
        data["member_ids"] = tuple(x.strip() for x in data["member_ids"].replace(";", ",").split(",") if x.strip())
    for key in ("no_openings_confirmed", "attic_insulated", "plastic_exposed", "uv_protected"):
        if key in data:
            data[key] = {"yes":True, "no":False, "unknown":None}.get(data[key])
    data["building_attic_kind"] = values.get("attic_kind", "unknown")
    if "space" not in data and data["building_attic_kind"] in {"cold", "warm", "technical"}:
        data["space"] = {"cold":"cold_attic", "warm":"warm_attic", "technical":"technical_storey"}[data["building_attic_kind"]]
    return SectionFanInput(**data)


def section_storm(values: dict) -> SectionStormInput:
    return SectionStormInput(city_code=values.get("storm_city", ""),
        roof_type=roof_rule(values.get("roof_type"))["rain_type"],
        roof_area_m2=values.get("storm_roof_area_m2", 0), walls_area_m2=values.get("storm_walls_area_m2", 0),
        selected_riser_dn_mm=values.get("storm_selected_riser_dn_mm", 0),
        risers_count=values.get("storm_risers_count", 0), max_riser_flow_lps=values.get("storm_max_riser_flow_lps"),
        funnels_on_different_levels=values.get("storm_funnels_on_different_levels") == "yes",
        funnels_count=values.get("storm_funnels_count", 0))


def section_main(values: dict, system: str) -> SectionMainInput:
    return SectionMainInput(**{key: values[f"section_{system}_{key}"]
        for key in SectionMainInput.__dataclass_fields__ if f"section_{system}_{key}" in values})


def representative_presentation(values: dict) -> RepresentativeSectionInput:
    """Persist display choices, not a copy of calculated/architectural values."""
    return RepresentativeSectionInput(
        basement_kind=values.get("basement_kind", "unknown"),
        drainage=section_readiness(values)["drainage"] or "unknown",
        k1=section_main(values, "k1"), k2=section_main(values, "k2"),
        fan=section_fan(values),
        funnel_heated={"yes":True, "no":False}.get(values.get("section_funnel_heated")),
        zero_absolute_m=values.get("section_zero_absolute_m"),
        zero_source_ref=values.get("section_zero_source_ref", ""),
    )


def section_readiness(values: dict) -> dict:
    missing = [key for key in ("floors", "consumer_code", "floor_height_m", "basement_kind", "roof_type")
               if key not in values]
    if values.get("basement_kind") in {"basement", "subfloor"} and "basement_floor_m" not in values:
        missing.append("basement_floor_m")
    automatic = decide_storm_system(roof_rule(values.get("roof_type"))["rain_type"], values.get("floors", 0))
    drainage = values.get("section_drainage")
    if not drainage and automatic.system_kind == "internal":
        drainage = "internal"
    if not drainage:
        missing.append("section_drainage")
    limitations = []
    if values.get("roof_type") not in {None, *ROOF_CHOICES}:
        limitations.append("Уточните вид кровли в карточке здания.")
    if values.get("roof_type") == "complex":
        limitations.append("Для составной кровли нужен разрез АР; простой профиль не подставляем.")
    if values.get("floors", 1) > 200:
        limitations.append("Этот предварительный разрез поддерживает до 200 надземных этажей.")
    return {"ready": not missing and not limitations, "missing": missing,
            "limitations": limitations, "drainage": drainage,
            "mode": "representative", "release_ready": False, "takeoff_eligible": False}


def section_model(values: dict):
    from app.pz.residential_concept_section import ResidentialConceptSection

    status = section_readiness(values)
    if not status["ready"]:
        raise ValueError("Для разреза уточните: " + ", ".join(status["missing"] + status["limitations"]))
    return ResidentialConceptSection(
        floors=values["floors"], floor_height_m=values["floor_height_m"],
        basement_kind=values["basement_kind"],
        basement_floor_m=values.get("basement_floor_m") if values["basement_kind"] != "none" else None,
        roof_kind=values["roof_type"], drainage=status["drainage"],
        consumer_code=values["consumer_code"],
        title=values.get("object_name", "Жилой дом"),
        k1=section_main(values, "k1"), k2=section_main(values, "k2"),
        fan=section_fan(values),
        funnel_heated={"yes":True, "no":False}.get(values.get("section_funnel_heated")),
        storm=section_storm(values),
        zero_absolute_m=values.get("section_zero_absolute_m"),
        zero_source_ref=values.get("section_zero_source_ref", ""),
        k1_total_flow_lps=current_k1_total(
            [(values["consumer_code"], values["residents"])] if "residents" in values else [],
            values.get("sewage_max_fixture_lps")),
        k1_hour_max_m3h=current_k1_hourly(
            [(values["consumer_code"], values["residents"])] if "residents" in values else []),
        k1_fixture_max_lps=values.get("sewage_max_fixture_lps"),
    )
