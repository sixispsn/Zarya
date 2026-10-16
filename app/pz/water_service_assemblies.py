"""Explicit service/balancing takeoff; no hydraulic sizing or symbol counting.

SP 30 (uploaded edition with amendments), 11.17 and 10.6–10.7.
An unspecified layout keeps requirements visible, not a fictitious quantity.
"""
from dataclasses import dataclass


SERVICE_MODES = {
    "unspecified": "Компоновка пока не задана",
    "per_riser": "По одному верхнему и нижнему узлу на каждый стояк",
    "explicit": "Задать количество точек обслуживания",
}
BALANCE_MODES = {
    "unspecified": "Схема циркуляции пока не задана",
    "riser_returns": "На подключениях стояков Т4 к сборной магистрали",
    "collection_branches": "На сборных циркуляционных ветвях / секционных узлах",
    "floor_loops": "На подключениях поэтажных колец к стоякам Т4",
    "towel_rail_returns": "На ветвях полотенцесушителей и сборных возвратах",
}
SERVICE_COUNTS = tuple(f"{s}_{point}" for s in ("v1", "t3", "t4") for point in ("upper", "lower"))


@dataclass(frozen=True)
class WaterServiceLayout:
    mode: str = "unspecified"
    v1_upper: int | None = None
    v1_lower: int | None = None
    t3_upper: int | None = None
    t3_lower: int | None = None
    t4_upper: int | None = None
    t4_lower: int | None = None
    balance_mode: str = "unspecified"
    balance_count: int | None = None
    balance_collector_count: int | None = None

    def validate(self):
        issues = []
        for key, choices in (("mode", SERVICE_MODES), ("balance_mode", BALANCE_MODES)):
            if not isinstance(getattr(self, key), str) or getattr(self, key) not in choices:
                issues.append(f"water_service_layout.{key}: неизвестная компоновка")
        for key in (*SERVICE_COUNTS, "balance_count", "balance_collector_count"):
            value = getattr(self, key)
            if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000):
                issues.append(f"water_service_layout.{key}: требуется целое число от 0 до 1 000 000")
            active = (self.mode == "explicit" if key in SERVICE_COUNTS else
                      self.balance_mode == "towel_rail_returns" if key == "balance_collector_count" else
                      self.balance_mode in ("collection_branches", "floor_loops", "towel_rail_returns"))
            if value is not None and not active:
                issues.append(f"water_service_layout.{key}: количество не соответствует выбранной компоновке")
        return issues

    def check(self):
        if issues := self.validate():
            raise ValueError("; ".join(issues))

    def service_quantity(self, system, point, building):
        self.check()
        if system not in ("v1", "t3", "t4") or point not in ("upper", "lower"):
            raise ValueError("Неизвестная точка обслуживания")
        if self.mode == "explicit":
            return getattr(self, f"{system}_{point}")
        if self.mode == "per_riser":
            n = getattr(building, "risers_" + system)
            if type(n) is not int or not 0 <= n <= 1_000_000:
                raise ValueError("Некорректное число стояков для узлов обслуживания")
            return n or None
        return None

    def balance_quantity(self, building):
        self.check()
        if self.balance_mode == "riser_returns":
            n = building.risers_t4
            if type(n) is not int or not 0 <= n <= 1_000_000:
                raise ValueError("Некорректное число стояков Т4 для балансировки")
            return n or None
        if self.balance_mode != "unspecified":
            return self.balance_count
        return None


def from_dict(raw):
    if not isinstance(raw, dict):
        raise ValueError("water_service_layout: требуется объект")
    data = WaterServiceLayout(**raw)
    data.check()
    return data


def from_values(values):
    mode = values.get("water_service_mode", "unspecified")
    central = values.get("hws_type") == "central"
    balance = values.get("hws_balance_mode", "unspecified") if central else "unspecified"
    counts = {k: values.get("water_service_" + k) for k in SERVICE_COUNTS
              if mode == "explicit" and (k.startswith("v1_") or central)}
    return WaterServiceLayout(mode=mode, **counts, balance_mode=balance,
        balance_count=values.get("hws_balance_count") if balance in (
            "collection_branches", "floor_loops", "towel_rail_returns") else None,
        balance_collector_count=values.get("hws_balance_collector_count") if balance == "towel_rail_returns" else None)


