"""
app/pz/spec.py — спецификация оборудования, изделий и материалов
(форма 1 ГОСТ 21.110-2013), раздел ИОС2. Группировка по разделам и системам
(водоснабжение холодное: В1, В2; водоснабжение горячее: Т3-Т4).

Источники строк:
  • оборудование — из подбора (PumpSystem, MetersSystem);
  • арматура — запорные краны перед приборами (project.fixtures, от АР), по Ду;
  • трубы — укрупнённо по площади (Метод 2), с группировкой по Ду (Метод 3);
  • крепления — по длинам труб и нормативному максимальному шагу.
Явно назначенные детали ВУ включают по составу схемы. Номенклатуру монтажных
изделий, определяемую подрядчиком, не выдумывают (ГОСТ 21.110 п.4.6).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from app.pz.project import BuildingPurpose, Project
from app.calc.insulation import (
    InsulationParams, PipeGvs, PipeHvs, calculate_insulation,
)
from app.data.pipe_catalog import PipeSize, pipe_size, sleeve_for, preliminary_inlet_sleeve_for
from app.pz.water_pipe_binding import bind_v1_pipes
from app.pz.hws_presentation import uses_bound_hws, build_bound_hws_rows, build_local_hws_rows
from app.data.booster_controls import booster_control
from app.pz.water_regulation_plan import branch_regulation_plan

# Удельные показатели расхода труб, пог. м на 1 м² (Метод 2); общ./пром. = жилые ÷1,5.
UNIT_PIPE_M_PER_M2 = {
    BuildingPurpose.RESIDENTIAL: {"hvs": 0.25, "gvs": 0.25},
    BuildingPurpose.PUBLIC:      {"hvs": 0.17, "gvs": 0.17},
    BuildingPurpose.INDUSTRIAL:  {"hvs": 0.17, "gvs": 0.17},
}
# Группировка труб по диаметрам (Метод 3): доля длины и представительный Ду.
PIPE_GROUPS = [("магистрали", 0.15, {"hvs": 50, "gvs": 40}),
               ("стояки",     0.35, {"hvs": 32, "gvs": 25}),
               ("подводки",   0.50, {"hvs": 20, "gvs": 20})]
PIPE_SPARE = 1.07
# СП 73.13330.2016, таблица 2: Ду -> (неизолированные, изолированные), м.
STEEL_SUPPORT_SPACING_M = {
    15: (2.5, 1.5), 20: (3.0, 2.0), 25: (3.5, 2.0), 32: (4.0, 2.5),
    40: (4.5, 3.0), 50: (5.0, 3.0), 80: (6.0, 4.0), 100: (6.0, 4.5),
    125: (7.0, 5.0), 150: (8.0, 6.0),
}
# СП 41-109-2005, таблица 4: наружный диаметр ->
# (ХВС горизонталь, ГВС горизонталь, ХВС вертикаль, ГВС вертикаль), м.
PEX_SUPPORT_SPACING_M = {
    16: (0.35, 0.35, 0.36, 0.29), 20: (0.40, 0.35, 0.43, 0.29),
    25: (0.45, 0.40, 0.57, 0.36), 32: (0.55, 0.50, 0.72, 0.50),
    40: (0.60, 0.55, 0.86, 0.57), 50: (0.75, 0.70, 1.07, 0.79),
}
# Старая оценка компенсаторов; требует отдельного аудита/согласования.
# Для секционных кранов этот коэффициент не применяется.
SEISMIC_COMPENSATOR_ESTIMATE_COEF = 0.3
# Проходки через конструкции (СП 30: гильзы Ø+5–10 мм, зазор — негорючий материал)
SLAB_THK_M = 0.20       # толщина перекрытия
WALL_THK_M = 0.30       # толщина наружной стены (для вводов)


def ring_volume_l(pipe_outer_mm: float, sleeve_inner_mm: float, length_m: float) -> float:
    """Объём кольцевого зазора труба↔гильза, дм³ (л)."""
    if sleeve_inner_mm <= pipe_outer_mm:
        raise ValueError("Внутренний диаметр гильзы должен быть больше наружного диаметра трубы")
    area_mm2 = math.pi / 4.0 * (sleeve_inner_mm ** 2 - pipe_outer_mm ** 2)
    return area_mm2 * (length_m * 1000.0) / 1e6


def _size_mark(size: PipeSize) -> str:
    return ((f"DN{size.dn}; " if size.dn else "") + f"{size.size_label}; dвн={size.inner_mm:g} мм").replace(".", ",")


def _size_label_ru(size: PipeSize) -> str:
    return size.size_label.replace(".", ",")


def _mass_mark(size: PipeSize) -> str:
    return "" if size.mass_kg_m is None else f"{size.mass_kg_m:.2f}".replace(".", ",")

DISCRETE_SPEC_UNITS = {"шт", "шт.", "компл", "компл.", "комплект"}


def format_spec_qty(value: Optional[float], unit: str) -> str:
    """Количество для формы 1: штучные единицы без десятичной части."""
    if value is None:
        return ""
    number = float(value)
    if (unit or "").strip().lower() in DISCRETE_SPEC_UNITS:
        rounded = round(number)
        if not math.isclose(number, rounded, abs_tol=1e-9):
            raise ValueError(f"Дробное количество {number:g} недопустимо для единицы '{unit}'")
        return str(int(rounded))
    return f"{number:.1f}".replace(".", ",")


@dataclass
class SpecRow:
    pos: Optional[int]
    name: str
    type_mark: str = ""
    code: str = ""
    manufacturer: str = ""
    unit: str = ""
    qty: Optional[float] = 0
    mass: str = ""
    note: str = ""
    quantity_basis: str = ""
    quantity_source: str = ""
    # VU marks are stable references to the drawing, not global row numbers.
    diagram_pos: str = ""
    component_ids: tuple[str, ...] = ()
    catalogue_id: str = ""

    @property
    def quantity_note(self) -> str:
        # The source already states the accepted per-flat/per-floor rule.
        # Repeating a generic prefix makes the narrow note column overflow.
        if self.quantity_source and self.quantity_basis in ('apartment_schedule', 'stage_p_regulation_schedule', 'apartment_connection_schedule'):
            return self.quantity_source
        labels = {
            "area_estimate": "Оценка по площади, не обмер трасс",
            "needs_area": "Площадь для укрупнённой оценки не задана",
            "needs_layout": "Нужно количество по компоновке",
            "assembly_estimate": "Оценка по условному составу узлов",
            "source_rows": "По заданным участкам/элементам",
            "project_input": "По заданному количеству, не по символам схемы",
            "metering_scheme": "По составу схемы ВУ",
            "metering_mounting_reference": "Справочный метраж ВУ, включённый в метраж системы",
            "explicit_vu_supports": "По заданному числу опор ВУ",
            "explicit_vu_accessory": "По явному выбору, на одну водомерную",
            "principle_requirement": "По принципиальной схеме",
            "stage_p_regulation_requirement": "Предусмотрено стадией П; количество требует поэтажной ведомости",
            "stage_p_regulation_schedule": "По принятой поэтажной компоновке",
            "apartment_principle": "Количество не определено",
            "apartment_schedule": "По принятому числу квартирных узлов",
        }
        return "; ".join(filter(None, (
            labels.get(self.quantity_basis, ""), self.quantity_source,
        )))


@dataclass
class SpecSection:
    title: str
    division: str = ""
    rows: List[SpecRow] = field(default_factory=list)


@dataclass
class Specification:
    sections: List[SpecSection] = field(default_factory=list)
    note: str = ""


def _mat(materials, name, default):
    return getattr(materials, name, None) or default


def build_specification(project: Project, *, scope: str = "all") -> Specification:
    """Build selected systems only; never calculate unrelated document sections."""
    if scope not in {"all", "water", "wastewater"}:
        raise ValueError("unknown specification scope")
    pos = 0
    sections: List[SpecSection] = []
    area = project.building.total_area_m2 or 0
    floors = project.building.floors_above or 0
    fb = bool(getattr(project.building, "fire_barriers", True))
    seismic = bool(getattr(project.building, "seismic", False))
    heat_need = bool(getattr(project.building, "unheated_zones", False)
                     or getattr(project.building, "permafrost", False))
    rates = UNIT_PIPE_M_PER_M2.get(project.building.purpose, UNIT_PIPE_M_PER_M2[BuildingPurpose.PUBLIC])
    mats = project.materials
    meter_rows = project.meters.rows or []
    v1_bound = bool(project.v1_sections or project.v1_network)
    v1_geometry = bind_v1_pipes(project) if v1_bound else {}

    def grouped_pipes(key, mat_mains, mat_dist):
        for group, share, dns in PIPE_GROUPS:
            if key == "hvs" and v1_bound:
                role = {"магистрали": "main", "стояки": "riser", "подводки": "apartment"}[group]
                binding = v1_geometry[role]
                size = binding.pipe
                yield group, share, size.material if size else "по расчёту", size, binding
            else:
                mat = mat_mains if group == "магистрали" else mat_dist
                yield group, share, mat, pipe_size(mat, dns[key]), None

    def next_pos():
        nonlocal pos
        pos += 1
        return pos

    def find_meter(keys):
        for r in meter_rows:
            if any(k in r.label.lower() for k in keys):
                return r
        return None

    def _step_for_steel(dn, insulated):
        table_dn = next((x for x in sorted(STEEL_SUPPORT_SPACING_M) if x >= dn), 150)
        return STEEL_SUPPORT_SPACING_M[table_dn][1 if insulated else 0]

    def _step_for_pex(dn, key, vertical):
        table_dn = next((x for x in sorted(PEX_SUPPORT_SPACING_M) if x >= dn), 50)
        idx = (2 if vertical else 0) + (1 if key == "gvs" else 0)
        return PEX_SUPPORT_SPACING_M[table_dn][idx]

    def meter_marka(type_label, dn, is_hot):
        """Марка водосчётчика: крыльчатый холодный — ВСХНд, горячий — ВСГд,
        турбинный — ВСТ (стандартные обозначения, проектировщик может уточнить)."""
        t = (type_label or "").lower()
        if "турбин" in t:
            return f"ВСТ-{dn}"
        return (f"ВСГд-{dn}" if is_hot else f"ВСХНд-{dn}")

    # арматура по приборам: {"cold": {dn: count}, "hot": {dn: count}}
    valves = {"cold": {}, "hot": {}}
    for fg in ((project.fixtures or []) if scope != "wastewater" else []):
        has_c, has_h, dn = fg.resolved()
        if has_c:
            valves["cold"][dn] = valves["cold"].get(dn, 0) + fg.count
        if has_h:
            valves["hot"][dn] = valves["hot"].get(dn, 0) + fg.count

    def valve_rows(side):
        """Строки «Кран шаровой Ø__ / то же Ø__» по возрастанию Ду."""
        out, first = [], True
        for dn in sorted(valves[side]):
            name = "Кран шаровой запорный у приборов Ø{}".format(dn) if first else "то же Ø{}".format(dn)
            first = False
            out.append(SpecRow(next_pos(), name, type_mark=f"Ø{dn}",
                               manufacturer="Торговая сеть", unit="шт.", qty=valves[side][dn]))
        return out

    def shutoff_rows(n_risers, riser_dn, main_dn, has_pump, meter_dn, bypass,
                     meter_units=1, include_meter=True):
        """Арматура узлов; дополнительная секционная запорка только по компоновке."""
        out = []
        def mark(dn):
            return f"Ду{dn}" if dn else "присоединение по подбору"
        if n_risers or not include_meter:
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный у основания стояков, {mark(riser_dn)}",
                       type_mark=mark(riser_dn), manufacturer="Торговая сеть", unit="шт.",
                       qty=n_risers or None, note="по числу стояков",
                       component_ids=('v1-riser-valve',) if not include_meter else (),
                       quantity_basis="project_input" if n_risers else "principle_requirement",
                       quantity_source=f"1 кран × {n_risers} стояков" if n_risers else
                                       "Число стояков В1 не задано; не по символам схемы"))
        if meter_dn and include_meter:
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный водомерного узла, Ду{meter_dn}",
                       type_mark=f"Ду{meter_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=2 * meter_units, note="до и после каждого счётчика"))
            if bypass:
                out.append(SpecRow(next_pos(), f"Задвижка на обводной линии, Ду{meter_dn}",
                           type_mark=f"Ду{meter_dn}", manufacturer="Торговая сеть", unit="шт.", qty=meter_units))
        if has_pump:
            pump_mark = "по патрубкам НУ" if v1_bound and not include_meter else mark(meter_dn or main_dn)
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный у насоса, {pump_mark}",
                       type_mark=pump_mark, manufacturer="Торговая сеть",
                       unit="шт.", qty=2, note="до и после насоса"))
        n_main = project.building.v1_sectional_valves_count
        basis = project.building.v1_sectional_valves_basis
        if n_main is not None and (type(n_main) is not int or not 0 <= n_main <= 1_000_000):
            raise ValueError("Секционные краны В1: требуется целое неотрицательное количество либо отсутствие значения")
        if not isinstance(basis, str) or len(basis) > 200:
            raise ValueError("Секционные краны В1: некорректное основание количества")
        basis = basis.strip()
        assigned = n_main is not None and bool(basis)
        note = "Без повторного учёта кранов стояков, ВУ, квартир и насосов"
        if not assigned:
            note += "; количество по компоновке магистралей не подтверждено"
        elif n_main == 0:
            note += "; дополнительные секционные краны не предусмотрены"
        source = basis if assigned else (
            f"Введено {n_main} шт.; укажите основание компоновки"
            if n_main is not None else "СП 30, п. 11.8: по местам отключения; не процент от стояков")
        out.append(SpecRow(next_pos(), f"Кран запорный секционный на магистрали, {mark(main_dn)}",
                   type_mark=mark(main_dn), manufacturer="Торговая сеть", unit="шт.",
                   qty=n_main if assigned else None, note=note,
                   component_ids=('v1-sectional-valves',),
                   quantity_basis="project_input" if assigned else "needs_layout",
                   quantity_source=source))
        return out

    def kip_rows(n_mano, n_termo, mano_note=""):
        """КИП: манометры показывающие + термометры технические."""
        out = []
        if n_mano:
            out.append(SpecRow(next_pos(), "Манометр показывающий", type_mark="МП-100, 0–1,0 МПа",
                       manufacturer="Торговая сеть", unit="шт.", qty=n_mano, note=mano_note))
        if n_termo:
            out.append(SpecRow(next_pos(), "Термометр технический", type_mark="0–100 °C",
                       manufacturer="Торговая сеть", unit="шт.", qty=n_termo,
                       note="подача и обратка ГВС"))
        return out

    def crossing_g4_rows(n_risers, riser_dn, riser_material, floors,
                         n_inlets, inlet_dn, inlet_material, plastic, *, riser_size=None, inlet_size=None):
        """Группа 4 «другие элементы»: гильзы при пересечении конструкций (СП 30) +
        противопожарные муфты на пластиковых стояках (при fire_barriers)."""
        out = []
        n_slab = (n_risers or 0) * (floors or 0)
        riser = riser_size or pipe_size(riser_material, riser_dn)
        inlet = inlet_size or pipe_size(inlet_material, inlet_dn)
        if n_slab:
            riser_sleeve = sleeve_for(riser)
            difference = (f"{riser_sleeve.inner_mm - riser.outer_mm:g}".replace(".", ",")
                          if riser_sleeve else None)
            out.append(SpecRow(
                next_pos(), (f"Гильза стальная ВГП обыкновенная, DN{riser_sleeve.dn}"
                             if riser_sleeve else "Гильза внутренней проходки — требуется подбор"),
                type_mark=(_size_mark(riser_sleeve) if riser_sleeve else
                           f"dвн={riser.outer_mm + 5:g}–{riser.outer_mm + 10:g} мм".replace(".", ",")),
                manufacturer="Торговая сеть" if riser_sleeve else "по подбору",
                unit="шт.", qty=n_slab,
                note=(f"для трубы {_size_label_ru(riser)}; " +
                      (f"разность диаметров {difference} мм; " if riser_sleeve else
                       "в каталоге ВГП нет подходящего размера; объём заделки не определён; ") +
                      "СП 30, п. 11.5: 5–10 мм; стояки×этажи"),
            ))
        if n_inlets:
            inlet_sleeve = preliminary_inlet_sleeve_for(inlet)
            out.append(SpecRow(
                next_pos(), (f"Гильза стальная ВГП обыкновенная, DN{inlet_sleeve.dn}"
                             if inlet_sleeve else "Гильза наружного ввода — требуется подбор"),
                type_mark=_size_mark(inlet_sleeve) if inlet_sleeve else "По узлу ввода",
                manufacturer="Торговая сеть" if inlet_sleeve else "по подбору",
                unit="шт.", qty=n_inlets,
                note=((f"для трубы {_size_label_ru(inlet)}; " +
                       (f"разность диаметров {inlet_sleeve.inner_mm-inlet.outer_mm:g} мм; "
                        if inlet_sleeve else "в каталоге ВГП нет подходящего размера; ") +
                       "габарит предварительный, герметизацию ввода уточнить по узлу").replace(".", ",")),
            ))
        if plastic and fb and n_slab:
            out.append(SpecRow(next_pos(), "Муфта противопожарная" + ("" if riser_size else f", Ду{riser_dn}"),
                       type_mark=f"для трубы {_size_label_ru(riser)}", manufacturer="Торговая сеть", unit="шт.",
                       qty=n_slab, note="на пластиковых стояках при пересечении преград"))
        return out

    def sealant_l(n_risers, riser_dn, riser_material, floors,
                  n_inlets, inlet_dn, inlet_material, *, riser_size=None, inlet_size=None) -> float | None:
        """Объём, дм³; None, если хотя бы для одной учитываемой проходки нет гильзы."""
        riser = riser_size or pipe_size(riser_material, riser_dn)
        inlet = inlet_size or pipe_size(inlet_material, inlet_dn)
        v = 0.0
        for count, pipe, sleeve, thickness in (
            ((n_risers or 0) * (floors or 0), riser, sleeve_for(riser), SLAB_THK_M),
            (n_inlets or 0, inlet, preliminary_inlet_sleeve_for(inlet), WALL_THK_M),
        ):
            if count:
                if sleeve is None:
                    return None  # Не выдавать неполную сумму за полный объём.
                v += count * ring_volume_l(pipe.outer_mm, sleeve.inner_mm, thickness)
        return v

    def sealant_rows(vol_l, *, firestop=False, partial=False):
        """Группа 8 «материалы»: массу указывают после выбора состава и его плотности."""
        if vol_l is not None and vol_l <= 0:
            return []
        name = ("Состав огнезащитный сертифицированный для проходок инженерных коммуникаций"
                if firestop else "Материал негорючий гидрофобный для заделки зазоров")
        mark = "огнезаделка проходок" if firestop else "заделка проходок"
        if vol_l is None:
            return [SpecRow(next_pos(), name,
                type_mark=mark, manufacturer="Торговая сеть", unit="кг", qty=None,
                note="Объём не определён: не для всех проходок подобраны гильзы. "
                     "Массу определить после подбора гильз, состава и его плотности")]
        volume_text = f"{vol_l:.1f}".replace(".", ",")
        return [SpecRow(next_pos(), name,
                type_mark=mark, manufacturer="Торговая сеть", unit="кг",
                qty=None, note=(
                    (f"Частичный объём {volume_text} дм³ — только вводы; число проходок стояков В1 не определено. "
                     if partial else f"Расчётный объём {volume_text} дм³. ") +
                    "Массу определить после выбора состава по его плотности; "
                    "объём предварительный по принятым узлам проходок"))]

    def seismic_rows(n_fixtures, n_risers, main_dn):
        """Сейсмические мероприятия (СП 30 р.15): гибкие подводки к приборам +
        сильфонные компенсаторы на магистралях. Только при seismicity ≥ 7."""
        if not seismic:
            return []
        out = []
        if n_fixtures:
            out.append(SpecRow(next_pos(), "Подводка гибкая к приборам, Ду15",
                       type_mark="Ду15", manufacturer="Торговая сеть", unit="шт.",
                       qty=n_fixtures, note="сейсмические мероприятия (СП 30 р.15)"))
        nc = round((n_risers or 0) * SEISMIC_COMPENSATOR_ESTIMATE_COEF)
        if nc:
            mark = f"Ду{main_dn}" if main_dn else "присоединение по подбору"
            out.append(SpecRow(next_pos(), f"Компенсатор сильфонный, {mark}",
                       type_mark=mark, manufacturer="Торговая сеть", unit="шт.",
                       qty=nc, note="сейсмические мероприятия (СП 30 р.15)"))
        return out

    def heating_rows(key):
        """Обогрев труб в неотапливаемых зонах / мерзлоте (СП 30): греющий кабель
        на магистрали (укрупнённо = длина магистрали)."""
        if not heat_need:
            return []
        if area <= 0:
            return [SpecRow(next_pos(), "Защита труб В1 от замерзания", unit="компл.", qty=None,
                component_ids=("v1-freeze-protection",), quantity_basis="needs_area",
                note="Метраж обогрева не определён; трассы, мощность и состав по температурным условиям")]
        total = area * rates[key] * PIPE_SPARE
        length = round(total * PIPE_GROUPS[0][1], 1)  # доля магистралей
        if length <= 0:
            return []
        return [SpecRow(next_pos(), "Кабель греющий саморегулирующийся",
                type_mark="16 Вт/м", manufacturer="Торговая сеть", unit="м",
                qty=length, note="обогрев в неотапливаемых зонах (СП 30)",
                quantity_basis="area_estimate",
                quantity_source=f"S={area:g} м²; доля магистралей 15%")]

    def pipe_rows(key, mat_mains, mat_dist):
        """Трубы по возрастанию Ду (ГОСТ 21.110 п.4.5), «то же» в пределах
        одного материала, сортамент для распределительной сети, ед. «м» (п.9.5)."""
        out = []
        total = area * rates[key] * PIPE_SPARE
        entries = sorted(grouped_pipes(key, mat_mains, mat_dist), key=lambda e: e[3].outer_mm if e[3] else 0)
        prev_mat = None
        for grp, share, mat, size, binding in entries:
            if size is None:
                out.append(SpecRow(next_pos(), f"Трубы В1 — {grp}", unit="м", qty=None, note=binding.issue))
                continue
            dn = size.dn
            suffix = f" ({size.size_label}; dвн={size.inner_mm:g} мм)".replace(".", ",")
            if binding:
                name = f"Труба {mat} — {grp}"
            elif mat != prev_mat:
                name = f"Труба {mat}, Ду{dn}{suffix}"
                prev_mat = mat
            else:
                name = f"то же Ду{dn}{suffix}"
            out.append(SpecRow(next_pos(), name, type_mark=_size_mark(size),
                               manufacturer="Торговая сеть", unit="м",
                               qty=round(total * share, 1) if area > 0 else None, mass=_mass_mark(size),
                               quantity_basis="area_estimate" if area > 0 else "needs_area",
                               quantity_source=(f"{area:g} м² × {rates[key]:g} м/м² × {PIPE_SPARE:g} × {share:g}"
                                                if area > 0 else "Длина сети не определена; расчётный путь не является ведомостью труб"),
                               note=("Сечение характерного пути: " + ", ".join(binding.source_ids) +
                                     "; распределение объёма по группам оценочное" if binding else "")))
        return out

    def fastener_rows(key, mat_mains, mat_dist):
        """Минимальный укрупнённый крепёж по длинам и нормативному шагу."""
        total = area * rates[key] * PIPE_SPARE
        out = []
        entries = sorted(grouped_pipes(key, mat_mains, mat_dist), key=lambda e: e[3].outer_mm if e[3] else 0)
        for grp, share, mat, size, binding in entries:
            if size is None:
                out.append(SpecRow(next_pos(), f"Крепления труб В1 — {grp}", unit="шт.", qty=None,
                    note="Нужны сечение, система труб и длина; " + binding.issue))
                continue
            dn = size.dn
            length = total * share
            vertical = grp == "стояки"
            mat_lower = mat.lower()
            if ("сталь" in mat_lower or "стальн" in mat_lower) and dn:
                step = _step_for_steel(dn, insulated=(grp != "подводки"))
                name = f"Хомут трубный стальной с эластомерной прокладкой, Ду{dn}"
                basis = "СП 73.13330.2016, табл. 2"
            elif ("pe-x" in mat_lower or "сшит" in mat_lower) and size.outer_mm in PEX_SUPPORT_SPACING_M:
                step = _step_for_pex(size.outer_mm, key, vertical)
                name = (f"Крепление скользящее для труб PE-X, {_size_label_ru(size)}" if binding else
                        f"Крепление скользящее для труб PE-X, Ду{dn}")
                basis = "СП 41-109-2005, табл. 4"
            else:
                out.append(SpecRow(
                    next_pos(), f"Комплект креплений для труб {mat}",
                    type_mark=_size_label_ru(size), manufacturer="по системе изготовителя",
                    unit="шт.", qty=None,
                    note="количество по таблице изготовителя после выбора системы труб",
                ))
                continue
            qty = math.ceil(length / step) if area > 0 else None
            out.append(SpecRow(
                next_pos(), name, type_mark=(_size_label_ru(size) if binding else f"Ду{dn}"),
                manufacturer="Торговая сеть", unit="шт.", qty=qty,
                note=(f"{grp}; " + (f"L={length:.1f} м, " if area > 0 else "L не задана; ") +
                      f"шаг ≤{step:g} м; {basis}; "
                      "доп. крепления у арматуры/поворотов уточнить на Р"),
                quantity_basis="area_estimate" if area > 0 else "needs_area",
            ))
        return out

    def fixture_rows():
        """Группа 2 «Санитарные приборы» (ГОСТ 21.110 п.9.4) — из задания АР."""
        out = []
        for fg in (project.fixtures or []):
            out.append(SpecRow(next_pos(), fg.name, manufacturer="Торговая сеть",
                               unit="шт.", qty=fg.count))
        return out

    def insulation_rows(key):
        """Группа 7 «Конструкции теплоизоляционные»: трубки из вспененного каучука
        на магистрали + стояки (в шахтах/техпространстве — от конденсата и потерь,
        СП 30 п.8.11, п.3.1.26). Подводки (открытые) не изолируют. По Ду, ед. «м»."""
        out = []
        total = area * rates[key] * PIPE_SPARE
        rows = []  # (Ду, длина, материал, фактическая геометрия)
        mat_mains = _mat(mats, "hot_mains" if key == "gvs" else "cold_mains", "сталь ГОСТ 3262-75")
        mat_dist = _mat(mats, "hot_distribution" if key == "gvs" else "cold_distribution", "PE-X")
        for grp, share, mat, size, binding in grouped_pipes(key, mat_mains, mat_dist):
            if grp == "подводки":
                continue
            if size is None:
                out.append(SpecRow(next_pos(), f"Теплоизоляция В1 — {grp}", unit="м", qty=None,
                    note="Толщина и длина требуют исходных данных; " + binding.issue))
                continue
            rows.append((size.dn, round(total * share, 1) if area > 0 else None, size))
        rows.sort(key=lambda e: e[2].outer_mm)
        ins = project.insulation
        params = InsulationParams(
            location=ins.location,
            t_room_manual=ins.t_room_manual,
            humidity=ins.humidity,
        )
        if key == "gvs":
            result = calculate_insulation(
                params,
                [PipeGvs(dn=dn, t_water=ins.gvs_water_temp,
                         outer_diameter_mm=size.outer_mm) for dn, _, size in rows],
                [],
            )
            calculated = result.gvs
        else:
            result = calculate_insulation(
                params,
                [],
                # DN=0 is an unused metadata sentinel: the HVS formula uses
                # the explicit, validated Dн. It is never printed as a size.
                [PipeHvs(dn=dn or 0, t_water=ins.hvs_water_temp,
                         outer_diameter_mm=size.outer_mm) for dn, _, size in rows],
            )
            calculated = [x if x.need_insulation else None for x in result.hvs]
        normative_min = (
            project.normative.gvs_min_insulation_mm
            if key == "gvs" else project.normative.hvs_min_insulation_mm
        )
        first = True
        for (dn, length, size), calc in zip(rows, calculated):
            if calc is None and not normative_min:
                continue
            calculated_thk = calc.delta if calc is not None else 0
            thk = max(calculated_thk, normative_min)
            material = ("минеральной ваты группы Г1" if ins.location == "parking" and key == "gvs"
                        else "вспененного каучука группы Г1" if ins.location == "parking"
                        else "вспененного каучука")
            if first:
                name = (f"Трубки теплоизоляционные из {material}, толщ. {thk} мм, "
                        f"для трубы {_size_label_ru(size)}")
                first = False
            else:
                name = f"то же толщ. {thk} мм, для трубы {_size_label_ru(size)}"
            out.append(SpecRow(next_pos(), name, type_mark=f"для {_size_label_ru(size)}, δ{thk}",
                               manufacturer="Торговая сеть", unit="м", qty=length,
                               quantity_basis="area_estimate" if area > 0 else "needs_area",
                               quantity_source=("Оценка относится к длине, не к расчёту толщины" if area > 0 else
                                                "Толщина рассчитана отдельно; длина изоляции не определена"),
                               note=(
                                   f"расчёт legacy/SP 61: δ={calculated_thk} мм, tводы="
                                   f"{ins.gvs_water_temp if key == 'gvs' else ins.hvs_water_temp:g} °C, "
                                   f"tпом={result.t_room:g} °C, φ={ins.humidity}%"
                                   + (f"; принято не менее {normative_min} мм по "
                                      "СП 253.1325800.2016, п. 10.15"
                                      if normative_min else "")
                               )))
        return out

    def fire_pipe_rows():
        """Трубы В2 по фактическим длинам расчётной сети, без укрупнения."""
        net = project.fire_network
        if net is None:
            return []
        lengths = defaultdict(float)
        for segment in net.segments:
            lengths[("кольцевая магистраль", int(segment.dn))] += segment.length_m
        for riser in net.risers:
            lengths[("стояки", int(riser.dn))] += riser.length_m
        out = []
        material = _mat(mats, "fire_pipes", "сталь по ГОСТ 3262-75")
        for (role, dn), length in sorted(lengths.items(), key=lambda x: (x[0][1], x[0][0])):
            size = pipe_size(material, dn)
            out.append(SpecRow(
                next_pos(), (f"Труба {material}, Ду{dn} "
                             f"({size.size_label}; dвн={size.inner_mm:g} мм)".replace(".", ",")),
                type_mark=_size_mark(size),
                manufacturer="Торговая сеть", unit="м", qty=round(length, 1),
                quantity_basis="source_rows",
                mass=_mass_mark(size),
                note=f"В2, {role}; по расчётной схеме стадии П",
            ))
        return out

    def fire_fastener_rows():
        """Крепления В2: кольцо по СП 73, стояки укрупнённо по этажам."""
        net = project.fire_network
        if net is None:
            return []
        out = []
        by_dn = defaultdict(float)
        for segment in net.segments:
            by_dn[int(segment.dn)] += segment.length_m
        for dn, length in sorted(by_dn.items()):
            step = _step_for_steel(dn, insulated=False)
            out.append(SpecRow(
                next_pos(), f"Хомут трубный стальной с эластомерной прокладкой, Ду{dn}",
                type_mark=f"Ду{dn}", manufacturer="Торговая сеть", unit="шт.",
                qty=math.ceil(length / step),
                note=f"кольцо В2; L={length:.1f} м, шаг ≤{step:g} м; СП 73.13330.2016, табл. 2",
            ))
        risers_by_dn = defaultdict(int)
        for riser in net.risers:
            risers_by_dn[int(riser.dn)] += 1
        for dn, count in sorted(risers_by_dn.items()):
            out.append(SpecRow(
                next_pos(), f"Хомут трубный стояка В2 с эластомерной прокладкой, Ду{dn}",
                type_mark=f"Ду{dn}", manufacturer="Торговая сеть", unit="шт.",
                qty=count * floors,
                note="укрупнённо: 1 крепление на этаж; окончательно по узлам стадии Р",
            ))
        out.sort(key=lambda row: int(row.type_mark.removeprefix("Ду")))
        return out

    def fire_crossing_rows():
        """Стальные гильзы проходок стояков В2 по фактическому сортаменту."""
        net = project.fire_network
        if net is None:
            return []
        material = _mat(mats, "fire_pipes", "сталь по ГОСТ 3262-75")
        by_dn = defaultdict(int)
        for riser in net.risers:
            by_dn[int(riser.dn)] += 1
        out = []
        for dn, count in sorted(by_dn.items()):
            out += crossing_g4_rows(
                count, dn, material, floors,
                0, dn, material, plastic=False,
            )
        return out

    def fire_sealant_l() -> float | None:
        net = project.fire_network
        if net is None:
            return 0.0
        if not floors:
            return 0.0
        material = _mat(mats, "fire_pipes", "сталь по ГОСТ 3262-75")
        total = 0.0
        for riser in net.risers:
            pipe = pipe_size(material, int(riser.dn))
            sleeve = sleeve_for(pipe)
            if sleeve is None:
                return None
            total += ((floors or 0)
                      * ring_volume_l(pipe.outer_mm, sleeve.inner_mm, SLAB_THK_M))
        return total

    f = project.fire
    if scope != "wastewater":
        # ── Раздел В1 (хоз-питьевой холодный водопровод) ──
        sec = SpecSection(
            title="В1 — хозяйственно-питьевой водопровод",
            division="Водоснабжение холодное",
        )
        # группа 1: оборудование
        p = project.pumps
        control = booster_control(p)
        regulation = branch_regulation_plan(project)
        def regulator_rows(system):
            if regulation.state != "principle" or not regulation.floors or system not in regulation.systems:
                return []
            qty = project.apartment_water_units.quantity_on_floors(system,
                project.building.apartments, project.building.floors_above,
                project.building.apartments_by_floor, regulation.floors)
            from app.pz.apartment_products import apartment_regulator_proposal
            proposal = apartment_regulator_proposal(project, system)
            product = proposal.product if proposal else None
            return [SpecRow(next_pos(),
                f"Регулятор давления квартирного ответвления {system}, статический и динамический режим",
                type_mark=(f"{product.model}; DN{product.dn}; G{product.thread}" if product else
                           "DN, Kv и марка — по подбору"), unit="шт.", qty=qty,
                code=product.article if product else '',
                manufacturer=product.manufacturer if product else '',
                catalogue_id=product.id if product else '',
                component_ids=(f"apartment-{'v1' if system == 'В1' else 't3'}-regulator",),
                note=(f"По одному на квартирный ввод {system}, этажи {regulation.floor_text}; "
                      if qty is None else f"Этажи {regulation.floor_text}; ") +
                     "граница предварительная. " +
                     ("Кандидат; уставка по подбору" if product else
                      "Для питьевой воды" + (", исполнение для ГВС" if system == "Т3" else "")),
                quantity_basis="stage_p_regulation_requirement" if qty is None else "stage_p_regulation_schedule",
                quantity_source="" if qty is None else
                    f"1 РД на ввод × {qty} квартир на этажах {regulation.floor_text}; один ввод {system} на квартиру")]
        v1_main = v1_geometry["main"].pipe if v1_bound else None
        v1_riser = v1_geometry["riser"].pipe if v1_bound else None
        v1_inlet = v1_geometry["inlet"].pipe if v1_bound else None
        main_dn = v1_main.dn if v1_bound and v1_main else None if v1_bound else PIPE_GROUPS[0][2]["hvs"]
        riser_dn = v1_riser.dn if v1_bound and v1_riser else None if v1_bound else PIPE_GROUPS[1][2]["hvs"]
        pump_obr = None
        if p.required and p.top3:
            from app.pz.water_station_review import factory_component_ids
            from app.data.booster_service import booster_service
            service = booster_service(p)
            acc = p.top3[0]
            duty = (f"Qрасч={p.q_design_m3h:.3f} м³/ч, Hтреб={p.h_design_m:.2f} м"
                    if p.q_design_m3h > 0 and p.h_design_m > 0
                    else "расчётная пара Q/H не задана")
            intersection = (f"; оценочное пересечение Q={p.wp_q:.2f} м³/ч, H={p.wp_h:.2f} м"
                            if p.wp_q > 0 and p.wp_h > 0 else "")
            sec.rows.append(SpecRow(
                next_pos(),
                (f"Установка повысительная: {duty}; P2 одного насоса={getattr(acc,'p2_kw',0):.2f} кВт"
                 + (f"; частотное управление {control.drive}" if control else "")).replace('.', ','),
                type_mark=f"{getattr(acc,'brand','')} {getattr(acc,'model','')}".strip(),
                manufacturer="по проекту", unit="шт.", qty=1,
                note=(p.count_note or "1 раб. + 1 рез.") +
                     intersection.replace('.', ',') +
                     ("; не уставка ПЧ; ПЧ, штатные датчики/реле, манометры, отсечки насосов и обратные клапаны в комплекте PBS, отдельно не учитывать; мембранный бак 12 л с отсечкой также в комплекте" if control else "") +
                     ("; воздушные и сливные пробки CDM15 - штатные части насосов, не отдельные краны (РЭ CDM, рис. 7-Н)" if service else ""),
                component_ids=("station_assembly", *factory_component_ids(project)),
                quantity_basis="selected_station", quantity_source="1 комплект насосной установки"))
            pump_obr = True
            if project.normative.frequency_drive_required and not control:
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Шкаф управления повысительной насосной установкой с частотным приводом",
                    manufacturer="Комплект поставки насосной установки",
                    unit="компл.", qty=1,
                    note="ручное, дистанционное и автоматическое управление; "
                         "СП 253.1325800.2016, пп. 10.25, 10.27",
                ))
            # вибровставки у насоса (СП 30): кроме произв. зданий без шумозащиты
            if project.building.noise_protection:
                sec.rows.append(SpecRow(next_pos(),
                    "Вставка виброизолирующая гибкая" + ("" if v1_bound else f", Ду{main_dn}"),
                    type_mark="по патрубкам НУ" if v1_bound else f"Ду{main_dn}", manufacturer="Торговая сеть",
                    unit="шт.", qty=2, note="на всас/напор насоса (СП 30)"))
        # группа 2: санитарные приборы
        sec.rows += fixture_rows()
        if project.normative.apartment_hose_tap_required:
            apartment_qty = project.building.apartments or None
            sec.rows.append(SpecRow(
                next_pos(),
                "Кран внутриквартирного пожаротушения Ду15 со шлангом и распылителем",
                type_mark="Ду15", manufacturer="Торговая сеть", unit="компл.",
                qty=apartment_qty,
                note=(
                    "по одному на квартиру; длина шланга до любой точки квартиры; "
                    "СП 54.13330.2022, п. 6.2.4.3"
                    if apartment_qty else
                    "по одному на квартиру; количество квартир требуется по АР; "
                    "СП 54.13330.2022, п. 6.2.4.3"
                ),
            ))
        # группа 3: трубопроводная арматура
        sec.rows += regulator_rows("В1")
        from app.pz.water_apartment_assembly import apartment_spec_rows
        from app.pz.apartment_connections import apartment_connection_rows
        sec.rows += apartment_spec_rows(project, "В1", next_pos)
        sec.rows += apartment_connection_rows(project, "В1", next_pos)
        cm = find_meter(["ввод", "хвс", "холодн"])
        # All common inlet-meter components have one owner: the VU subsection
        # below. Do not also count the former generic meter/filter/stand here.
        if project.normative.separate_owner_metering_required:
            sec.rows.append(SpecRow(
                next_pos(),
                "Узел автономного учёта холодной воды для группы помещений отдельного собственника",
                manufacturer="по проекту", unit="компл.",
                qty=project.meters.owner_groups_count,
                note="по числу групп собственников; Ду и состав подобрать по расходу "
                     "каждой группы на стадии Р; СП 118.13330.2022, п. 8.24",
            ))
        nv1 = project.building.risers_v1 or 0
        from app.pz.water_service_assemblies import service_rows
        sec.rows += service_rows(project, "v1", next_pos)
        from app.pz.water_station_components import external_spec_rows
        sec.rows += external_spec_rows(project, next_pos)
        if pump_obr and not control:
            sec.rows.append(SpecRow(next_pos(), "Клапан обратный на напорном патрубке насоса",
                                    manufacturer="Торговая сеть", unit="шт.", qty=2,
                                    note="по числу насосов"))
        # запорная арматура (гибрид): стояки + узел учёта + насос + магистрали
        sec.rows += shutoff_rows(nv1, riser_dn, main_dn,
                                 pump_obr and not control, (cm.dn if cm else None),
                                 (project.meters.has_bypass if cm else False),
                                 meter_units=max(1, project.source.inputs_count), include_meter=False)
        sec.rows += valve_rows("cold")
        # КИП: манометры узла учёта и насоса
        sec.rows += kip_rows(2 if pump_obr and not control else 0, 0, mano_note="насосная установка; вне ВУ")
        # группа 4: гильзы + противопожарные муфты (проходки)
        if not v1_bound or (v1_riser and v1_inlet):
            sec.rows += crossing_g4_rows(
                nv1, PIPE_GROUPS[1][2]["hvs"], _mat(mats, "cold_distribution", "PE-X"), floors,
                project.source.inputs_count, PIPE_GROUPS[0][2]["hvs"],
                _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                plastic=(v1_riser.family in {"pe", "pex"} if v1_bound else True),
                riser_size=v1_riser, inlet_size=v1_inlet,
            )
        else:
            sec.rows.append(SpecRow(next_pos(), "Гильзы проходок В1", unit="шт.", qty=None,
                                   note="Нужны согласованные сечения вводов и стояков"))
        # реакции на условия: сейсмика + обогрев (срабатывают по флагам ТЗ)
        sec.rows += seismic_rows(sum(fg.count for fg in (project.fixtures or [])),
                                 nv1, main_dn)
        sec.rows += heating_rows("hvs")
        # группа 4: опоры и крепления трубопроводов
        sec.rows += fastener_rows("hvs", _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                                  _mat(mats, "cold_distribution", "PE-X"))
        # группа 6: трубопроводы
        sec.rows += pipe_rows("hvs", _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                              _mat(mats, "cold_distribution", "PE-X"))
        if v1_inlet:
            sec.rows.append(SpecRow(next_pos(), f"Труба ввода {v1_inlet.material}",
                type_mark=_size_mark(v1_inlet), unit="м", qty=None,
                note="Сечение: " + ", ".join(v1_geometry["inlet"].source_ids) +
                "; суммарная длина по плану вводов, длина расчётного пути не размножается на число вводов"))
        # группа 7: конструкции теплоизоляционные
        sec.rows += insulation_rows("hvs")
        # группа 8: материалы (герметик по объёму)
        if not v1_bound or (v1_riser and v1_inlet):
            sec.rows += sealant_rows(sealant_l(
                nv1, PIPE_GROUPS[1][2]["hvs"], _mat(mats, "cold_distribution", "PE-X"), floors,
                project.source.inputs_count, PIPE_GROUPS[0][2]["hvs"],
                _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                riser_size=v1_riser, inlet_size=v1_inlet,
            ), partial=not nv1 or not floors)
        sections.append(sec)

        from app.pz.metering_spec import build_metering_spec_section, branch_meter_kit_row
        vu = build_metering_spec_section(project)
        from app.pz.metering_hot_node import hot_spec_section
        hot_vu = hot_spec_section(project)
        # The inlet meter is owned by the assembly. Every other calculated
        # node gets exactly one separate row, including cold/heater branches.
        from app.pz.meter_products import primary_meter, evaluate_meter_product
        from app.pz.meter_validation import meter_node_key
        primary = primary_meter(project)
        branch_meters = []
        branch_kits = []
        for row in meter_rows:
            if row is primary:
                continue
            if hot_vu is not None and meter_node_key(row) == "hot":
                continue  # Owned by its own drawing/composition, never twice.
            check = evaluate_meter_product(project, row)
            model = check.product
            branch_meters.append(SpecRow(
                next_pos(), f"Счётчик воды, DN{row.dn} — {row.label}",
                type_mark=model.model if model else "",
                manufacturer=model.manufacturer if model else "",
                unit="шт.", qty=1, catalogue_id=model.id if model else "",
                quantity_basis="metering_scheme", component_ids=(f"meter_{check.node}",),
                note="Предварительный подбор; условия применения по паспорту" if model else
                     "; ".join(check.errors) or "Модель уточнить",
            ))
            kit = branch_meter_kit_row(project, row, check)
            if kit:
                kit.pos = next_pos()
                branch_kits.append(kit)
        vu.rows[1:1] = branch_meters
        kit_index = next(i for i, row in enumerate(vu.rows) if "kit_in" in row.component_ids)
        vu.rows[kit_index+1:kit_index+1] = branch_kits
        sections.append(vu)
        if hot_vu is not None:
            sections.append(hot_vu)

        # ── Раздел Т3-Т4 (ГВС подача + циркуляция) ──
        if uses_bound_hws(project):
            sec = SpecSection(title="Т3-Т4 — горячее водоснабжение",
                              division="Водоснабжение горячее")
            sec.rows = build_bound_hws_rows(project, next_pos)
            # Regulating valves belong with fittings, before pipes/insulation.
            valve_index = next((i for i, row in enumerate(sec.rows)
                                if "circulation-balance" in row.component_ids), 0)
            sec.rows[valve_index:valve_index] = regulator_rows("Т3")
            sec.rows[valve_index:valve_index] = (apartment_spec_rows(project, "Т3", next_pos)
                + apartment_connection_rows(project, "Т3", next_pos))
            hm = find_meter(["гвс", "горяч"])
            if hm and hot_vu is None:
                sec.rows[0:0] = [SpecRow(next_pos(), "Фильтр узла учёта ГВС", type_mark=f"DN{hm.dn}",
                    unit="шт.", qty=1, quantity_basis="metering_scheme"),
                    SpecRow(next_pos(), "Запорная арматура узла учёта ГВС", type_mark=f"DN{hm.dn}",
                    unit="шт.", qty=2, quantity_basis="metering_scheme", note="До и после счётчика")]
            sec.rows += valve_rows("hot")
            if project.normative.separate_owner_metering_required:
                sec.rows.append(SpecRow(next_pos(), "Узел автономного учёта горячей воды отдельного собственника",
                    unit="компл.", qty=project.meters.owner_groups_count or None,
                    note="Состав по расходам каждой группы", quantity_basis="project_input"))
            sections.append(sec)
        elif project.building.hws_type.value == "local":
            sections.append(SpecSection(title="Местное горячее водоснабжение",
                division="Водоснабжение горячее",
                rows=build_local_hws_rows(project, next_pos) + valve_rows("hot")))

        # ── Раздел В2 (внутренний противопожарный водопровод) ──
        f = project.fire
        if f.required:
            sec = SpecSection(
                title="В2 — внутренний противопожарный водопровод",
                division="Водоснабжение холодное",
            )
            fp = project.fire_pumps
            if fp.pressure_review:
                from app.pz.fire_review_binding import spec_rows
                for row in spec_rows(project):
                    sec.rows.append(SpecRow(next_pos(), row['name'], type_mark=row['mark'],
                        unit=row['unit'], qty=row['qty'], note=row['note']))
            elif fp.station_design:
                from app.pz.fire_station_binding import station_spec_rows
                for row in station_spec_rows(fp.station_design):
                    sec.rows.append(SpecRow(next_pos(), row['name'], type_mark=row['mark'],
                        unit=row['unit'], qty=row['qty'], note=row['note']))
            elif fp.required and fp.top3:
                acc = fp.top3[0]
                sec.rows.append(SpecRow(
                    next_pos(),
                    f"Установка пожарная насосная: Q={fp.wp_q:.2f} м³/ч, "
                    f"H={fp.wp_h:.1f} м, N={getattr(acc, 'p2_kw', 0):.2f} кВт",
                    type_mark=f"{getattr(acc, 'brand', '')} {getattr(acc, 'model', '')}".strip(),
                    manufacturer="по проекту", unit="шт.", qty=1,
                    note=(fp.count_note or "1 рабочий + 1 резервный")
                         + ("; предварительный подбор по архивной Q-H кривой"
                            if getattr(acc, "archived", False) else "")))
                if project.normative.frequency_drive_required:
                    sec.rows.append(SpecRow(
                        next_pos(),
                        "Шкаф управления пожарной насосной установкой с регулируемым приводом",
                        manufacturer="Комплект поставки насосной установки",
                        unit="компл.", qty=1,
                        note="диспетчеризация; ручное, дистанционное и автоматическое "
                             "управление; СП 253.1325800.2016, пп. 10.25–10.27",
                    ))
            pk = getattr(f, "pk_total", 0) or 0
            ndn = getattr(f, "nozzle_dn", 50)
            hose = getattr(f, "hose_length_m", 20)
            if pk:
                sec.rows.append(SpecRow(
                    next_pos(), f"Кран пожарный Ду{ndn} с рукавом {hose} м и стволом РС-50",
                    type_mark=f"Ду{ndn}", manufacturer="Торговая сеть", unit="шт.",
                    qty=pk, note="в шкафу пожарном"))
                sec.rows.append(SpecRow(next_pos(), "Шкаф пожарный навесной (ШПК)",
                                        manufacturer="Торговая сеть", unit="шт.", qty=pk))
            else:
                # pk_total не задан: число ПК определяется графической расстановкой
                # (СП 10.13130, орошение каждой точки расчётным числом струй) —
                # позиция вносится, количество уточняется по планам, а не молча теряется.
                sec.rows.append(SpecRow(
                    next_pos(), f"Кран пожарный Ду{ndn} с рукавом {hose} м и стволом РС-50",
                    type_mark=f"Ду{ndn}", manufacturer="Торговая сеть", unit="шт.",
                    qty=None, note="кол-во по расстановке ПК на планах"))
                sec.rows.append(SpecRow(next_pos(), "Шкаф пожарный навесной (ШПК)",
                                        manufacturer="Торговая сеть", unit="шт.",
                                        qty=None, note="по числу ПК"))
            sec.rows += fire_crossing_rows()
            sec.rows += fire_fastener_rows()
            sec.rows += fire_pipe_rows()
            sec.rows += sealant_rows(fire_sealant_l(), firestop=True)
            sections.append(sec)

    if scope != "water":
        # ── Раздел К1/К2: только явно подтверждённые позиции стадии П ──
        from app.pz.wastewater_graphic_exports import representative_document_model
        section_model = representative_document_model(project)
        section_mains = dict(section_model.mains) if section_model else {}

        def add_section_main(section, system):
            data = section_mains.get(system)
            if data is not None and data.dn_mm is not None:
                geometry = (f"; Ø{data.outer_diameter_mm:g}×{data.wall_thickness_mm:g}; dвн={data.inner_diameter_mm:g} мм"
                            if data.inner_diameter_mm is not None else "")
                section.rows.append(SpecRow(
                    next_pos(), f"Магистраль и выпуск системы {system}",
                    type_mark=f"DN{data.dn_mm}"+geometry.replace('.', ','), unit="м", qty=None,
                    note="DN задан для характерного разреза; длина уточняется по планам. "
                         "По изображению количество не определяется. "
                         + (f"Заданный материал: {data.material_label}. " if data.material else "") +
                         "Основание: " + (data.source_ref or "не задано"),
                ))
        k1_pipes = [row for row in project.sewage.pipes if row.system == "K1"]
        k2_pipes = [row for row in project.sewage.pipes if row.system == "K2"]
        k3_pipes = [row for row in project.sewage.pipes if row.system == "K3"]
        k1_elements = [row for row in project.sewage.elements if row.system == "K1"]
        k2_elements = [row for row in project.sewage.elements if row.system == "K2"]
        k3_elements = [row for row in project.sewage.elements if row.system == "K3"]

        def add_sewer_elements(section, elements):
            """Переносит реестр в СО, складывая идентичные штучные позиции."""
            groups = {}
            for element in (row for row in elements if row.include_in_spec):
                type_mark = element.type_mark
                if not type_mark and element.dn_mm is not None:
                    type_mark = f"DN{element.dn_mm}"
                key = (
                    element.name, type_mark, element.standard,
                    element.manufacturer, element.unit,
                )
                groups.setdefault(key, []).append(element)
            for key, items in groups.items():
                element = items[0]
                floor_note = (
                    f"эт. {element.floor_from}–{element.floor_to}"
                    if element.floor_to is not None
                    and element.floor_to != element.floor_from
                    else f"эт. {element.floor_from}"
                )
                location = ", ".join(filter(None, (
                    element.room_number, element.room_name, floor_note,
                )))
                if len(items) == 1:
                    note = "; ".join(filter(None, (
                        element.element_id,
                        location,
                        element.note,
                    )))
                else:
                    ids = ", ".join(row.element_id for row in items)
                    item_notes = "; ".join(dict.fromkeys(
                        row.note for row in items if row.note
                    ))
                    note = "; ".join(filter(None, (
                        f"реестр: {ids}",
                        "места установки по принципиальной схеме",
                        item_notes,
                    )))
                section.rows.append(SpecRow(
                    next_pos(),
                    key[0],
                    type_mark=key[1],
                    code=key[2],
                    manufacturer=key[3],
                    unit=key[4],
                    qty=sum(row.quantity for row in items),
                    quantity_basis="source_rows",
                    note=note,
                ))

        if (
            project.sewage.outlets_count
            or k1_pipes
            or k1_elements
            or project.flows.sewage_l_per_s > 0
            or project.grease_trap.required
            or "К1" in section_mains
        ):
            sec = SpecSection(
                title="К1 — бытовая канализация",
                division="Водоотведение",
            )
            for pipe in k1_pipes:
                sec.rows.append(SpecRow(
                    next_pos(),
                    f"Труба канализационная {pipe.material}",
                    type_mark=(
                        f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}; "
                        f"dвн={pipe.inner_diameter_mm:g} мм"
                    ).replace(".", ","),
                    code=pipe.standard,
                    manufacturer="по проекту",
                    unit="м",
                    qty=round(pipe.length_m, 2),
                    quantity_basis="source_rows",
                    note=f"{pipe.section_id}; {pipe.purpose}".rstrip("; "),
                ))
            add_sewer_elements(sec, k1_elements)
            add_section_main(sec, "К1")
            if section_model and section_model.fan_plan.kind == "common":
                sec.rows.append(SpecRow(next_pos(), "Сборный вентиляционный трубопровод К1",
                    type_mark=f"DN{section_model.fan_plan.diameter_mm}" if section_model.fan_plan.diameter_mm else "",
                    unit="м", qty=None, note="Общая вытяжка заданной группы: " +
                    ", ".join(section_model.fan.member_ids) + ". " + section_model.fan_plan.diameter_notice +
                    " Материал, изоляция, фасонные части и длина "
                    "уточняются по АР/ВК; по характерному разрезу не подсчитываются. Основание: " +
                    section_model.fan.source_ref))
            if (
                project.sewage.outlets_count
                and not any(row.kind == "outlet" for row in k1_elements)
            ):
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Выпуск хозяйственно-бытовой канализации К1",
                    manufacturer="по проекту",
                    unit="шт.",
                    qty=project.sewage.outlets_count,
                    note="диаметр и узел присоединения по плану/профилю",
                ))
            if not k1_pipes and not k1_elements:
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Трубопроводы, фасонные части, ревизии и прочистки системы К1",
                    manufacturer="по проекту",
                    unit="компл.",
                    qty=None,
                    note="длины и количество по планам и аксонометрии стадии Р; "
                         "условные объёмы не подставлены",
                ))
            sections.append(sec)

        if project.grease_trap.preparation_type != "none" or k3_pipes or k3_elements:
            sec = SpecSection(
                title="К3 — производственная канализация",
                division="Водоотведение",
            )
            if project.grease_trap.required:
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Жироуловитель для производственных стоков предприятия общественного питания",
                    manufacturer="по проекту", unit="компл.", qty=None,
                    note="число и производительность по заданию ТХ и схеме выпусков; "
                         "СП 118.13330.2022, п. 8.7",
                ))
            for pipe in k3_pipes:
                sec.rows.append(SpecRow(
                    next_pos(),
                    f"Труба производственной канализации {pipe.material}",
                    type_mark=(
                        f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}; "
                        f"dвн={pipe.inner_diameter_mm:g} мм"
                    ).replace(".", ","),
                    code=pipe.standard,
                    manufacturer="по проекту",
                    unit="м",
                    qty=round(pipe.length_m, 2),
                    quantity_basis="source_rows",
                    note=f"{pipe.section_id}; {pipe.purpose}".rstrip("; "),
                ))
            add_sewer_elements(sec, k3_elements)
            if not k3_pipes and not k3_elements:
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Трубопроводы и фасонные части системы К3",
                    manufacturer="по проекту", unit="компл.", qty=None,
                    note="состав по заданию ТХ и принципиальной схеме",
                ))
            sections.append(sec)

        if project.storm.system_kind == "internal" or k2_pipes or k2_elements or "К2" in section_mains:
            sec = SpecSection(
                title="К2 — внутренний водосток",
                division="Водоотведение",
            )
            if not any(row.kind == "roof_funnel" for row in k2_elements):
                heating = section_model.funnel_heated if section_model and section_model.drainage == "internal" else None
                heating_label = (" с электрообогревом" if heating is True else
                                 " без электрообогрева" if heating is False else "")
                heating_note = ("; мощность обогрева и питание по паспорту изделия" if heating is True else
                                "; необходимость электрообогрева не задана" if heating is None else "")
                sec.rows.append(SpecRow(
                    next_pos(), "Воронка водосточная для внутреннего водостока" + heating_label,
                    manufacturer="по проекту", unit="шт.",
                    qty=(project.storm.funnels_count or None),
                    quantity_basis="project_input" if project.storm.funnels_count else "",
                    note="тип и паспортная пропускная способность по плану кровли; "
                         "СП 30.13330.2020, пп. 21.5, 21.12" + heating_note,
                ))
            for pipe in k2_pipes:
                sec.rows.append(SpecRow(
                    next_pos(),
                    f"Труба водосточная {pipe.material}",
                    type_mark=(
                        f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}; "
                        f"dвн={pipe.inner_diameter_mm:g} мм"
                        + (
                            f"; PN{pipe.pressure_class_bar:g}"
                            if pipe.pressure_rated is True
                            and pipe.pressure_class_bar is not None
                            else ""
                        )
                    ).replace(".", ","),
                    code=pipe.standard,
                    manufacturer="по проекту",
                    unit="м",
                    qty=round(pipe.length_m, 2),
                    quantity_basis="source_rows",
                    note=f"{pipe.section_id}; {pipe.purpose}".rstrip("; "),
                ))
            add_sewer_elements(sec, k2_elements)
            add_section_main(sec, "К2")
            if not k2_pipes and not k2_elements:
                sec.rows.append(SpecRow(
                    next_pos(),
                    "Трубопроводы, фасонные части и ревизии системы К2",
                    manufacturer="по проекту",
                    unit="компл.",
                    qty=None,
                    note="длины и количество по планам и аксонометрии стадии Р; "
                         "условные объёмы не подставлены",
                ))
            sections.append(sec)

    # ГОСТ 21.601-2011, пп. 9.3–9.4: сначала раздел холодного
    # водоснабжения (В1, В2), затем горячего; позиции выводим последовательно
    # после нормативной сортировки разделов.
    system_order = {"В1": 0, "В2": 1, "Т3-Т4": 2, "К1": 3, "К2": 4, "К3": 5}
    division_order = {
        "Водоснабжение холодное": 0,
        "Водоснабжение горячее": 1,
        "Водоотведение": 2,
    }
    sections.sort(key=lambda s: (
        division_order.get(s.division, 99),
        next((rank for marker, rank in system_order.items() if s.title.startswith(marker)), 99),
    ))
    row_number = 0
    for section in sections:
        for row in section.rows:
            if row.pos is not None:
                row_number += 1
                row.pos = row_number

    fire_note = (
        "Трубы В2 приняты по длинам расчётной сети стадии П. "
        if f.required else ""
    )
    highrise_note = (
        "Для высотного здания применены минимумы 10 мм (ХВС) и 25 мм "
        "(ГВС/циркуляция) по СП 253.1325800.2016, п. 10.15. "
        if project.normative.sp253_applicable else ""
    )
    if scope != "wastewater" and project.rainwater_reuse.enabled:
        from app.pz.rainwater_reuse import specification_rows
        sections.append(SpecSection(
            title="Использование дождевой воды · предварительный состав",
            division="Техническое водоснабжение", rows=specification_rows(project),
        ))
    result = Specification(
        sections=sections,
        note=((f"Длины трубопроводов В1 и общий объём труб ГВС оценены для площади {area:g} м² "
              "укрупнённо по удельным показателям расхода труб на 1 м² площади (Метод 2) "
              "с коэффициентом запаса 1,07; это оценка программы, не обмер планов. " if area > 0 else
              "Площадь для укрупнённой оценки труб не задана; количество труб и креплений В1 "
              "не определено. Пустое количество не означает отсутствие изделия. ") +
              "Санитарные приборы — по исходным данным; арматура — по их количеству "
              "и принятому составу узлов, включая отмеченные укрупнённые оценки. "
              + ("Толщины изоляции для подтверждённых сечений рассчитаны существующим алгоритмом "
                 "legacy/SP 61; незаданные параметры обозначены в строках спецификации. "
                 if uses_bound_hws(project) else
              "Толщина изоляции В1 рассчитана алгоритмом legacy SP calculator по СП 61 "
              "для заданных температуры и влажности. Общая циркуляционная сеть Т4 не назначена. ") + f"{highrise_note}{fire_note}"
              + ("Сечения В1 перенесены из заданного характерного расчётного пути без изменения материалов. "
                 "Их применение к оценочным объёмам групп не заменяет ведомость всей сети здания. "
                 "Для остальных систем сортамент указан в соответствующих строках; " if v1_bound else
                 "Для стальных труб зафиксировано исполнение ВГП «обыкновенная» по ГОСТ 3262-75; ") +
              "в спецификации приведены Dн×s и расчётный Dвн=Dн−2s. Для PE-X приведены "
              "фактические Dн×s и Dвн принятого сортамента. "
              "Крепления с указанными количествами рассчитаны минимально по длинам и предельному шагу СП 73.13330.2016 "
              "и СП 41-109-2005; дополнительные крепления у арматуры, поворотов и ответвлений "
              "уточняются на стадии «Р». В подразделе «Водомерный узел» учтены явно "
              "заданные детали и состав принципиальной схемы (ГОСТ Р 21.619-2023, п.5.2.2.6, приложение Г). "
              "Неопределённые длины труб и количество опор оставлены пустыми; это не нулевой объём. "
              "Штатный присоединительный комплект счётчика учтён один раз без повторного учёта его частей. "
              "Монтажные изделия, определяемые подрядчиком, не назначались условно "
              "(ГОСТ 21.110-2013 п.4.6; ГОСТ 21.601-2011 п.9.4). "
              "Состав разделов, порядок групп и единицы измерения — по ГОСТ 21.601-2011 "
              "пп.9.3–9.5; форма таблицы — по ГОСТ 21.110-2013."),
    )

    if scope != "wastewater" and uses_bound_hws(project):
        total_hws = area * rates["gvs"] * PIPE_SPARE
        result.note += ((
            f" Для Т3-Т4 общая укрупнённая оценка {total_hws:g} м сохранена справочно "
            "(площадь × удельный показатель × 1,07), без распределения между Т3/Т4 и диаметрами. "
            if area > 0 else " Для Т3-Т4 общая укрупнённая оценка не выполнена: площадь не задана. ") +
            "В строках ГВС размеры Т3 взяты из текущего расчётного пути, а количества труб, "
            "креплений и проходок оставлены незаданными: характерный путь не является ведомостью сети. "
            "Размеры и изоляция Т4 не назначены по аналогии с Т3. Функциональные элементы схемы "
            "включены требованиями к комплектации, а не подтверждённым подбором оборудования."
        )

    if scope != "wastewater":
        from app.pz.apartment_products import apartment_product_spec_note
        result.note += apartment_product_spec_note(project)

    if scope == "wastewater":
        result.note = (
            "Количество труб и элементов К1/К2/К3 перенесено из исходных данных проекта. "
            "Наличие числа в ведомости само по себе не подтверждает его измерение по плану. "
            "Метраж по площади здания не применяется. Полноту сети, происхождение длин "
            "и количества проверяют по планам и принятой схеме; не заданные позиции "
            "остаются без количества. Форма таблицы - по ГОСТ 21.110-2013."
        )
    return result


def build_water_specification(project: Project) -> Specification:
    """Independent IOS2 specification: V1/V2/T3/T4, no drainage evaluation."""
    return build_specification(project, scope="water")


def build_wastewater_specification(project: Project) -> Specification:
    """Independent IOS3 specification, without water calculations or quantities."""
    return build_specification(project, scope="wastewater")
