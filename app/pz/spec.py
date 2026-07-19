"""
app/pz/spec.py — спецификация оборудования, изделий и материалов
(форма 1 ГОСТ 21.110-2013), раздел ИОС2. Группировка ПО СИСТЕМАМ (В1, Т3, В2).

Источники строк:
  • оборудование — из подбора (PumpSystem, MetersSystem);
  • арматура — запорные краны перед приборами (project.fixtures, от АР), по Ду;
  • трубы — укрупнённо по площади (Метод 2), с группировкой по Ду (Метод 3);
  • крепления — по длинам труб и нормативному максимальному шагу.
Фасонные части и гибкие подводки не включают (ГОСТ 21.601 п.9.4,
ГОСТ 21.110 п.4.6). Повтор наименования по возрастанию Ду -> «то же Ø…» (п.4.5).
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
VALVE_MAIN_COEF = 0.3   # укрупнённый коэф. секционной запорки на магистралях (от числа стояков)
# Проходки через конструкции (СП 30: гильзы Ø+5–10 мм, зазор — негорючий материал)
SLAB_THK_M = 0.20       # толщина перекрытия
WALL_THK_M = 0.30       # толщина наружной стены (для вводов)
SLEEVE_GAP_MM = 8       # зазор труба↔гильза (5–10 мм)
SLEEVE_DN_ROW = [25, 32, 40, 50, 65, 80, 100, 125, 150]  # ряд Ду гильз

def sleeve_dn(d_outer_mm: float) -> int:
    need = d_outer_mm + SLEEVE_GAP_MM
    for s in SLEEVE_DN_ROW:
        if s >= need:
            return s
    return SLEEVE_DN_ROW[-1]

def ring_volume_l(d_outer_mm: float, length_m: float) -> float:
    """Объём кольцевого зазора труба↔гильза, дм³ (л)."""
    dg = d_outer_mm + SLEEVE_GAP_MM
    area_mm2 = math.pi / 4.0 * (dg ** 2 - d_outer_mm ** 2)
    return area_mm2 * (length_m * 1000.0) / 1e6
# Сортамент PE-X/ПНД (Ду -> Ø×стенка) для записи труб распределительной сети.
PEX_SORTAMENT = {16: "16×2,0", 20: "20×2,0", 25: "25×2,3",
                 32: "32×3,0", 40: "40×3,7", 50: "50×4,6"}
@dataclass
class SpecRow:
    pos: Optional[int]
    name: str
    type_mark: str = ""
    code: str = ""
    manufacturer: str = ""
    unit: str = ""
    qty: float = 0
    mass: str = ""
    note: str = ""


@dataclass
class SpecSection:
    title: str
    rows: List[SpecRow] = field(default_factory=list)


@dataclass
class Specification:
    sections: List[SpecSection] = field(default_factory=list)
    note: str = ""


def _mat(materials, name, default):
    return getattr(materials, name, None) or default


def build_specification(project: Project) -> Specification:
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
    for fg in (project.fixtures or []):
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

    def shutoff_rows(n_risers, riser_dn, main_dn, has_pump, meter_dn, bypass):
        """Запорная арматура (гибрид, СП 30): стояки точно + узел учёта + насос +
        секционная на магистралях укрупнённо."""
        out = []
        if n_risers:
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный у основания стояков, Ду{riser_dn}",
                       type_mark=f"Ду{riser_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=n_risers, note="по числу стояков"))
        if meter_dn:
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный водомерного узла, Ду{meter_dn}",
                       type_mark=f"Ду{meter_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=2, note="до и после счётчика"))
            if bypass:
                out.append(SpecRow(next_pos(), f"Задвижка на обводной линии, Ду{meter_dn}",
                           type_mark=f"Ду{meter_dn}", manufacturer="Торговая сеть", unit="шт.", qty=1))
        if has_pump:
            out.append(SpecRow(next_pos(), f"Кран шаровой запорный у насоса, Ду{meter_dn or main_dn}",
                       type_mark=f"Ду{meter_dn or main_dn}", manufacturer="Торговая сеть",
                       unit="шт.", qty=2, note="до и после насоса"))
        n_main = round((n_risers or 0) * VALVE_MAIN_COEF)
        if n_main:
            out.append(SpecRow(next_pos(), f"Кран запорный секционный на магистрали, Ду{main_dn}",
                       type_mark=f"Ду{main_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=n_main, note="укрупнённо; уточняется на Р"))
        return out

    def balancer_rows(n_t4, dn):
        """Балансировочные клапаны на циркуляционных стояках Т4 (СП 30)."""
        if not n_t4:
            return []
        return [SpecRow(next_pos(), f"Клапан балансировочный ручной, Ду{dn}",
                type_mark=f"Ду{dn}", manufacturer="Торговая сеть", unit="шт.", qty=n_t4,
                note="на циркуляционные стояки Т4")]

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

    def crossing_g4_rows(n_risers, riser_dn, floors, n_inlets, inlet_dn, plastic):
        """Группа 4 «другие элементы»: гильзы при пересечении конструкций (СП 30) +
        противопожарные муфты на пластиковых стояках (при fire_barriers)."""
        out = []
        n_slab = (n_risers or 0) * (floors or 0)
        if n_slab:
            out.append(SpecRow(next_pos(), f"Гильза стальная, Ду{sleeve_dn(riser_dn)}",
                       type_mark=f"Ду{sleeve_dn(riser_dn)}", manufacturer="Торговая сеть",
                       unit="шт.", qty=n_slab, note="проходки стояков через перекрытия (стояки×этажи)"))
        if n_inlets:
            out.append(SpecRow(next_pos(), f"Гильза стальная, Ду{sleeve_dn(inlet_dn)}",
                       type_mark=f"Ду{sleeve_dn(inlet_dn)}", manufacturer="Торговая сеть",
                       unit="шт.", qty=n_inlets, note="проходки вводов через стену"))
        if plastic and fb and n_slab:
            out.append(SpecRow(next_pos(), f"Муфта противопожарная, Ду{riser_dn}",
                       type_mark=f"Ду{riser_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=n_slab, note="на пластиковых стояках при пересечении преград"))
        return out

    def sealant_l(n_risers, riser_dn, floors, n_inlets, inlet_dn):
        """Объём негорючего материала для заделки зазоров проходок, дм³."""
        v = (n_risers or 0) * (floors or 0) * ring_volume_l(riser_dn, SLAB_THK_M)
        v += (n_inlets or 0) * ring_volume_l(inlet_dn, WALL_THK_M)
        return v

    def sealant_rows(vol_l):
        """Группа 8 «материалы»: герметик/негорючий материал заделки (по объёму)."""
        if vol_l <= 0:
            return []
        return [SpecRow(next_pos(), "Материал негорючий гидрофобный для заделки зазоров",
                type_mark="заделка проходок", manufacturer="Торговая сеть", unit="дм³",
                qty=round(vol_l, 1), note="заполнение зазоров гильз (СП 30)")]

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
        nc = round((n_risers or 0) * VALVE_MAIN_COEF)
        if nc:
            out.append(SpecRow(next_pos(), f"Компенсатор сильфонный, Ду{main_dn}",
                       type_mark=f"Ду{main_dn}", manufacturer="Торговая сеть", unit="шт.",
                       qty=nc, note="сейсмические мероприятия (СП 30 р.15)"))
        return out

    def heating_rows(key):
        """Обогрев труб в неотапливаемых зонах / мерзлоте (СП 30): греющий кабель
        на магистрали (укрупнённо = длина магистрали)."""
        if not heat_need or area <= 0:
            return []
        total = area * rates[key] * PIPE_SPARE
        length = round(total * PIPE_GROUPS[0][1], 1)  # доля магистралей
        if length <= 0:
            return []
        return [SpecRow(next_pos(), "Кабель греющий саморегулирующийся",
                type_mark="16 Вт/м", manufacturer="Торговая сеть", unit="м",
                qty=length, note="обогрев в неотапливаемых зонах (СП 30)")]

    def pipe_rows(key, mat_mains, mat_dist):
        """Трубы по возрастанию Ду (ГОСТ 21.110 п.4.5), «то же» в пределах
        одного материала, сортамент для распределительной сети, ед. «м» (п.9.5)."""
        out = []
        if area <= 0:
            return out
        total = area * rates[key] * PIPE_SPARE
        entries = []  # (Ду, материал, доля, сортамент)
        for grp, share, dn_map in PIPE_GROUPS:
            dn = dn_map[key]
            is_main = (grp == "магистрали")
            mat = mat_mains if is_main else mat_dist
            sort = "" if is_main else PEX_SORTAMENT.get(dn, "")
            entries.append((dn, mat, share, sort))
        entries.sort(key=lambda e: e[0])  # по возрастанию Ду
        prev_mat = None
        for dn, mat, share, sort in entries:
            suffix = f" ({sort})" if sort else ""
            if mat != prev_mat:
                name = f"Труба {mat}, Ду{dn}{suffix}"
                prev_mat = mat
            else:
                name = f"то же Ду{dn}{suffix}"
            out.append(SpecRow(next_pos(), name, type_mark=f"Ду{dn}",
                               manufacturer="Торговая сеть", unit="м",
                               qty=round(total * share, 1)))
        return out

    def fastener_rows(key, mat_mains, mat_dist):
        """Минимальный укрупнённый крепёж по длинам и нормативному шагу."""
        if area <= 0:
            return []
        total = area * rates[key] * PIPE_SPARE
        out = []
        for grp, share, dn_map in PIPE_GROUPS:
            dn = dn_map[key]
            length = total * share
            vertical = grp == "стояки"
            mat = mat_mains if grp == "магистрали" else mat_dist
            mat_lower = mat.lower()
            if "сталь" in mat_lower:
                step = _step_for_steel(dn, insulated=(grp != "подводки"))
                name = f"Хомут трубный стальной с эластомерной прокладкой, Ду{dn}"
                basis = "СП 73.13330.2016, табл. 2"
            elif "pe-x" in mat_lower or "сшит" in mat_lower:
                step = _step_for_pex(dn, key, vertical)
                name = f"Крепление скользящее для труб PE-X, Ду{dn}"
                basis = "СП 41-109-2005, табл. 4"
            else:
                out.append(SpecRow(
                    next_pos(), f"Комплект креплений для труб {mat}, Ду{dn}",
                    type_mark=f"Ду{dn}", manufacturer="по системе изготовителя",
                    unit="компл.", qty=None,
                    note="количество по таблице изготовителя после выбора системы труб",
                ))
                continue
            qty = math.ceil(length / step)
            out.append(SpecRow(
                next_pos(), name, type_mark=f"Ду{dn}",
                manufacturer="Торговая сеть", unit="шт.", qty=qty,
                note=(f"{grp}; L={length:.1f} м, шаг ≤{step:g} м; {basis}; "
                      "доп. крепления у арматуры/поворотов уточнить на Р"),
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
        if area <= 0:
            return out
        total = area * rates[key] * PIPE_SPARE
        rows = []  # (Ду, длина)
        for grp, share, dn_map in PIPE_GROUPS:
            if grp == "подводки":
                continue
            rows.append((dn_map[key], round(total * share, 1)))
        rows.sort(key=lambda e: e[0])
        ins = project.insulation
        params = InsulationParams(
            location=ins.location,
            t_room_manual=ins.t_room_manual,
            humidity=ins.humidity,
        )
        if key == "gvs":
            result = calculate_insulation(
                params,
                [PipeGvs(dn=dn, t_water=ins.gvs_water_temp) for dn, _ in rows],
                [],
            )
            calculated = {x.dn: x for x in result.gvs}
        else:
            result = calculate_insulation(
                params,
                [],
                [PipeHvs(dn=dn, t_water=ins.hvs_water_temp) for dn, _ in rows],
            )
            calculated = {x.dn: x for x in result.hvs if x.need_insulation}
        first = True
        for dn, length in rows:
            calc = calculated.get(dn)
            if calc is None:
                continue
            thk = calc.delta
            material = ("минеральной ваты группы Г1" if ins.location == "parking" and key == "gvs"
                        else "вспененного каучука группы Г1" if ins.location == "parking"
                        else "вспененного каучука")
            if first:
                name = f"Трубки теплоизоляционные из {material}, толщ. {thk} мм, Ду{dn}"
                first = False
            else:
                name = f"то же толщ. {thk} мм, Ду{dn}"
            out.append(SpecRow(next_pos(), name, type_mark=f"Ду{dn}, δ{thk}",
                               manufacturer="Торговая сеть", unit="м", qty=length,
                               note=(f"расчёт legacy/SP 61: tводы="
                                     f"{ins.gvs_water_temp if key == 'gvs' else ins.hvs_water_temp:g} °C, "
                                     f"tпом={result.t_room:g} °C, φ={ins.humidity}%")))
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
            out.append(SpecRow(
                next_pos(), f"Труба {material}, Ду{dn}", type_mark=f"Ду{dn}",
                manufacturer="Торговая сеть", unit="м", qty=round(length, 1),
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
        return out

    # ── Раздел В1 (хоз-питьевой холодный водопровод) ──
    sec = SpecSection(title="В1 — хозяйственно-питьевой водопровод")
    # группа 1: оборудование
    p = project.pumps
    pump_obr = None
    if p.required and p.top3:
        acc = p.top3[0]
        sec.rows.append(SpecRow(
            next_pos(),
            f"Установка повысительная: Q={p.wp_q:.2f} м³/ч, H={p.wp_h:.1f} м, "
            f"N={getattr(acc,'p2_kw',0):.2f} кВт",
            type_mark=f"{getattr(acc,'brand','')} {getattr(acc,'model','')}".strip(),
            manufacturer="по проекту", unit="компл.", qty=1,
            note=p.count_note or "1 раб. + 1 рез."))
        pump_obr = True
        # вибровставки у насоса (СП 30): кроме произв. зданий без шумозащиты
        if project.building.noise_protection:
            sec.rows.append(SpecRow(next_pos(),
                f"Вставка виброизолирующая гибкая, Ду{PIPE_GROUPS[0][2]['hvs']}",
                type_mark=f"Ду{PIPE_GROUPS[0][2]['hvs']}", manufacturer="Торговая сеть",
                unit="шт.", qty=2, note="на всас/напор насоса (СП 30)"))
    # группа 2: санитарные приборы
    sec.rows += fixture_rows()
    # группа 3: трубопроводная арматура
    cm = find_meter(["ввод", "хвс", "холодн"])
    if cm:
        sec.rows.append(SpecRow(
            next_pos(), f"Счётчик воды крыльчатый, Ду{cm.dn}", type_mark=meter_marka(cm.type_label, cm.dn, False),
            manufacturer="Торговая сеть", unit="шт.", qty=1,
            note=("с обводной линией" if cm.need_bypass else
                  ("комбинированный" if cm.need_combo else ""))))
        sec.rows.append(SpecRow(
            next_pos(), f"Фильтр сетчатый муфтовый, Ду{cm.dn}", type_mark=f"Ду{cm.dn}",
            manufacturer="Торговая сеть", unit="шт.", qty=1, note="на водомерный узел"))
        sec.rows.append(SpecRow(
            next_pos(), f"Подставка (опорная рама) под водомерный узел, Ду{cm.dn}",
            type_mark="индивидуального изготовления", manufacturer="по месту",
            unit="шт.", qty=max(1, project.source.inputs_count),
            note="по числу вводов; конструкцию и анкеровку уточнить на стадии Р"))
    nv1 = project.building.risers_v1 or 0
    if nv1:
        sec.rows.append(SpecRow(
            next_pos(), "Воздухоотводчик автоматический, Ду15", type_mark="Ду15",
            manufacturer="Торговая сеть", unit="шт.", qty=nv1,
            note="по числу стояков; уточняется на Р"))
    if pump_obr:
        sec.rows.append(SpecRow(next_pos(), "Клапан обратный на напорном патрубке насоса",
                                manufacturer="Торговая сеть", unit="шт.", qty=2,
                                note="по числу насосов"))
    # запорная арматура (гибрид): стояки + узел учёта + насос + магистрали
    sec.rows += shutoff_rows(nv1, PIPE_GROUPS[1][2]["hvs"], PIPE_GROUPS[0][2]["hvs"],
                             pump_obr, (cm.dn if cm else None),
                             (cm.need_bypass if cm else False))
    sec.rows += valve_rows("cold")
    # КИП: манометры узла учёта и насоса
    sec.rows += kip_rows(1 + (2 if pump_obr else 0), 0, mano_note="узел учёта и насос")
    # группа 4: гильзы + противопожарные муфты (проходки)
    sec.rows += crossing_g4_rows(nv1, PIPE_GROUPS[1][2]["hvs"], floors, 1,
                                 PIPE_GROUPS[0][2]["hvs"], plastic=True)
    # реакции на условия: сейсмика + обогрев (срабатывают по флагам ТЗ)
    sec.rows += seismic_rows(sum(fg.count for fg in (project.fixtures or [])),
                             nv1, PIPE_GROUPS[0][2]["hvs"])
    sec.rows += heating_rows("hvs")
    # группа 6: трубопроводы
    sec.rows += pipe_rows("hvs", _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                          _mat(mats, "cold_distribution", "PE-X"))
    sec.rows += fastener_rows("hvs", _mat(mats, "cold_mains", "сталь ГОСТ 3262-75"),
                              _mat(mats, "cold_distribution", "PE-X"))
    # группа 7: конструкции теплоизоляционные
    sec.rows += insulation_rows("hvs")
    # группа 8: материалы (герметик по объёму)
    sec.rows += sealant_rows(sealant_l(nv1, PIPE_GROUPS[1][2]["hvs"], floors, 1,
                                       PIPE_GROUPS[0][2]["hvs"]))
    sections.append(sec)

    # ── Раздел Т3-Т4 (ГВС подача + циркуляция) ──
    if project.building.hws_type.value != "none":
        sec = SpecSection(title="Т3-Т4 — горячее водоснабжение")
        hm = find_meter(["гвс", "горяч"])
        if hm:
            sec.rows.append(SpecRow(
                next_pos(), f"Счётчик воды крыльчатый, Ду{hm.dn}", type_mark=meter_marka(hm.type_label, hm.dn, True),
                manufacturer="Торговая сеть", unit="шт.", qty=1,
                note=("комбинированный" if hm.need_combo else "")))
            sec.rows.append(SpecRow(
                next_pos(), f"Фильтр сетчатый муфтовый, Ду{hm.dn}", type_mark=f"Ду{hm.dn}",
                manufacturer="Торговая сеть", unit="шт.", qty=1, note="на водомерный узел"))
        nt = (project.building.risers_t3 or 0) + (project.building.risers_t4 or 0)
        if nt:
            sec.rows.append(SpecRow(
                next_pos(), "Воздухоотводчик автоматический, Ду15", type_mark="Ду15",
                manufacturer="Торговая сеть", unit="шт.", qty=nt,
                note="на стояки Т3 и Т4; уточняется на Р"))
        # запорная арматура: стояки Т3+Т4 + узел учёта
        sec.rows += shutoff_rows(nt, PIPE_GROUPS[1][2]["gvs"], PIPE_GROUPS[0][2]["gvs"],
                                 False, (hm.dn if hm else None),
                                 (hm.need_bypass if hm else False))
        # балансировочные клапаны на циркуляционных стояках Т4
        sec.rows += balancer_rows(project.building.risers_t4 or 0, 20)
        sec.rows += valve_rows("hot")
        # КИП: манометр узла учёта + термометры подачи/обратки ГВС
        sec.rows += kip_rows(1, 2, mano_note="узел учёта ГВС")
        # группа 4: гильзы + противопожарные муфты (стояки Т3+Т4)
        sec.rows += crossing_g4_rows(nt, PIPE_GROUPS[1][2]["gvs"], floors, 1,
                                     PIPE_GROUPS[0][2]["gvs"], plastic=True)
        sec.rows += seismic_rows(0, nt, PIPE_GROUPS[0][2]["gvs"])
        sec.rows += heating_rows("gvs")
        sec.rows += pipe_rows("gvs", _mat(mats, "hot_mains", "сталь ГОСТ 3262-75"),
                              _mat(mats, "hot_distribution", "PE-X"))
        sec.rows += fastener_rows("gvs", _mat(mats, "hot_mains", "сталь ГОСТ 3262-75"),
                                  _mat(mats, "hot_distribution", "PE-X"))
        sec.rows += insulation_rows("gvs")
        # группа 8: материалы (герметик)
        sec.rows += sealant_rows(sealant_l(nt, PIPE_GROUPS[1][2]["gvs"], floors, 1,
                                           PIPE_GROUPS[0][2]["gvs"]))
        sections.append(sec)

    # ── Раздел В2 (внутренний противопожарный водопровод) ──
    f = project.fire
    if f.required:
        sec = SpecSection(title="В2 — внутренний противопожарный водопровод")
        fp = project.fire_pumps
        if fp.required and fp.top3:
            acc = fp.top3[0]
            sec.rows.append(SpecRow(
                next_pos(),
                f"Установка пожарная насосная: Q={fp.wp_q:.2f} м³/ч, "
                f"H={fp.wp_h:.1f} м, N={getattr(acc, 'p2_kw', 0):.2f} кВт",
                type_mark=f"{getattr(acc, 'brand', '')} {getattr(acc, 'model', '')}".strip(),
                manufacturer="по проекту", unit="компл.", qty=1,
                note=(fp.count_note or "1 рабочий + 1 резервный")
                     + ("; предварительный подбор по архивной Q-H кривой"
                        if getattr(acc, "archived", False) else "")))
        pk = getattr(f, "pk_total", 0) or 0
        ndn = getattr(f, "nozzle_dn", 50)
        hose = getattr(f, "hose_length_m", 20)
        if pk:
            sec.rows.append(SpecRow(
                next_pos(), f"Кран пожарный Ду{ndn} с рукавом {hose} м и стволом РС-50",
                type_mark=f"Ду{ndn}", manufacturer="Торговая сеть", unit="компл.",
                qty=pk, note="в шкафу пожарном"))
            sec.rows.append(SpecRow(next_pos(), "Шкаф пожарный навесной (ШПК)",
                                    manufacturer="Торговая сеть", unit="шт.", qty=pk))
        else:
            # pk_total не задан: число ПК определяется графической расстановкой
            # (СП 10.13130, орошение каждой точки расчётным числом струй) —
            # позиция вносится, количество уточняется по планам, а не молча теряется.
            sec.rows.append(SpecRow(
                next_pos(), f"Кран пожарный Ду{ndn} с рукавом {hose} м и стволом РС-50",
                type_mark=f"Ду{ndn}", manufacturer="Торговая сеть", unit="компл.",
                qty=None, note="кол-во по расстановке ПК на планах"))
            sec.rows.append(SpecRow(next_pos(), "Шкаф пожарный навесной (ШПК)",
                                    manufacturer="Торговая сеть", unit="шт.",
                                    qty=None, note="по числу ПК"))
        sec.rows += fire_pipe_rows()
        sec.rows += fire_fastener_rows()
        sections.append(sec)

    return Specification(
        sections=sections,
        note=(f"Длины трубопроводов В1 и Т3-Т4 определены для общей площади {area:g} м² "
              "укрупнённо по удельным показателям расхода труб на 1 м² площади (Метод 2) "
              "с коэффициентом запаса 1,07; уточняются на стадии «Р». Санитарные приборы "
              "и запорная арматура — по заданию АР. Теплоизоляция (вспененный каучук) принята "
              "на магистрали и стояки В1 и Т3-Т4 (от конденсата и теплопотерь, СП 30 п.8.11); "
              "толщина рассчитана алгоритмом legacy SP calculator по СП 61 для заданных "
              "температуры и влажности. Трубы В2 приняты по длинам расчётной сети стадии П. "
              "Крепления рассчитаны минимально по длинам и предельному шагу СП 73.13330.2016 "
              "и СП 41-109-2005; дополнительные крепления у арматуры, поворотов и ответвлений "
              "уточняются на стадии «Р». Фасонные части "
              "в спецификацию не включены (ГОСТ 21.601-2011 п.9.4). Единицы — по ГОСТ 21.110 п.9.5."),
    )
