"""Shared T3/T4 presentation contract, not a network-sizing algorithm.

A characteristic hydraulic path supplies sizes, never building quantities.
In particular it does not supply T4 sizes or a circulation-pump selection.
"""
from dataclasses import dataclass

from app.calc.insulation import InsulationParams, PipeGvs, calculate_insulation
from app.pz.water_pipe_binding import bind_t3_pipes, PipeBinding


@dataclass(frozen=True)
class HwsPipeItem:
    key: str
    title: str
    binding: PipeBinding
    insulation_mm: int | None = None


@dataclass(frozen=True)
class HwsPrinciple:
    """Document scope only. Does not certify a circulation calculation."""
    mode: str
    central: bool
    local_circulation_pump: bool
    zones_unresolved: bool
    risers_t3: int | None
    risers_t4: int | None

    @property
    def drawing_notes(self):
        return (
            "Т3 - подача к приборам; Т4 - возврат к источнику, без водоразбора.",
            "Балансировка Т4 предусмотрена; DN, Kv и настройка не определены.",
            ("Материал и DN Т4 нужны для выпуска П; расчёт колец и подбор НЦ не выполнены."
             if self.local_circulation_pump else
             "Материал и DN Т4 нужны для выпуска П; расчёт колец и условия возврата по ТУ требуют дополнения."),
        )


def hws_zone_count(project):
    """Explicit HWS zoning must not reconfigure the cold-water network."""
    data = project.hws_stage_p
    if data.enabled and data.zones is not None:
        return data.zones
    return project.building.zones or 1


def hws_principle(project):
    kind = project.building.hws_type.value
    central = kind == "central"
    local_pump = central and project.source.hws_heater_in_scope
    mode = ("central_local" if local_pump else "central_external") if central else kind
    return HwsPrinciple(mode, central, local_pump,
        central and hws_zone_count(project) > 1,
        project.building.risers_t3 or None, project.building.risers_t4 or None)


def uses_bound_hws(project):
    # Absence of a T3 path must not activate the old guessed T4 DN20/lengths.
    return hws_principle(project).central


def hws_pipe_items(project):
    """Identical pipe identities and geometry for drawing and specification."""
    bindings = bind_t3_pipes(project)
    ins = project.insulation
    items = []
    for role, title in (("main", "магистраль"), ("riser", "стояк"),
                        ("apartment", "квартирная подводка")):
        b = bindings[role]
        thickness = None
        # GVS tables use DN in addition to Dн. Unlike the HVS formula,
        # a zero metadata sentinel is NOT safe here. No nearest-size guess.
        if b.pipe and b.pipe.dn is not None and role != "apartment":
            result = calculate_insulation(
                InsulationParams(location=ins.location, t_room_manual=ins.t_room_manual,
                                 humidity=ins.humidity),
                [PipeGvs(dn=b.pipe.dn, t_water=ins.gvs_water_temp,
                         outer_diameter_mm=b.pipe.outer_mm)], [],
            )
            thickness = max(result.gvs[0].delta, project.normative.gvs_min_insulation_mm)
        items.append(HwsPipeItem("t3-" + role, "Т3: " + title, b, thickness))
    items.append(HwsPipeItem("t4-network", "Т4: циркуляционная сеть",
        PipeBinding("circulation", None, (), "Нет геометрии расчётной сети Т4")))
    return tuple(items)


