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
    # ТУ на подключение к водопроводу
    tu_org: str = ""                   # кто выдал ТУ (водоканал)
    tu_number: str = ""
    tu_date: str = ""
    connection_point: str = ""         # точка подключения
    guaranteed_head_m: Optional[float] = None   # гарантированный напор, м
    tu_limit_q_day: Optional[float] = None      # лимит, м³/сут
    tu_fire_outdoor_l_s: Optional[float] = None # наружное пожаротушение, л/с
    water_main_dn: int = 0             # диаметр городского водовода

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


@dataclass
class MainRunRequest:
    """Участок магистрали между узлами."""
    from_node: str
    to_node: str
    length_m: float
    dn: int = 100
    equiv_length_m: float = 0.0
    A: float = 0.0023


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
class IOS2Request:
    """Полное намерение: «спроектируй мне ИОС2 для такого объекта»."""
    document: DocumentRequest
    building_type: str                            # BUILDING_TYPES
    floors: int
    building_height_m: float
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
        if self.streams is not None and self.streams not in (1, 2):
            p.append(f"streams={self.streams}: поддерживается 1 или 2")
        if not self.document.cipher:
            p.append("document.cipher обязателен")
        if not self.document.object_name:
            p.append("document.object_name обязателен")
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