def shows_riser_balance(project):
    """Existing characteristic section only depicts the riser-return variant.

    A takeoff choice does not reconstruct a floor-ring/towel-rail network.
    Do not falsely keep the base-riser valve for those selected variants.
    """
    return project.building.water_service_layout.balance_mode in ("unspecified", "riser_returns")


def service_rows(project, system, next_pos):
    from app.pz.spec import SpecRow
    data = project.building.water_service_layout
    title = {"v1": "В1", "t3": "Т3", "t4": "Т4"}[system]
    if system != "v1" and project.building.hws_type.value != "central":
        return []
    rows = []
    for key, point, name in (
        ("air-collector", "upper", "Воздухосборник"),
        ("air-isolation", "upper", "Клапан запорный перед воздухоотводчиком"),
        ("air-vent", "upper", "Воздухоотводчик автоматический с впуском воздуха"),
        ("drain-valve", "lower", "Кран спускной в нижней точке"),
    ):
        qty = data.service_quantity(system, point, project.building)
        source = (f"Принято: 1 {'верхний' if point == 'upper' else 'нижний'} узел на стояк {title}; по 1 изделию на узел"
                  if data.mode == "per_riser" else f"Заданы точки обслуживания {title}; по 1 изделию на точку")
        if qty is None:
            source = "Число точек обслуживания не задано; не по символам схемы"
        note = ("СП 30, п. 11.17; верхний узел: воздухосборник, кран, автомат; вне квартир"
                if point == "upper" else "СП 30, п. 11.17; вне запорки стояков и обвязки оборудования")
        if qty == 0:
            note += "; задано 0: проверить обеспечение обслуживания"
        rows.append(SpecRow(next_pos(), f"{name} {title}",
            type_mark="DN, исполнение и присоединения по подбору узла", unit="шт.", qty=qty,
            component_ids=(f"{system}-{key}",), note=note,
            quantity_basis="project_input" if qty is not None else "needs_layout", quantity_source=source))
    return rows


def balance_rows(project, next_pos):
    from app.pz.spec import SpecRow
    if project.building.hws_type.value != "central":
        return []
    data = project.building.water_service_layout
    qty = data.balance_quantity(project.building)
    location = {
        "unspecified": "в циркуляционной сети Т4",
        "riser_returns": "на подключениях стояков Т4",
        "collection_branches": "на сборных циркуляционных ветвях",
        "floor_loops": "на подключениях поэтажных колец Т4",
        "towel_rail_returns": "на возвратных ветвях полотенцесушителей",
    }[data.balance_mode]
    entries = [("circulation-balance", location, qty)]
    if data.balance_mode == "towel_rail_returns":
        entries.append(("circulation-balance-collectors", "на сборных возвратах к стоякам Т4", data.balance_collector_count))
    rows = []
    for key, place, count in entries:
        source = (f"Принято: 1 клапан на подключение × {count} стояков Т4" if data.balance_mode == "riser_returns" else
                  "Количество точек подключения задано по выбранной схеме циркуляции")
        if count is None:
            source = "Схема / число точек балансировки не заданы; не по числу стояков или квартир на рисунке"
        note = ("СП 30, п. 10.7; две группы клапанов учитываются отдельно" if data.balance_mode == "towel_rail_returns" else
                "СП 30, п. 10.6; подбор по расчёту циркуляционных колец")
        if count == 0:
            note += "; задано 0: проверить обеспечение балансировки"
        rows.append(SpecRow(next_pos(), "Клапан балансировочный ручной " + place,
            type_mark="DN, Kv и настройка по расчёту", unit="шт.", qty=count,
            component_ids=(key,), note=note,
            quantity_basis="project_input" if count is not None else "needs_layout", quantity_source=source))
    return rows