def build_bound_hws_rows(project, next_pos):
    # Local import keeps the drawing contract independent of spec rendering.
    from app.pz.spec import SpecRow
    items = hws_pipe_items(project)
    principle = hws_principle(project)
    rows = []

    def row(key, name, mark="", unit="шт.", qty=None, note="", quantity_source=""):
        rows.append(SpecRow(next_pos(), name, type_mark=mark, unit=unit, qty=qty,
            note=note, component_ids=(key,), quantity_basis="principle_requirement",
            quantity_source=quantity_source or ("Количество по проекту" if qty is not None else
                            "Количество не определено; не по числу символов на схеме")))

    def riser_source(system, count):
        return (f"1 изделие × {count} стояков {system}" if count else
                f"Число стояков {system} не задано; не по символам схемы")

    if principle.local_circulation_pump:
        row("circulation-pump-pending", "Насосная установка циркуляции ГВС",
            "Q/H, состав и модель по расчёту Т4", unit="компл.",
            note="Функция НЦ показана на схеме; окончательного подбора нет")
    from app.pz.water_service_assemblies import service_rows, balance_rows
    rows += balance_rows(project, next_pos)
    rows += service_rows(project, "t3", next_pos)
    rows += service_rows(project, "t4", next_pos)
    row("t3-riser-valve", "Арматура запорная у основания стояков Т3",
        "Присоединение к " + items[1].binding.label, qty=project.building.risers_t3 or None,
        note="Тип и исполнение изделия уточнить",
        quantity_source=riser_source('Т3', principle.risers_t3))
    row("t4-riser-valve", "Арматура запорная у основания стояков Т4", "DN по расчёту Т4",
        qty=project.building.risers_t4 or None,
        quantity_source=riser_source('Т4', principle.risers_t4))
    row("hws-fittings", "Фасонные части и арматура обвязки ГВС", "По составу узлов",
        unit="компл.", note=("Включая обратные клапаны и запорную арматуру НЦ; без условного подсчёта"
            if principle.local_circulation_pump else "По узлам Т3/Т4 и условиям присоединения; местный НЦ не задан"))
    row("temperature-supply", "Термометр на подаче Т3", "Диапазон и исполнение по подбору",
        qty=1 if hws_zone_count(project) == 1 else None)
    row("temperature-return", "Термометр на возврате Т4", "Диапазон и исполнение по подбору",
        qty=1 if hws_zone_count(project) == 1 else None)
    row("hws-supports", "Крепления трубопроводов Т3 и Т4", "По размерам и системе труб",
        note="Нужны длины и размещение опор; Т4 не приравнивается к Т3")
    row("hws-sleeves", "Гильзы проходок трубопроводов ГВС", "По узлам пересечения конструкций",
        note="Вводы В1 не являются вводами ГВС; число пересечений не задано")
    # The cold feed belongs to the HWS assembly but is not a T3 pipe.
    if project.source.hws_heater_in_scope:
        b = bind_t3_pipes(project)["feed"]
        row("cold-to-heater", "Труба В1 к узлу нагрева ГВС",
            (b.pipe.material + "; " + b.label) if b.pipe else b.label, unit="м",
            note="Сечение из расчётного пути; метраж сети не определён")
    for item in items:
        b = item.binding
        system = "Т4" if item.key == "t4-network" else "Т3"
        mark = (b.pipe.material + f"; dвн={b.pipe.inner_mm:g} мм").replace(".", ",") if b.pipe else f"Материал и размер по расчёту {system}"
        row(item.key, "Труба " + item.title + ", " + b.label, mark, "м",
            note=("Размер из " + ", ".join(b.source_ids) + "; длина пути не равна длине сети")
                 if b.pipe else b.issue)
    for item in items:
        if item.insulation_mm is not None:
            material = "минеральная вата Г1" if project.insulation.location == "parking" else "вспененный каучук"
            row("insulation-" + item.key, "Теплоизоляция " + item.title,
                f"{material}; {item.binding.label}; δ{item.insulation_mm} мм", "м",
                note=f"DN{item.binding.pipe.dn}; толщина по алгоритму legacy/SP 61; длина не определена")
        elif item.key in ("t3-main", "t3-riser"):
            row("insulation-" + item.key, "Теплоизоляция " + item.title,
                item.binding.label + "; толщина требует данных", "м",
                note=("Для расчёта по таблицам legacy нужен подтверждённый DN, не только Dн×s; "
                      f"нормативный минимум {max(10, project.normative.gvs_min_insulation_mm)} мм"))
    row("insulation-t4-network", "Теплоизоляция Т4", "Размер и толщина после задания труб Т4", "м",
        note=(f"Нормативный минимум {max(10, project.normative.gvs_min_insulation_mm)} мм; "
              "это не расчётная толщина. Теплопроводность не более 0,05 Вт/(м·°С), СП 30, п. 10.3"))
    row("hws-sealant", "Материал заделки проходок ГВС", "По узлам проходок и типу преград", "кг",
        note="Объём и масса после задания проходок; не по числу вводов В1")
    if project.building.unheated_zones or project.building.permafrost:
        row("hws-freeze-protection", "Защита ГВС от замерзания", "По температурным условиям и трассам",
            "компл.", note="Состав и количество не определены")
    if project.building.seismic:
        row("hws-seismic", "Сейсмические мероприятия ГВС", "По узлам и особым условиям", "компл.")
    return rows


def build_local_hws_rows(project, next_pos):
    """Local heaters do not imply a building-wide T4 loop or guessed DN20."""
    from app.pz.spec import SpecRow
    return [SpecRow(next_pos(), name, type_mark=mark, unit=unit, qty=None,
        component_ids=(key,), quantity_basis="principle_requirement",
        note="Общая Т4 не предусмотрена; состав и количество по размещению местных водонагревателей")
        for key, name, mark, unit in (
            ("local-hws-heaters", "Местные водонагреватели", "Тип, мощность и объём по заданию", "шт."),
            ("local-hws-pipes", "Трубы местного горячего водоснабжения", project.materials.hot_distribution + "; Dн×s по расчёту", "м"),
            ("local-hws-fittings", "Арматура и фасонные части местных водонагревателей", "По схеме и паспорту оборудования", "компл."),
        )]
