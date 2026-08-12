"""Координатная модель принципиальной схемы К1/К2/К3.

Модель отделяет инженерную семантику ``Project`` от геометрии листа. Участки
трубопроводов и элементы не создаются рендерером: каждая размещённая линия
ссылается на ``SewerPipeSpec``, каждый знак — на ``SewerElementSpec``.

Координаты задаются в миллиметрах листа. Это позволяет использовать одну
модель для самостоятельной схемы по приложению В ГОСТ Р 21.620-2023 и для
схемы, наложенной на подтверждённый архитектурный разрез.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from app.pz.project import Project


class WastewaterLayoutMode(str, Enum):
    """Способ формирования графической части."""

    STANDALONE = "standalone"
    ARCHITECTURE_UNDERLAY = "architecture_underlay"


class WastewaterLayoutSource(str, Enum):
    """Основание для положения объекта на листе."""

    PROJECT_REGISTRY = "project_registry"
    ARCHITECTURE = "architecture"
    MANUAL_CONFIRMED = "manual_confirmed"


@dataclass(frozen=True)
class PointMm:
    x: float
    y: float


@dataclass(frozen=True)
class RectMm:
    x: float
    y: float
    width: float
    height: float

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    def contains(self, point: PointMm, tolerance: float = 0.0) -> bool:
        return (
            self.x - tolerance <= point.x <= self.x2 + tolerance
            and self.y - tolerance <= point.y <= self.y2 + tolerance
        )


@dataclass(frozen=True)
class WastewaterUnderlay:
    """Подтверждённая подложка АР и область её размещения на листе."""

    source_path: str
    page_number: int = 1
    frame: RectMm = RectMm(20.0, 15.0, 816.0, 574.0)
    opacity: float = 0.35
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterFloorGroup:
    """Один показанный уровень или группа повторяющихся этажей."""

    group_id: str
    label: str
    floors: Tuple[int, ...]
    elevation_m: Optional[float]
    y_mm: float
    kind: str = "floor"  # roof / floor / basement / technical
    source: WastewaterLayoutSource = WastewaterLayoutSource.MANUAL_CONFIRMED
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterSpace:
    """Помещение или шахта, показанные в архитектурной части схемы."""

    space_id: str
    group_id: str
    label: str
    frame: RectMm
    kind: str = "room"  # room / shaft / corridor / technical
    source: WastewaterLayoutSource = WastewaterLayoutSource.ARCHITECTURE
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterNodePlacement:
    """Размещение семантического узла графа на конкретной группе этажей."""

    placement_id: str
    node_id: str
    system: str
    point: PointMm
    group_id: str = ""
    kind: str = "junction"  # riser / junction / outlet / vent / funnel
    source: WastewaterLayoutSource = WastewaterLayoutSource.PROJECT_REGISTRY
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterRoutePlacement:
    """Ломаная реального участка из ``Project.sewage.pipes``."""

    route_id: str
    section_id: str
    system: str
    from_placement_id: str
    to_placement_id: str
    points: Tuple[PointMm, ...]
    group_id: str = ""
    show_mark: bool = True
    source: WastewaterLayoutSource = WastewaterLayoutSource.PROJECT_REGISTRY
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterElementPlacement:
    """Экземпляр УГО элемента, зарегистрированного в проекте."""

    placement_id: str
    element_id: str
    point: PointMm
    group_id: str = ""
    rotation_deg: float = 0.0
    quantity_label: str = ""
    source: WastewaterLayoutSource = WastewaterLayoutSource.PROJECT_REGISTRY
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterAnnotation:
    annotation_id: str
    text: str
    point: PointMm
    leader_to: Optional[PointMm] = None
    group_id: str = ""
    source: WastewaterLayoutSource = WastewaterLayoutSource.MANUAL_CONFIRMED
    source_ref: str = ""


@dataclass(frozen=True)
class WastewaterSlab:
    """Конструктивная плита, необходимая для чтения разреза."""

    slab_id: str
    frame: RectMm
    kind: str = "floor_slab"  # floor_slab / basement_foundation_slab
    hatch: str = "none"  # none / diagonal
    source: WastewaterLayoutSource = WastewaterLayoutSource.ARCHITECTURE
    source_ref: str = ""


@dataclass
class WastewaterSchemeLayout:
    """Полная графическая модель одного листа."""

    mode: WastewaterLayoutMode
    sheet_width_mm: float = 841.0
    sheet_height_mm: float = 594.0
    drawing_frame: RectMm = RectMm(20.0, 5.0, 816.0, 584.0)
    underlay: Optional[WastewaterUnderlay] = None
    floor_groups: List[WastewaterFloorGroup] = field(default_factory=list)
    spaces: List[WastewaterSpace] = field(default_factory=list)
    nodes: List[WastewaterNodePlacement] = field(default_factory=list)
    routes: List[WastewaterRoutePlacement] = field(default_factory=list)
    elements: List[WastewaterElementPlacement] = field(default_factory=list)
    annotations: List[WastewaterAnnotation] = field(default_factory=list)
    slabs: List[WastewaterSlab] = field(default_factory=list)
    individual_floors_required: bool = True


@dataclass(frozen=True)
class WastewaterLayoutIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass
class WastewaterLayoutAudit:
    errors: List[WastewaterLayoutIssue] = field(default_factory=list)
    warnings: List[WastewaterLayoutIssue] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors


def _same_point(a: PointMm, b: PointMm, tolerance_mm: float) -> bool:
    return math.hypot(a.x - b.x, a.y - b.y) <= tolerance_mm


def _duplicates(values: Sequence[str]) -> List[str]:
    seen = set()
    duplicate = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate)


def audit_wastewater_layout(
    project: Project,
    layout: WastewaterSchemeLayout,
    *,
    endpoint_tolerance_mm: float = 0.2,
    require_source_refs: bool = True,
) -> WastewaterLayoutAudit:
    """Проверить геометрию и её связь с подтверждённым реестром проекта."""
    result = WastewaterLayoutAudit()

    def error(code: str, message: str):
        result.errors.append(WastewaterLayoutIssue(code, message, "error"))

    def warning(code: str, message: str):
        result.warnings.append(WastewaterLayoutIssue(code, message, "warning"))

    if layout.sheet_width_mm <= 0 or layout.sheet_height_mm <= 0:
        error("sheet.size", "размеры листа должны быть положительными")
        return result
    sheet = RectMm(0.0, 0.0, layout.sheet_width_mm, layout.sheet_height_mm)
    if layout.drawing_frame.width <= 0 or layout.drawing_frame.height <= 0:
        error("sheet.frame", "размеры рабочей рамки должны быть положительными")
    for point in (
        PointMm(layout.drawing_frame.x, layout.drawing_frame.y),
        PointMm(layout.drawing_frame.x2, layout.drawing_frame.y2),
    ):
        if not sheet.contains(point):
            error("sheet.frame", "рабочая рамка выходит за границы листа")

    if layout.mode == WastewaterLayoutMode.ARCHITECTURE_UNDERLAY:
        if layout.underlay is None:
            error("underlay.missing", "для режима по подложке АР требуется подложка")
        else:
            if layout.underlay.page_number < 1:
                error("underlay.page", "номер страницы подложки должен быть не меньше 1")
            if not 0.0 <= layout.underlay.opacity <= 1.0:
                error("underlay.opacity", "прозрачность подложки должна быть от 0 до 1")
            if not layout.underlay.source_path:
                error("underlay.path", "не задан файл подложки АР")
            elif not Path(layout.underlay.source_path).exists():
                warning("underlay.unavailable", f"файл подложки недоступен: {layout.underlay.source_path}")
            if layout.underlay.frame.width <= 0 or layout.underlay.frame.height <= 0:
                error("underlay.frame", "размеры области подложки должны быть положительными")
            for point in (
                PointMm(layout.underlay.frame.x, layout.underlay.frame.y),
                PointMm(layout.underlay.frame.x2, layout.underlay.frame.y2),
            ):
                if not sheet.contains(point):
                    error("underlay.frame", "область подложки выходит за границы листа")
            if require_source_refs and not layout.underlay.source_ref:
                error("underlay.source", "не указана ссылка на подтверждённую подложку АР")

    collections = {
        "floor_group": [row.group_id for row in layout.floor_groups],
        "space": [row.space_id for row in layout.spaces],
        "node": [row.placement_id for row in layout.nodes],
        "route": [row.route_id for row in layout.routes],
        "element": [row.placement_id for row in layout.elements],
        "annotation": [row.annotation_id for row in layout.annotations],
        "slab": [row.slab_id for row in layout.slabs],
    }
    for kind, identifiers in collections.items():
        if any(not value for value in identifiers):
            error(f"{kind}.empty_id", f"{kind}: обнаружен пустой идентификатор")
        for value in _duplicates(identifiers):
            error(f"{kind}.duplicate", f"{kind}: идентификатор {value!r} повторяется")

    groups: Dict[str, WastewaterFloorGroup] = {
        row.group_id: row for row in layout.floor_groups
    }
    nodes: Dict[str, WastewaterNodePlacement] = {
        row.placement_id: row for row in layout.nodes
    }
    project_pipes = {row.section_id: row for row in project.sewage.pipes}
    project_elements = {row.element_id: row for row in project.sewage.elements}
    project_node_systems: Dict[str, set] = {}
    for pipe in project.sewage.pipes:
        project_node_systems.setdefault(pipe.from_node, set()).add(pipe.system)
        project_node_systems.setdefault(pipe.to_node, set()).add(pipe.system)

    def check_point(code: str, owner: str, point: PointMm):
        if not math.isfinite(point.x) or not math.isfinite(point.y):
            error(code, f"{owner}: координата должна быть конечным числом")
        elif not sheet.contains(point):
            error(code, f"{owner}: точка ({point.x:g}; {point.y:g}) вне листа")

    def check_group(code: str, owner: str, group_id: str):
        if group_id and group_id not in groups:
            error(code, f"{owner}: неизвестная группа этажей {group_id!r}")

    for group in layout.floor_groups:
        check_point("floor_group.point", group.group_id, PointMm(0.0, group.y_mm))
        if not group.floors and group.kind == "floor":
            error("floor_group.floors", f"{group.group_id}: не заданы этажи")
        if len(set(group.floors)) != len(group.floors):
            error("floor_group.floors", f"{group.group_id}: этажи повторяются")
        if layout.individual_floors_required and group.kind == "floor" and len(group.floors) != 1:
            error(
                "floor_group.individual",
                f"{group.group_id}: каждый надземный этаж должен иметь отдельную полосу",
            )
        if require_source_refs and not group.source_ref:
            error("floor_group.source", f"{group.group_id}: не указано основание положения")

    if layout.individual_floors_required:
        shown_floors = [
            floor
            for group in layout.floor_groups
            if group.kind == "floor"
            for floor in group.floors
        ]
        expected_floors = list(range(1, max(1, int(project.building.floors_above or 1)) + 1))
        missing = sorted(set(expected_floors) - set(shown_floors))
        extra = sorted(set(shown_floors) - set(expected_floors))
        repeated = _duplicates([str(value) for value in shown_floors])
        if missing:
            error("floor.coverage", "на схеме отсутствуют этажи: " + ", ".join(map(str, missing)))
        if extra:
            error("floor.coverage", "на схеме есть этажи вне здания: " + ", ".join(map(str, extra)))
        if repeated:
            error("floor.coverage", "этажи показаны повторно: " + ", ".join(repeated))

    for space in layout.spaces:
        check_group("space.group", space.space_id, space.group_id)
        if space.frame.width <= 0 or space.frame.height <= 0:
            error("space.frame", f"{space.space_id}: размеры помещения должны быть положительными")
        for point in (PointMm(space.frame.x, space.frame.y), PointMm(space.frame.x2, space.frame.y2)):
            check_point("space.frame", space.space_id, point)
        if require_source_refs and not space.source_ref:
            error("space.source", f"{space.space_id}: не указана ссылка на АР/подтверждение")

    for node in layout.nodes:
        check_point("node.point", node.placement_id, node.point)
        check_group("node.group", node.placement_id, node.group_id)
        if node.system not in {"K1", "K2", "K3"}:
            error("node.system", f"{node.placement_id}: неизвестная система {node.system!r}")
        elif node.node_id not in project_node_systems:
            error("node.registry", f"{node.placement_id}: узел {node.node_id!r} отсутствует в графе проекта")
        elif node.system not in project_node_systems[node.node_id]:
            error(
                "node.system",
                f"{node.placement_id}: узел {node.node_id!r} не относится к системе {node.system}",
            )
        if require_source_refs and not node.source_ref:
            error("node.source", f"{node.placement_id}: не указано основание положения")

    for route in layout.routes:
        check_group("route.group", route.route_id, route.group_id)
        pipe = project_pipes.get(route.section_id)
        if pipe is None:
            error("route.section", f"{route.route_id}: неизвестный участок {route.section_id!r}")
        elif pipe.system != route.system:
            error(
                "route.system",
                f"{route.route_id}: система {route.system} не совпадает с {pipe.system} у {route.section_id}",
            )
        start = nodes.get(route.from_placement_id)
        end = nodes.get(route.to_placement_id)
        if start is None:
            error("route.from", f"{route.route_id}: неизвестный начальный узел {route.from_placement_id!r}")
        if end is None:
            error("route.to", f"{route.route_id}: неизвестный конечный узел {route.to_placement_id!r}")
        if len(route.points) < 2:
            error("route.points", f"{route.route_id}: требуется не менее двух точек")
        else:
            for point in route.points:
                check_point("route.point", route.route_id, point)
            if start and not _same_point(route.points[0], start.point, endpoint_tolerance_mm):
                error("route.endpoint", f"{route.route_id}: начало линии не совпадает с узлом")
            if end and not _same_point(route.points[-1], end.point, endpoint_tolerance_mm):
                error("route.endpoint", f"{route.route_id}: конец линии не совпадает с узлом")
        if start and start.system != route.system:
            error("route.node_system", f"{route.route_id}: начальный узел относится к {start.system}")
        if end and end.system != route.system:
            error("route.node_system", f"{route.route_id}: конечный узел относится к {end.system}")
        if pipe and start and start.node_id != pipe.from_node:
            error(
                "route.topology",
                f"{route.route_id}: начальный узел {start.node_id!r} не совпадает с {pipe.from_node!r}",
            )
        if pipe and end and end.node_id != pipe.to_node:
            error(
                "route.topology",
                f"{route.route_id}: конечный узел {end.node_id!r} не совпадает с {pipe.to_node!r}",
            )
        if require_source_refs and not route.source_ref:
            error("route.source", f"{route.route_id}: не указано основание трассы")

    for placement in layout.elements:
        check_point("element.point", placement.placement_id, placement.point)
        check_group("element.group", placement.placement_id, placement.group_id)
        element = project_elements.get(placement.element_id)
        if element is None:
            error(
                "element.registry",
                f"{placement.placement_id}: неизвестный элемент {placement.element_id!r}",
            )
        elif placement.group_id and placement.group_id in groups:
            group_floors = groups[placement.group_id].floors
            floor_to = element.floor_to if element.floor_to is not None else element.floor_from
            if group_floors and not any(element.floor_from <= floor <= floor_to for floor in group_floors):
                error(
                    "element.floor",
                    f"{placement.placement_id}: элемент не применяется к этажам группы {placement.group_id}",
                )
        if require_source_refs and not placement.source_ref:
            error("element.source", f"{placement.placement_id}: не указано основание положения")

    for annotation in layout.annotations:
        check_point("annotation.point", annotation.annotation_id, annotation.point)
        if annotation.leader_to is not None:
            check_point("annotation.leader", annotation.annotation_id, annotation.leader_to)
        check_group("annotation.group", annotation.annotation_id, annotation.group_id)
        if not annotation.text.strip():
            error("annotation.text", f"{annotation.annotation_id}: пустая надпись")
        if require_source_refs and not annotation.source_ref:
            error("annotation.source", f"{annotation.annotation_id}: не указано основание надписи")

    foundation_slabs = []
    for slab in layout.slabs:
        if slab.frame.width <= 0 or slab.frame.height <= 0:
            error("slab.frame", f"{slab.slab_id}: размеры плиты должны быть положительными")
        for point in (
            PointMm(slab.frame.x, slab.frame.y),
            PointMm(slab.frame.x2, slab.frame.y2),
        ):
            check_point("slab.frame", slab.slab_id, point)
        if slab.kind not in {"floor_slab", "basement_foundation_slab"}:
            error("slab.kind", f"{slab.slab_id}: неизвестный вид плиты {slab.kind!r}")
        if slab.hatch not in {"none", "diagonal"}:
            error("slab.hatch", f"{slab.slab_id}: неизвестная штриховка {slab.hatch!r}")
        if slab.kind == "basement_foundation_slab":
            foundation_slabs.append(slab)
            if slab.hatch != "diagonal":
                error(
                    "slab.foundation_hatch",
                    f"{slab.slab_id}: фундаментная плита подвала должна иметь диагональную штриховку",
                )
        if require_source_refs and not slab.source_ref:
            error("slab.source", f"{slab.slab_id}: не указано основание конструкции")

    has_basement = any(group.kind in {"basement", "technical"} for group in layout.floor_groups)
    if has_basement and not foundation_slabs:
        error(
            "slab.foundation_missing",
            "под подвальным/техническим уровнем не задана фундаментная плита",
        )
    if len(foundation_slabs) > 1:
        error("slab.foundation_duplicate", "на одном листе задано несколько фундаментных плит")

    return result
