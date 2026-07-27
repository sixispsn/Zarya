"""Применимость СП 54/118/253 и обязательные проектные решения.

Модуль не рассчитывает расходы, потери или напоры. Расчётное ядро В1/В2/Т3/Т4
остаётся в legacy; здесь формируется только нормативный профиль объекта.
"""
from __future__ import annotations

from app.pz.project import (
    BuildingFlags,
    BuildingPurpose,
    GreaseTrapDesign,
    NormativeRequirements,
    StormDesign,
)


def derive_requirements(
    building: BuildingFlags,
    consumer_codes: list[str],
    owner_groups_count: int = 1,
) -> NormativeRequirements:
    purposes = {
        "residential" if code.startswith("residential_") else "public"
        for code in consumer_codes if code
    }
    if building.purpose == BuildingPurpose.RESIDENTIAL:
        purposes.add("residential")
    elif building.purpose == BuildingPurpose.PUBLIC:
        purposes.add("public")

    mixed = len(purposes) > 1
    residential = "residential" in purposes
    public = "public" in purposes
    high_rise = (
        (residential and building.height_m > 75)
        or (public and building.height_m > 50)
    )

    refs = []
    if residential and building.height_m <= 75:
        refs.append("СП 54.13330.2022, п. 6.2.4.3")
    if public:
        refs.extend(("СП 118.13330.2022, пп. 8.3–8.7", "СП 118.13330.2022, п. 8.24"))
    if high_rise:
        refs.extend((
            "СП 253.1325800.2016, п. 10.3",
            "СП 253.1325800.2016, п. 10.15",
            "СП 253.1325800.2016, пп. 10.23, 10.25, 10.27",
        ))

    return NormativeRequirements(
        sp54_applicable=residential and building.height_m <= 75,
        sp118_applicable=public,
        sp253_applicable=high_rise,
        mixed_use=mixed,
        separate_v1_v2_required=high_rise,
        apartment_hose_tap_required=residential and building.height_m <= 75,
        hvs_min_insulation_mm=10 if high_rise else 0,
        gvs_min_insulation_mm=25 if high_rise else 0,
        frequency_drive_required=high_rise,
        pump_full_reserve_required=high_rise,
        pump_dispatch_required=high_rise,
        separate_k1_required=high_rise and mixed,
        separate_owner_metering_required=public and owner_groups_count > 1,
        references=refs,
    )


def decide_storm_system(roof_type: str, floors: int) -> StormDesign:
    design = StormDesign(roof_type=roof_type)
    if roof_type == "not_set":
        design.system_note = "Тип кровли не задан; решение К2 требует исходных данных АР."
    elif roof_type == "flat":
        if floors >= 3:
            design.system_kind = "internal"
            design.system_note = (
                "Предусмотреть внутренний водосток К2 "
                "(СП 118.13330.2022, п. 8.4)."
            )
        else:
            design.system_kind = "external_or_internal"
            design.system_note = (
                "Для плоской кровли здания до двух этажей допустим наружный водосток "
                "при выполнении условий СП 118.13330.2022, п. 8.6; окончательное "
                "решение принимается по АР."
            )
    elif roof_type == "sloped":
        if floors <= 2:
            design.system_kind = "unorganized_or_organized"
            design.system_note = (
                "Неорганизованный водосток допустим только при ограничениях "
                "СП 118.13330.2022, п. 8.3; иначе предусмотреть организованный."
            )
        elif floors <= 5:
            design.system_kind = "organized"
            design.system_note = (
                "Предусмотреть организованный водосток "
                "(СП 118.13330.2022, п. 8.3)."
            )
        elif floors == 6:
            design.system_kind = "internal_or_heated_external"
            design.system_note = (
                "Предусмотреть внутренний водосток; для шестиэтажного здания "
                "допускается наружный организованный водосток с обогревом элементов "
                "(СП 118.13330.2022, п. 8.3)."
            )
        else:
            design.system_kind = "internal"
            design.system_note = (
                "Предусмотреть внутренний водосток "
                "(СП 118.13330.2022, п. 8.3)."
            )
    else:
        raise ValueError("roof_type должен быть not_set, flat или sloped")
    return design


def decide_grease_trap(
    preparation_type: str,
    seats: int,
    conditional_dishes: int,
    school_by_assignment: bool,
) -> GreaseTrapDesign:
    required = (
        (preparation_type == "semi_finished" and seats >= 500)
        or (preparation_type == "raw" and (seats >= 200 or conditional_dishes >= 1500))
        or (preparation_type == "school" and school_by_assignment)
    )
    if required:
        note = (
            "На выпусках производственных стоков предусмотреть жироуловители "
            "(СП 118.13330.2022, п. 8.7). Производительность и число установок "
            "уточнить по технологическому заданию и схеме выпусков на стадии Р."
        )
    elif preparation_type == "none":
        note = "Предприятие общественного питания в исходных данных не задано."
    else:
        note = (
            "Порог обязательной установки жироуловителей по СП 118.13330.2022, "
            "п. 8.7 не достигнут либо требование задания на проектирование не задано."
        )
    return GreaseTrapDesign(
        preparation_type=preparation_type,
        seats=seats,
        conditional_dishes=conditional_dishes,
        school_by_assignment=school_by_assignment,
        required=required,
        decision_note=note,
    )
