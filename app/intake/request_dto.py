# -*- coding: utf-8 -*-
"""
app/intake/request_dto.py — входное намерение проектировщика (Request DTO).

Слой 1 цепочки ввода:
    Wizard / IFC / Excel / YAML / REST / CLI
            ↓  отдают НАМЕРЕНИЕ, не Project
       Request DTO   (этот модуль)
            ↓
      Project Builder (app/intake/project_builder.py)
            ↓
         Project → design_ios2()

DTO описывает объект в терминах ПРОЕКТИРОВЩИКА (тип здания, этажи, коридор,
стояки), а не в терминах модели (BuildingPurpose, FireNetworkSpec, dataclass'ы).
Форма и любые будущие входы не знают про Project вообще — они собирают этот DTO.

Здесь НЕТ логики сборки Project и НЕТ расчётов — только данные намерения
и их первичная валидация (типы, диапазоны, обязательность).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── справочники значений (строки — то, что придёт из формы/YAML/API) ────────

BUILDING_TYPES = ("residential", "public", "industrial")
SOURCE_KINDS = ("city_main", "reservoir", "pond", "well")
SPACE_KINDS = ("corridor", "room", "hall", "storage")
PLACEMENT_MODES = ("one_side", "two_opposite_sides")


@dataclass
class DocumentRequest:
    """Кто/что/шифр — реквизиты комплекта."""
    cipher: str
    object_name: str
    organization: str
    object_address: str = ""
    object_part: str = ""
    stage: str = "П"
    developer: str = ""
    inspector: str = ""
    dept_head: str = ""
    gip: str = ""
    norm_control: str = ""


@dataclass
class SourceDataRequest:
    """Исходные данные проектирования: заказчик, основание, ТУ на подключение.
    Всё — то, что проектировщик получает НА ВХОДЕ (не считает сам)."""
    customer: str = ""                 # заказчик
    designer_org: str = ""             # проектная организация (генпроектировщик)
    basis: str = ""                    # основание (договор №, дата)
    design_stage: str = "Проектная документация (П)"
    source_description: str = ""       # существующая централизованная сеть
    water_protection_note: str = ""    # подтверждение по ГПЗУ/ИОС1
    reserve_water_note: str = ""       # решение по резервированию воды
    # ТУ на подключение к водопроводу
    tu_org: str = ""                   # кто выдал ТУ (водоканал)
    tu_number: str = ""
    tu_date: str = ""
    connection_point: str = ""         # точка подключения
    guaranteed_head_m: Optional[float] = None   # гарантированный напор, м
    maximum_head_m: Optional[float] = None      # максимальный статический напор по ТУ, м
    tu_limit_q_day: Optional[float] = None      # лимит, м³/сут
    tu_fire_outdoor_l_s: Optional[float] = None # наружное пожаротушение, л/с
    water_main_dn: int = 0             # диаметр городского водовода
    # Расчёт требуемого напора В1 (формула (14) п. 8.27 СП 30.13330.2020).
    # Это исходные/расчётные величины проектировщика; Builder их не придумывает.
    elev_header_m: Optional[float] = None   # отметка оси ввода/напорного коллектора
    elev_fixture_m: Optional[float] = None  # отметка излива диктующего прибора
    h_geom_m: Optional[float] = None        # Hgeom напрямую, если отметок нет
    il_dict_m: Optional[float] = None       # i*l внутренней сети до учёта местных потерь
    h_il_m: Optional[float] = None          # готовая сумма потерь внутренней сети
    network_kind: str = "domestic"         # domestic / combined / fire
    h_pr_m: float = 20.0                    # свободный напор перед прибором
    h_tepl_m: float = 0.0                   # потери в теплообменнике/ИТП
    il_vvod_m: Optional[float] = None       # i*L ввода до коэффициента 1,1
    h_vvod_m: Optional[float] = None        # готовые потери на вводе
    water_use_period_h: float = 24.0        # период водопотребления для водомера
    inputs_count: int = 1                   # число вводов водопровода
    npsh_available_m: Optional[float] = None  # располагаемый кавитационный запас

@dataclass
class RoomRequest:
    """Помещение, где расставляются ПК (в терминах проектировщика)."""
    name: str
    length_m: float
    width_m: float
    height_m: float
    space_kind: str = "corridor"                 # SPACE_KINDS
    placement: str = "two_opposite_sides"        # PLACEMENT_MODES


@dataclass
class RiserRequest:
    """Стояк В2: где стоит и куда поднимается."""
    name: str                     # "СТ-В2-1"
    at_node: str                  # узел магистрали
    height_m: float               # длина стояка (подъём)
    cabinet_elevation_m: float    # отметка ПК
    dn: int = 65
    equiv_length_m: float = 0.0
    A: float = 0.011
    repair_section_id: str = ""   # ремонтная секция кольца


@dataclass
class MainRunRequest:
    """Участок магистрали между узлами."""
    from_node: str
    to_node: str
    length_m: float
    dn: int = 100
    equiv_length_m: float = 0.0
    A: float = 0.0023
    repair_section_id: str = ""       # секция между запорными устройствами


@dataclass
class NetworkRequest:
    """Сеть В2: узлы перечисляются неявно (из участков), кольцо/дерево — по факту."""
    runs: List[MainRunRequest] = field(default_factory=list)
    risers: List[RiserRequest] = field(default_factory=list)
    source_node: str = ""
    source_kind: str = "city_main"               # SOURCE_KINDS
    available_head_m: Optional[float] = None     # напор города (None → 0, уточнить)
    second_source_node: str = ""                 # второй ввод (пусто = один ввод)
    second_available_head_m: Optional[float] = None
    water_level_m: Optional[float] = None        # для резервуара/водоёма
    suction_head_loss_m: float = 0.0
    node_elevations: dict = field(default_factory=dict)   # {узел: отметка}, дефолт 0


@dataclass
class ConsumerGroupRequest:
    """Группа водопотребителей для расчёта расходов В1/Т3 (СП 30, табл. А.2)."""
    code: str                          # код типа потребителя (residential_central_hw и т.п.)
    count: int                         # число потребителей (жителей/мест/...)


@dataclass
class V1SectionRequest:
    """Участок диктующего направления хозяйственно-питьевого водопровода."""
    section_id: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    roughness_mm: float
    role: str = "internal"            # internal / input
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass
class V1NodeRequest:
    """Узел дерева В1 с отметкой и подключёнными потребителями."""
    node_id: str
    elevation_m: float
    consumers: List[ConsumerGroupRequest] = field(default_factory=list)
    direct_demand_lps: float = 0.0
    h_pr_m: float = 20.0
    max_static_head_m: float = 45.0


@dataclass
class V1NetworkSectionRequest:
    """Ориентированный участок В1; расход определяется по поддереву."""
    section_id: str
    from_node: str
    to_node: str
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    role: str = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: List[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass
class V1InletRequest:
    """Отдельный ввод В1, проверяемый на 100% расхода при отказе второго."""
    inlet_id: str
    guaranteed_head_m: float
    maximum_head_m: float
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: List[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass
class V1NetworkRequest:
    source_node: str
    nodes: List[V1NodeRequest] = field(default_factory=list)
    sections: List[V1NetworkSectionRequest] = field(default_factory=list)
    inlets: List[V1InletRequest] = field(default_factory=list)


@dataclass
class IOS2Request:
    """Полное намерение: «спроектируй мне ИОС2 для такого объекта»."""
    document: DocumentRequest
    building_type: str                            # BUILDING_TYPES
    floors: int
    building_height_m: float
    total_area_m2: float = 0.0
    risers_v1: int = 0
    risers_t3: int = 0
    risers_t4: int = 0
    insulation_location: str = "room_hot"
    insulation_t_room_manual: float = 5.0
    insulation_humidity: int = 60
    insulation_hvs_water_temp: float = 10.0
    insulation_gvs_water_temp: float = 60.0
    # ВПВ
    streams: Optional[int] = None                 # None → авто по табл. 7.1 (future)
    q_per_stream_lps: float = 2.6
    hose_length_m: int = 20
    cabinet_dn: int = 50
    rooms: List[RoomRequest] = field(default_factory=list)
    network: Optional[NetworkRequest] = None
    # прочее
    zones: int = 1
    needs_booster_pumps: bool = True
    source_data: Optional[SourceDataRequest] = None
    consumers: List[ConsumerGroupRequest] = field(default_factory=list)
    v1_sections: List[V1SectionRequest] = field(default_factory=list)
    v1_network: Optional[V1NetworkRequest] = None
    sewage_max_fixture_lps: float = 1.6  # q_0s по таблице А.1 СП 30, л/с
    storm_city: str = ""           # город для расчёта дождевого стока (К2)

    def validate(self) -> List[str]:
        """Первичная валидация намерения (типы/диапазоны/обязательность).
        Возвращает список проблем; пустой = вход пригоден для Builder."""
        p: List[str] = []
        if self.building_type not in BUILDING_TYPES:
            p.append(f"building_type '{self.building_type}' не из {BUILDING_TYPES}")
        if self.floors <= 0:
            p.append("floors должно быть > 0")
        if self.building_height_m <= 0:
            p.append("building_height_m должно быть > 0 (нужно для Rk п. 7.15)")
        if self.total_area_m2 < 0:
            p.append("total_area_m2 не может быть отрицательной")
        if min(self.risers_v1, self.risers_t3, self.risers_t4) < 0:
            p.append("число стояков В1/Т3/Т4 не может быть отрицательным")
        if self.insulation_location not in ("room_hot", "room_cold", "parking"):
            p.append("insulation_location должен быть room_hot, room_cold или parking")
        if self.insulation_humidity not in (40, 50, 60, 70, 80, 90):
            p.append("insulation_humidity должна быть 40, 50, 60, 70, 80 или 90")
        if self.streams is not None and self.streams not in (1, 2):
            p.append(f"streams={self.streams}: поддерживается 1 или 2")
        if self.sewage_max_fixture_lps < 0:
            p.append("sewage_max_fixture_lps не может быть отрицательным")
        seen_v1 = set()
        for i, s in enumerate(self.v1_sections):
            if not s.section_id or s.section_id in seen_v1:
                p.append(f"v1_sections[{i}]: обозначение пустое или повторяется")
            seen_v1.add(s.section_id)
            if min(s.length_m, s.inner_diameter_mm, s.flow_lps, s.velocity_limit_mps) <= 0:
                p.append(f"v1_sections[{i}]: L, dвн, q и предел скорости должны быть > 0")
            if s.roughness_mm < 0 or (s.local_loss_factor is not None and s.local_loss_factor < 0):
                p.append(f"v1_sections[{i}]: шероховатость и k_l не могут быть отрицательными")
            if s.role not in ("internal", "input"):
                p.append(f"v1_sections[{i}].role должен быть internal или input")
        vn = self.v1_network
        if vn is not None:
            node_ids = [n.node_id for n in vn.nodes]
            if not vn.source_node:
                p.append("v1_network.source_node обязателен")
            if not vn.nodes:
                p.append("v1_network.nodes пуст")
            if not vn.sections:
                p.append("v1_network.sections пуст")
            if len(set(node_ids)) != len(node_ids) or any(not x for x in node_ids):
                p.append("v1_network: обозначения узлов должны быть непустыми и уникальными")
            if vn.source_node and vn.source_node not in node_ids:
                p.append(f"v1_network.source_node '{vn.source_node}' отсутствует в узлах")
            for i, node in enumerate(vn.nodes):
                if node.direct_demand_lps < 0 or node.h_pr_m < 0:
                    p.append(f"v1_network.nodes[{i}]: расход и Hпр не могут быть отрицательными")
                if node.max_static_head_m <= 0:
                    p.append(f"v1_network.nodes[{i}].max_static_head_m должен быть > 0")
                for j, group in enumerate(node.consumers):
                    if not group.code or group.count <= 0:
                        p.append(f"v1_network.nodes[{i}].consumers[{j}]: нужен код и количество > 0")
            section_ids = set()
            for i, section in enumerate(vn.sections):
                if not section.section_id or section.section_id in section_ids:
                    p.append(f"v1_network.sections[{i}]: обозначение пустое или повторяется")
                section_ids.add(section.section_id)
                if section.from_node not in node_ids or section.to_node not in node_ids:
                    p.append(f"v1_network.sections[{i}]: начальный или конечный узел отсутствует")
                if section.from_node == section.to_node:
                    p.append(f"v1_network.sections[{i}]: начало и конец совпадают")
                if min(section.length_m, section.velocity_limit_mps) <= 0:
                    p.append(f"v1_network.sections[{i}]: L и предел скорости должны быть > 0")
                if section.inner_diameter_mm is not None and section.inner_diameter_mm <= 0:
                    p.append(f"v1_network.sections[{i}].inner_diameter_mm должен быть > 0")
                if section.inner_diameter_mm is None:
                    if (not section.candidate_inner_diameters_mm
                            or any(d <= 0 for d in section.candidate_inner_diameters_mm)):
                        p.append(f"v1_network.sections[{i}]: для автоподбора нужен положительный сортамент dвн")
                    if (section.max_specific_loss_m_per_m is None
                            or section.max_specific_loss_m_per_m <= 0):
                        p.append(f"v1_network.sections[{i}]: для автоподбора нужен iдоп > 0")
                if (section.roughness_mm < 0 or
                        (section.local_loss_factor is not None and section.local_loss_factor < 0)):
                    p.append(f"v1_network.sections[{i}]: шероховатость и k_l не могут быть отрицательными")
                if (section.max_specific_loss_m_per_m is not None
                        and section.max_specific_loss_m_per_m <= 0):
                    p.append(f"v1_network.sections[{i}].max_specific_loss_m_per_m должен быть > 0")
                if section.role not in ("internal", "input"):
                    p.append(f"v1_network.sections[{i}].role должен быть internal или input")
            if vn.inlets and any(section.role == "input" for section in vn.sections):
                p.append("v1_network: при явных inlets участки дерева должны иметь role=internal")
            inlet_ids = set()
            for i, inlet in enumerate(vn.inlets):
                if not inlet.inlet_id or inlet.inlet_id in inlet_ids:
                    p.append(f"v1_network.inlets[{i}]: обозначение пустое или повторяется")
                inlet_ids.add(inlet.inlet_id)
                if inlet.inlet_id in section_ids:
                    p.append(f"v1_network.inlets[{i}]: обозначение совпадает с участком сети")
                if min(inlet.guaranteed_head_m, inlet.maximum_head_m,
                       inlet.length_m, inlet.velocity_limit_mps) <= 0:
                    p.append(f"v1_network.inlets[{i}]: напоры, L и предел скорости должны быть > 0")
                if inlet.maximum_head_m < inlet.guaranteed_head_m:
                    p.append(f"v1_network.inlets[{i}]: Hмакс не может быть меньше Hгар")
                if inlet.inner_diameter_mm is not None and inlet.inner_diameter_mm <= 0:
                    p.append(f"v1_network.inlets[{i}].inner_diameter_mm должен быть > 0")
                if inlet.inner_diameter_mm is None:
                    if (not inlet.candidate_inner_diameters_mm
                            or any(d <= 0 for d in inlet.candidate_inner_diameters_mm)):
                        p.append(f"v1_network.inlets[{i}]: для автоподбора нужен положительный сортамент dвн")
                    if (inlet.max_specific_loss_m_per_m is None
                            or inlet.max_specific_loss_m_per_m <= 0):
                        p.append(f"v1_network.inlets[{i}]: для автоподбора нужен iдоп > 0")
                if (inlet.roughness_mm < 0 or
                        (inlet.local_loss_factor is not None and inlet.local_loss_factor < 0)):
                    p.append(f"v1_network.inlets[{i}]: шероховатость и k_l не могут быть отрицательными")
        if not self.document.cipher:
            p.append("document.cipher обязателен")
        if not self.document.object_name:
            p.append("document.object_name обязателен")
        sd = self.source_data
        if sd is not None:
            if (sd.elev_header_m is None) != (sd.elev_fixture_m is None):
                p.append("source_data: отметки elev_header_m и elev_fixture_m задаются парой")
            if (sd.elev_header_m is not None and sd.elev_fixture_m is not None
                    and sd.elev_fixture_m < sd.elev_header_m):
                p.append("source_data: отметка диктующего прибора ниже отметки ввода")
            if sd.network_kind not in ("domestic", "combined", "fire"):
                p.append("source_data.network_kind должен быть domestic, combined или fire")
            if sd.water_use_period_h <= 0:
                p.append("source_data.water_use_period_h должно быть > 0")
            if sd.inputs_count <= 0:
                p.append("source_data.inputs_count должно быть > 0")
            nonnegative = {
                "h_geom_m": sd.h_geom_m, "il_dict_m": sd.il_dict_m,
                "h_il_m": sd.h_il_m, "h_pr_m": sd.h_pr_m,
                "h_tepl_m": sd.h_tepl_m, "il_vvod_m": sd.il_vvod_m,
                "h_vvod_m": sd.h_vvod_m, "npsh_available_m": sd.npsh_available_m,
                "guaranteed_head_m": sd.guaranteed_head_m,
                "maximum_head_m": sd.maximum_head_m,
            }
            for name, value in nonnegative.items():
                if value is not None and value < 0:
                    p.append(f"source_data.{name} не может быть отрицательным")
            if (sd.guaranteed_head_m is not None and sd.maximum_head_m is not None
                    and sd.maximum_head_m < sd.guaranteed_head_m):
                p.append("source_data.maximum_head_m не может быть меньше guaranteed_head_m")
        for i, r in enumerate(self.rooms):
            if r.space_kind not in SPACE_KINDS:
                p.append(f"rooms[{i}].space_kind '{r.space_kind}' не из {SPACE_KINDS}")
            if r.placement not in PLACEMENT_MODES:
                p.append(f"rooms[{i}].placement '{r.placement}' не из {PLACEMENT_MODES}")
            if min(r.length_m, r.width_m, r.height_m) <= 0:
                p.append(f"rooms[{i}]: размеры должны быть > 0")
        n = self.network
        if n is not None:
            if n.source_kind not in SOURCE_KINDS:
                p.append(f"network.source_kind '{n.source_kind}' не из {SOURCE_KINDS}")
            if not n.source_node:
                p.append("network.source_node обязателен")
            if not n.runs:
                p.append("network.runs пуст — нет магистрали")
            if not n.risers:
                p.append("network.risers пуст — нет стояков с ПК")
            run_nodes = {x for r in n.runs for x in (r.from_node, r.to_node)}
            if n.source_node and n.source_node not in run_nodes:
                p.append(f"source_node '{n.source_node}' не встречается в участках магистрали")
            for i, r in enumerate(n.risers):
                if r.at_node not in run_nodes:
                    p.append(f"risers[{i}] '{r.name}': узел '{r.at_node}' не в магистрали")
            if n.second_source_node:
                if n.second_source_node not in run_nodes:
                    p.append(f"второй ввод '{n.second_source_node}' не в магистрали")
                if n.second_source_node == n.source_node:
                    p.append("второй ввод совпадает с первым — уберите или переставьте")
                if n.second_available_head_m is None:
                    p.append("для второго ввода нужен его напор (second_available_head_m)")
            # ── связность: вся магистраль достижима от источника (BFS) ──
            if n.source_node in run_nodes and n.runs:
                adj: dict = {}
                for r in n.runs:
                    adj.setdefault(r.from_node, set()).add(r.to_node)
                    adj.setdefault(r.to_node, set()).add(r.from_node)
                seen = {n.source_node}
                stack = [n.source_node]
                while stack:
                    for nb in adj.get(stack.pop(), ()):
                        if nb not in seen:
                            seen.add(nb)
                            stack.append(nb)
                orphans = sorted(run_nodes - seen)
                if orphans:
                    p.append(f"магистраль разорвана: узлы {', '.join(orphans)} не связаны "
                             f"с источником '{n.source_node}' — проверьте участки (runs)")
                for r in n.risers:
                    if r.at_node in run_nodes and r.at_node not in seen:
                        p.append(f"стояк '{r.name}' висит на недостижимом узле "
                                 f"'{r.at_node}' — вода до него не дойдёт")
            # ── дубли ──
            pairs = [frozenset((r.from_node, r.to_node)) for r in n.runs]
            if len(set(pairs)) < len(pairs):
                p.append("в магистрали есть дублирующиеся участки (одна и та же пара узлов)")
            names = [r.name for r in n.risers]
            if len(set(names)) < len(names):
                p.append("имена стояков повторяются — должны быть уникальны")
        return p
