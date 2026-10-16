"""Optional K1 metering and indoor leak/maintenance collection requirements.

Intent only: no hydraulic calculation, equipment selection or invented geometry.
User scope, 2026-10-14: settings/requirements only; no sump balance yet.
Normative trace and boundaries: docs/wastewater_service_2026-10-14.md.
"""
from dataclasses import asdict, dataclass, fields


METER_REGIMES = {"gravity": "Самотечный участок", "pressure": "Напорный участок"}
SUMP_ROOMS = {
    "pump_room": "Насосная",
    "meter_room": "Узел учёта воды / тепловой энергии",
    "itp": "ИТП",
    "technical_subfloor": "Техническое подполье",
    "used_basement": "Эксплуатируемый подвал",
    "supply_ventilation": "Приточная венткамера",
    "other": "Другое помещение · требуется отдельная проверка",
}
RESERVE_LOCATIONS = {"installed": "Установлен рядом с рабочим", "warehouse": "Хранится на складе"}
WAREHOUSE_ALLOWED = {"technical_subfloor", "used_basement"}
SP_REFERENCE = "СП 30.13330.2020, пп. 20.13–20.15; п. 20.14 с изменением № 4"
SCOPE = "Только утечки и вода от обслуживания. Без грунтового дренажа, фекальных стоков и воды от пожаротушения."


@dataclass
class WastewaterServiceInput:
    k1_metering_enabled: bool = False
    k1_metering_location: str = ""
    k1_metering_regime: str = ""
    k1_metering_basis: str = ""
    sump_enabled: bool = False
    sump_room: str = ""
    sump_location: str = ""
    sump_reserve_location: str = ""
    sump_discharge_note: str = ""
    sump_basis: str = ""

    def validate(self) -> list[str]:
        errors = []
        choices = {"k1_metering_regime": METER_REGIMES, "sump_room": SUMP_ROOMS,
                   "sump_reserve_location": RESERVE_LOCATIONS}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("_enabled"):
                if type(value) is not bool:
                    errors.append(f"{field.name}: требуется true/false")
            elif not isinstance(value, str) or len(value) > 200:
                errors.append(f"{field.name}: требуется текст до 200 символов")
            elif field.name in choices and value and value not in choices[field.name]:
                errors.append(f"{field.name}: неизвестный вариант")
        return errors


def from_dict(data=None) -> WastewaterServiceInput:
    if data is None:
        return WastewaterServiceInput()
    if not isinstance(data, dict):
        raise ValueError("sewage.service: требуется объект параметров")
    unknown = set(data) - {f.name for f in fields(WastewaterServiceInput)}
    if unknown:
        raise ValueError("sewage.service: неизвестные поля: " + ", ".join(sorted(unknown)))
    result = WastewaterServiceInput(**data)
    if errors := result.validate():
        raise ValueError("; ".join(errors))
    return result


def from_studio(values: dict) -> WastewaterServiceInput:
    data = {}
    for f in fields(WastewaterServiceInput):
        key = "sewer_service_" + f.name
        if key in values:
            data[f.name] = values[key] == "yes" if f.name.endswith("_enabled") else values[key]
    return from_dict(data)


def assess(data: WastewaterServiceInput) -> dict:
    """Always recompute requirements; saved choices are not approved designs."""
    errors = data.validate()
    meter = {"enabled": data.k1_metering_enabled, "title": "Узел учёта К1",
             "status": "needs_design" if data.k1_metering_enabled else "disabled",
             "settings": [], "requirements": [], "errors": [], "reference": "Документация изготовителя выбранного расходомера"}
    sump = {"enabled": data.sump_enabled, "title": "Приямок · утечки и обслуживание",
            "status": "needs_design" if data.sump_enabled else "disabled",
            "settings": [], "requirements": [], "errors": [], "reference": SP_REFERENCE,
            "duty_pumps_required": None, "reserve_pumps_required": None}
    result = {"input": asdict(data), "meter": meter, "sump": sump}
    if errors:
        for item in (meter, sump):
            if item["enabled"]:
                item.update(status="invalid", errors=errors)
        return result
    if meter["enabled"]:
        meter["settings"] = [
            ("Место установки", data.k1_metering_location.strip() or "Не задано"),
            ("Режим участка", METER_REGIMES.get(data.k1_metering_regime, "Не задан")),
            ("Основание требования", data.k1_metering_basis.strip() or "Не задано"),
        ]
        meter["requirements"] = [
            "Задано требование учёта К1, а не готовый узел. К3 этой опцией не охватывается.",
            "Для подбора нужны диапазон расходов, DN, режим наполнения и условия монтажа.",
            "Модель, прямые участки, доступ для обслуживания и деталировка подтверждаются документацией изготовителя. Универсальный узел не назначен.",
            "Прибор и монтажные детали автоматически в спецификацию не добавляются.",
        ]
    if sump["enabled"]:
        sump["settings"] = [
            ("Помещение", SUMP_ROOMS.get(data.sump_room, "Не задано")),
            ("Место установки", data.sump_location.strip() or "Не задано"),
            ("Размещение резерва", RESERVE_LOCATIONS.get(data.sump_reserve_location, "Не выбрано")),
            ("Условия отвода воды", data.sump_discharge_note.strip() or "Не заданы"),
            ("Основание", data.sump_basis.strip() or "Не задано"),
        ]
        if data.sump_room in SUMP_ROOMS and data.sump_room != "other":
            sump["duty_pumps_required"] = 1
            sump["reserve_pumps_required"] = 0 if data.sump_room == "supply_ventilation" else 1
            reserve = "Один рабочий дренажный насос; резервный по этому пункту не требуется."
            if sump["reserve_pumps_required"]:
                reserve = "Один рабочий и один резервный дренажные насосы."
                if data.sump_room in WAREHOUSE_ALLOWED:
                    reserve += " Резервный допускается хранить на складе."
                else:
                    reserve += " Хранение резерва на складе для этого помещения данным пунктом не предусмотрено."
        else:
            reserve = "Число рабочих и резервных насосов не определено: уточните назначение помещения и применимые требования."
        if data.sump_reserve_location == "warehouse" and data.sump_room not in WAREHOUSE_ALLOWED:
            sump["errors"].append("Хранение резервного насоса на складе допускается здесь только для техподполья и эксплуатируемого подвала; выбранное помещение не подходит.")
        if data.sump_room == "supply_ventilation" and data.sump_reserve_location == "installed":
            reserve += " Пользователем дополнительно указан установленный резерв; это отдельное проектное решение, не требование данного пункта."
        sump["requirements"] = [
            SCOPE, reserve,
            "Требование относится к заданному приямку; число приямков и общий состав оборудования здания не определены.",
            "Для расчёта нужны обоснованный приток утечек, объём и график слива при обслуживании, состав и температура воды.",
            "Для объёма и откачки нужны отметки, доступное место, уровни включения/отключения, аварийный уровень и допустимый режим пусков насоса.",
            "Для напора и подключения нужны отметка и условия приёмной сети, длина, диаметр и арматура напорного пути; требуется проверка обратного подтопления.",
            "Отвод проверяется по пп. 20.15 и 18.15. Подключение к К1 или К2 автоматически не создаётся; запись условий отвода не подтверждает их допустимость.",
            "Предусмотреть доступ для обслуживания; согласовать гидроизоляцию с КР, электропитание и управление с автоматикой. Параметры и схема пока не разработаны.",
            "Расчёт объёма, Q/H и подбор насоса не выполнены. Размеры, насосы и обвязка автоматически в схему и спецификацию не добавляются.",
        ]
        if sump["errors"]:
            sump["status"] = "invalid"
    return result
