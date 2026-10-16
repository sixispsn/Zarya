"""Explicit fan ventilation detail graphs; control sheets, NOT a release adapter.

Paper geometry is derived from supplied levels/positions. No collector, valve,
roof type, room height or airflow calculation is invented by the renderer.
These graphs can be bound to the canonical building in the explicit control
adapter wastewater_fan_binding. The production release gate remains separate
until geometry/equipment confirmation is collected by the regular input path.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from math import isfinite
from pathlib import Path
from xml.etree import ElementTree as ET

from app.pz.drafting_font import DRAFTING_FONT_FAMILY, ensure_drafting_font_registered
from app.pz.drawing_sheet_style import DrawingSheetStyle
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest, _text_width
from app.pz.wastewater_drafting import render_inline_pipe_label
from app.pz.wastewater_ventilation import FanRiser, FanTerminal, FanVentilationInput, audit_fan_ventilation
from app.pz.wastewater_fan_geometry import (
    FanRiserPosition as FanRiserPosition,
    FanRoofDetail as FanRoofDetail,
    FanValveDetail as FanValveDetail,
)

STYLE = DrawingSheetStyle(units_per_mm=1)
HL900N_DRAWING = "https://www.hutterer-lechner.com/upload/HL900N_a.pdf"
CONTROL_BORDER = ('<rect data-fan-control-border="true" x="20" y="5" width="395" height="287" '
                  'fill="none" stroke="black" stroke-width=".6"/>')


@dataclass(frozen=True)
class FanDetailNode:
    node_id: str
    x_m: float
    level_m: float
    role: str
    source_id: str


@dataclass(frozen=True)
class FanDetailEdge:
    edge_id: str
    start: str
    end: str
    dn_mm: float
    role: str


@dataclass(frozen=True)
class FanDetailGraph:
    terminal_id: str
    nodes: tuple[FanDetailNode, ...]
    edges: tuple[FanDetailEdge, ...]

    def node(self, key: str) -> FanDetailNode:
        return next(n for n in self.nodes if n.node_id == key)

    def validate(self) -> None:
        ids = {n.node_id for n in self.nodes}
        if len(ids) != len(self.nodes) or len({e.edge_id for e in self.edges}) != len(self.edges):
            raise ValueError("duplicate fan graph IDs")
        links: dict[str, set[str]] = {i: set() for i in ids}
        for n in self.nodes:
            if not all(isfinite(v) for v in (n.x_m, n.level_m)):
                raise ValueError("non-finite fan coordinates")
        for edge in self.edges:
            if edge.start not in ids or edge.end not in ids or edge.start == edge.end:
                raise ValueError("unbound fan edge")
            if not isfinite(edge.dn_mm) or edge.dn_mm <= 0:
                raise ValueError("missing fan edge DN")
            links[edge.start].add(edge.end)
            links[edge.end].add(edge.start)
        endings = [n for n in self.nodes if n.role in {"open_end", "valve"}]
        if len(endings) != 1:
            raise ValueError("fan graph must have exactly one declared ending")
        seen, todo = set(), [endings[0].node_id]
        while todo:
            node = todo.pop()
            if node not in seen:
                seen.add(node)
                todo.extend(links[node] - seen)
        if seen != ids:
            raise ValueError("disconnected fan graph")
        if any(len(links[n.node_id]) != 1 for n in self.nodes if n.role in {"riser_port", "open_end", "valve"}):
            raise ValueError("ending must have exactly one connection")
        if any(len(links[n.node_id]) < 2 for n in self.nodes if n.role == "collector_join"):
            raise ValueError("unexplained free collector end")


@dataclass(frozen=True)
class FanDetailsInput:
    roof_kind: str
    risers: tuple[FanRiser, ...]
    evidence: FanVentilationInput
    roofs: tuple[FanRoofDetail, ...]
    valves: tuple[FanValveDetail, ...]
    residential: bool = True

    def terminal(self, key: str) -> FanTerminal:
        return next(t for t in self.evidence.terminals if t.terminal_id == key)

    def validate(self) -> None:
        audit = audit_fan_ventilation(roof_kind=self.roof_kind, risers=self.risers,
                                     evidence=self.evidence, residential=self.residential)
        if not audit.ready:
            raise ValueError("fan validation not complete: " + "; ".join(audit.reasons))
        all_details: tuple[FanRoofDetail | FanValveDetail, ...] = (*self.roofs, *self.valves)
        details = [d.terminal_id for d in all_details]
        if not details:
            raise ValueError("no ventilation details to draw")
        if len(details) != len(set(details)) or set(details) != {t.terminal_id for t in self.evidence.terminals}:
            raise ValueError("each terminal needs exactly one graphic detail")
        for d in all_details:
            if not d.source_ref.strip() or not isfinite(d.scale) or d.scale <= 0:
                raise ValueError("explicit geometry source and positive scale required")
        for d in self.roofs:
            t = self.terminal(d.terminal_id)
            if t.kind != "roof" or len(d.risers) != len(t.riser_ids) or {r.riser_id for r in d.risers} != set(t.riser_ids):
                raise ValueError("roof detail membership differs from approved group")
            if d.vent_riser_id not in t.riser_ids or d.condensate_riser_id not in t.riser_ids:
                raise ValueError("vent/condensate connection must reference a real group riser")
            if not isfinite(d.roof_level_m) or any(
                not all(isfinite(v) for v in (r.x_m, r.lower_port_m, r.collector_m))
                or not r.lower_port_m < r.collector_m < d.roof_level_m for r in d.risers
            ):
                raise ValueError("roof/collector/lower-port levels conflict")
            ordered = sorted(d.risers, key=lambda r: r.x_m)
            if len({r.x_m for r in ordered}) != len(ordered):
                raise ValueError("distinct risers cannot occupy the same detail axis")
            # This first detail topology drains towards one explicit END riser.
            # A branched ridge collector is a separate future topology, not a
            # silently approximated alternative.
            if ordered[-1].riser_id == d.condensate_riser_id:
                ordered.reverse()
            if ordered[0].riser_id != d.condensate_riser_id or any(
                b.collector_m <= a.collector_m for a, b in zip(ordered, ordered[1:])
            ):
                raise ValueError("collector must drain monotonically to its declared end riser")
            build_roof_detail_graph(self, d).validate()
        for d in self.valves:
            if self.terminal(d.terminal_id).kind != "valve":
                raise ValueError("valve drawing cannot replace an open ending")
            if d.outline_ref != HL900N_DRAWING:
                raise ValueError("unsupported valve contour reference")
            if d.connection_outer_diameter_mm != 110:
                raise ValueError("this valve outline requires an explicit 110 mm connection; reducer not drawn")
            levels = (d.floor_level_m, d.highest_fixture_rim_m, d.connection_level_m, d.ceiling_level_m)
            if not all(isfinite(v) for v in levels) or not (
                d.floor_level_m < d.highest_fixture_rim_m < d.connection_level_m
                and d.connection_level_m + .192 < d.ceiling_level_m
            ):
                raise ValueError("valve must be above fixture rim and below the ceiling")
            build_valve_detail_graph(self, d).validate()


def build_roof_detail_graph(data: FanDetailsInput, detail: FanRoofDetail) -> FanDetailGraph:
    t = data.terminal(detail.terminal_id)
    riser_dn = {r.riser_id: r.diameter_mm for r in data.risers}
    nodes: list[FanDetailNode] = []
    edges: list[FanDetailEdge] = []
    ordered = sorted(detail.risers, key=lambda r: r.x_m)
    for p in ordered:
        nodes.extend((FanDetailNode(p.riser_id, p.x_m, p.lower_port_m, "riser_port", p.riser_id),
                      FanDetailNode("join:"+p.riser_id, p.x_m, p.collector_m, "collector_join", p.riser_id)))
        edges.append(FanDetailEdge("riser:"+p.riser_id, p.riser_id, "join:"+p.riser_id,
                                   float(riser_dn[p.riser_id] or 0), "riser_vent"))
    for i, (a, b) in enumerate(zip(ordered, ordered[1:])):
        edges.append(FanDetailEdge(f"collector:{i}", "join:"+a.riser_id, "join:"+b.riser_id,
                                   float(t.collector_diameter_mm or 0), "vent_collector"))
    vent = next(p for p in ordered if p.riser_id == detail.vent_riser_id)
    nodes.append(FanDetailNode(t.terminal_id, vent.x_m, detail.roof_level_m + float(t.height_m or 0),
                               "open_end", t.terminal_id))
    edges.append(FanDetailEdge("common-vent", "join:"+vent.riser_id, t.terminal_id,
                               float(t.diameter_mm or 0), "common_vent"))
    return FanDetailGraph(t.terminal_id, tuple(nodes), tuple(edges))


def build_valve_detail_graph(data: FanDetailsInput, detail: FanValveDetail) -> FanDetailGraph:
    t = data.terminal(detail.terminal_id)
    rid = t.riser_ids[0]
    r = next(r for r in data.risers if r.riser_id == rid)
    return FanDetailGraph(t.terminal_id, (
        FanDetailNode(rid, 0, detail.floor_level_m, "riser_port", rid),
        FanDetailNode(t.terminal_id, 0, detail.connection_level_m, "valve", t.terminal_id),
    ), (FanDetailEdge("valve-riser", rid, t.terminal_id, float(r.diameter_mm or 0), "valve_riser"),))


def _text(x, y, value, height=3.5, anchor="start", attrs="") -> str:
    return (f'<text x="{x:g}" y="{y:g}" font-family="{DRAFTING_FONT_FAMILY}" '
            f'font-size="{STYLE.font_size(height, 1):g}" text-anchor="{anchor}" {attrs}>{escape(value)}</text>')


def _line(x1, y1, x2, y2, width=.25, attrs="") -> str:
    return (f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
            f'stroke="black" stroke-width="{width:g}" {attrs}/>')


def _dimension(x, y1, y2, ref_x, value, key) -> str:
    return ''.join((f'<g data-dimension="{key}" data-value-mm="{value:g}" data-start-y="{y1:g}" data-end-y="{y2:g}">',
                    _line(x, y1-2, x, y2+2), _line(ref_x+2, y1, x+2, y1), _line(ref_x+2, y2, x+2, y2),
                    _line(x-1, y1+1, x+1, y1-1), _line(x-1, y2+1, x+1, y2-1),
                    _text(x-2, (y1+y2)/2, f"{value:g}", anchor="middle",
                          attrs=f'transform="rotate(-90 {x-2:g} {(y1+y2)/2:g})"'), '</g>'))


def _label(key, value, a, b) -> str:
    return render_inline_pipe_label(line_id=key, label=value, start=a, end=b,
                                    font_size=STYLE.font_size(3.5, 1), padding=1.)


def _leader(key, target, title, detail, bounds, *, side=1,
            vertical_offsets_mm=(18., 24., 30., 36.)) -> str:
    return LeaderLayoutEngine(bounds=LeaderBounds(*bounds), units_per_mm=1,
                              vertical_offsets_mm=vertical_offsets_mm).place_and_render(
        LeaderRequest(key, key, target, title, detail, preferred_side=side))


def _sheet_start(title, subtitle) -> list[str]:
    return ['<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297" '
            'data-fan-control-sheet="true" data-production-release="false">',
            '<rect width="420" height="297" fill="white"/>',
            CONTROL_BORDER,
            _text(27, 18, title, 5), _text(27, 27, subtitle, 3.5)]


def _control_footer(page, total, title, scale) -> str:
    if not 1 <= page <= total:
        raise ValueError("Неверная нумерация контрольных фановых листов")
    return ''.join(('<g data-fan-control-footer="true">',
                 _line(20, 276, 415, 276), _line(225, 276, 225, 292), _line(378, 276, 378, 292),
                 _text(27, 283, "ЗАРЯ | Контроль графического узла", 3.5),
                 _text(27, 289, "Не является готовым листом ПД или монтажным чертежом", 2.5),
                 _text(231, 283, title, 3.5), _text(231, 289, f"Геометрия М 1:{scale:g}; надписи в миллиметрах листа", 2.5),
                 _text(384, 286, f"{page} / {total}", 3.5), '</g>'))


def _sheet_end(page, total, title, scale, notes) -> list[str]:
    # Plain paragraphs: no decorative horizontal line above them. Preserve
    # the existing paper coordinates and text height; refuse overflow.
    rows = ['<g data-fan-control-notes="true">']
    size = STYLE.font_size(3.5, 1)
    for i, note in enumerate(notes):
        y = 234+i*7
        if _text_width(note, size) > 381 or y+size*.3 > 271:
            raise ValueError("Примечания не помещаются на контрольном фановом листе")
        rows.append(_text(27, y, note, 3.5))
    rows.extend(('</g>', _control_footer(page, total, title, scale), '</svg>'))
    return rows


def validate_fan_control_sheet(svg: str, *, page: int, total: int, title: str, scale: float) -> None:
    """Paper identity only, never evidence that the ventilation design is ready."""
    root = ET.fromstring(svg)
    if ((root.get("width"), root.get("height"), root.get("viewBox")) !=
            ("420mm", "297mm", "0 0 420 297") or root.get("data-production-release") != "false"
            or root.get("data-fan-control-sheet") != "true"):
        raise ValueError("Требуется непроектный контрольный лист А3")
    expected = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">' + CONTROL_BORDER +
                             _control_footer(page, total, title, scale) + '</svg>')
    for key, element in zip(("data-fan-control-border", "data-fan-control-footer"), expected, strict=True):
        matches = [e for e in root if e.get(key)]
        if len(matches) != 1 or ET.tostring(matches[0]) != ET.tostring(element):
            raise ValueError("Неверная рамка, нумерация или оговорка контрольного фанового листа")


def _roof_svg(data: FanDetailsInput, d: FanRoofDetail, page: int, total: int,
              source_sheet_by_riser: dict[str, int] | None = None, *,
              off_plane_risers: frozenset[str] = frozenset()) -> str:
    t = data.terminal(d.terminal_id)
    assert t.height_m is not None  # guaranteed by the normative audit above
    graph = build_roof_detail_graph(data, d)
    nodes = {n.node_id: n for n in graph.nodes}
    minimum_x = min(n.x_m for n in graph.nodes)
    factor = 1000 / d.scale
    roof_y = 112.

    def xy(n: FanDetailNode) -> tuple[float, float]:
        return 65+(n.x_m-minimum_x)*factor, roof_y+(d.roof_level_m-n.level_m)*factor

    if any(not (35 <= xy(n)[0] <= 240 and 38 <= xy(n)[1] <= 204) for n in graph.nodes):
        raise ValueError("roof detail does not fit A3 at the explicit scale; choose another scale or sheet")
    tip = xy(nodes[t.terminal_id])
    p = _sheet_start("К1. Общая фановая вытяжка", f"Контрольный узел {page:02d} | {len(d.risers)} стояка | Геометрия задана явно")
    p[0] = p[0].replace('data-fan-control-sheet="true"', f'data-fan-control-sheet="true" data-fan-roof-terminal="{escape(t.terminal_id)}"')
    p.extend((_line(35, roof_y, 267, roof_y, .6, 'data-roof-line="true"'),
              _line(35, roof_y+4, 267, roof_y+4),
              _text(36, roof_y-3, f"Кровля {d.roof_level_m:+.2f}"),
              _text(36, 205, "К стоякам К1 здания; нижние порты фрагмента", 3.5)))
    for edge in graph.edges:
        a, b = xy(nodes[edge.start]), xy(nodes[edge.end])
        p.append(_line(*a, *b, .6, f'data-fan-edge="{escape(edge.edge_id)}" data-role="{edge.role}" '
                        f'data-start="{escape(edge.start)}" data-end="{escape(edge.end)}" data-dn="{edge.dn_mm:g}"'))
        if edge.role == "riser_vent":
            p.append(_text(a[0], a[1]+7, nodes[edge.start].source_id, 3.5, "middle"))
            p.append(_text(a[0], a[1]+14, f"DN{edge.dn_mm:g}", 3.5, "middle"))
            if source_sheet_by_riser is not None:
                rid = nodes[edge.start].source_id
                source = source_sheet_by_riser[rid]
                prefix = f"Вне разреза л. {source}" if rid in off_plane_risers else f"С л. {source}"
                p.append(_text(a[0], a[1]+21, f"{prefix}; {nodes[edge.start].level_m:+.2f}", 2.5, "middle",
                               attrs=f'data-fan-detail-port="{escape(rid)}" data-source-sheet="{source}" '
                                     f'data-terminal="{escape(t.terminal_id)}" data-level-m="{nodes[edge.start].level_m:g}"'))
    # Slope is computed ONLY from supplied geometry, not selected by the renderer.
    ordered = sorted(d.risers, key=lambda r: r.x_m)
    for i, (ra, rb) in enumerate(zip(ordered, ordered[1:])):
        aa, bb = xy(nodes["join:"+ra.riser_id]), xy(nodes["join:"+rb.riser_id])
        value = abs(rb.collector_m-ra.collector_m)/(rb.x_m-ra.x_m)
        cx, cy = (aa[0]+bb[0])/2, min(aa[1], bb[1])-6
        sign = 1 if rb.collector_m < ra.collector_m else -1
        p.extend((f'<g data-condensate-slope="{value:g}" data-downhill-riser="{escape(d.condensate_riser_id)}">',
                  _text(cx, cy, f"{value:.3f}".replace('.', ','), anchor="middle"),
                  f'<path d="M{cx+sign*14:g},{cy:g} L{cx+sign*10:g},{cy:g} M{cx+sign*14:g},{cy:g} '
                  f'L{cx+sign*10:g},{cy-2.3:g}" fill="none" stroke="black" stroke-width=".25"/>', '</g>'))
        if i == 0:
            p.append(_label("collector-dn", f"К1 ⌀{t.collector_diameter_mm:g}", aa, bb))
    collector_target = xy(nodes["join:"+d.condensate_riser_id])
    collector_top = min(xy(nodes["join:"+r.riser_id])[1] for r in d.risers)
    collector_bounds = (75., 120., 205., 143.)
    collector_offsets = (18., 24., 30., 36.)
    if collector_top-roof_y < 40:
        # A shallow collector leaves no room for both a two-line leader and
        # slope labels under the slab. Use the reserved lower-right pocket;
        # don't shrink text, hide a slope or move engineering coordinates.
        collector_target = xy(nodes["join:"+ordered[-1].riser_id])
        collector_bounds = (collector_target[0]+34, 177., 405., 200.)
        collector_offsets = (187.-collector_target[1],)
    p.extend((_dimension(tip[0]+16, tip[1], roof_y, tip[0], float(t.height_m)*1000, "vent-above-roof"),
              _leader("common-vent", (tip[0], tip[1]+5), "Общая вытяжная часть", f"DN{t.diameter_mm:g}; открытое устье",
                      (70, 34, 205, 98), side=-1),
              _leader("collector", collector_target, "Сборный трубопровод",
                      f"DN{t.collector_diameter_mm:g}; оси {ordered[0].collector_m:+.2f} / {ordered[-1].collector_m:+.2f}",
                      collector_bounds, vertical_offsets_mm=collector_offsets),
              _text(282, 120, "Проверяемые связи", 3.5),
              _text(282, 131, f"{len(d.risers)} входных порта К1", 3.5),
              _text(282, 142, "Одна общая вытяжка", 3.5),
              _text(282, 153, f"Конденсат к {d.condensate_riser_id}", 3.5),
              _text(282, 164, "К2 не подключается", 3.5),
              _text(282, 175, "Без колпака и дефлектора", 3.5)))
    p.extend(_sheet_end(page, total, "Объединение стояков К1", d.scale, (
        "1. Это отдельный контрольный пример, не изменение кровли 8-квартирного дома.",
        "2. Уклоны показаны по заданным отметкам; это не расчёт сечения вытяжки.",
        "3. Теплоизоляция и УФ-защита подтверждаются во входе; конструкция креплений не разработана.",
        "4. СП 30: 18.18-18.22; ГОСТ Р 21.620-2023: 5.2.2.2, 5.2.2.4 - состав фрагмента.",
        "5. Положение фасонных частей, проходки и номера помещений требуют привязки к АР.",
    )))
    svg = ''.join(p)
    validate_fan_control_sheet(svg, page=page, total=total, title="Объединение стояков К1", scale=d.scale)
    return svg


def render_valve_outline(x: float, y: float, scale: float, *, stroke: float = .35) -> str:
    """Shared inspected manufacturer contour; scale is drawing units / real mm."""
    return (f'<g data-valve-outline="hl900n-reference" data-normative-ugo="false" '
            f'data-outline-source="{HL900N_DRAWING}" transform="translate({x:g} {y:g}) scale({scale:g})">'
            '<path d="M-55,0 V-62 L-73,-68 V-177 Q-73,-192 -58,-192 H58 '
            'Q73,-192 73,-177 V-68 L55,-62 V0 Z" fill="white" stroke="black" '
            f'stroke-width="{stroke/scale:g}"/></g>')


def _valve_svg(data: FanDetailsInput, d: FanValveDetail, page: int, total: int) -> str:
    t = data.terminal(d.terminal_id)
    graph = build_valve_detail_graph(data, d)
    edge = graph.edges[0]
    x, floor_y, factor = 142., 210., 1000/d.scale
    def y(level: float) -> float:
        return floor_y-(level-d.floor_level_m)*factor
    cy, ceiling_y, rim_y = y(d.connection_level_m), y(d.ceiling_level_m), y(d.highest_fixture_rim_m)
    if not (38 <= ceiling_y < cy-.192*factor < cy < rim_y < floor_y):
        raise ValueError("valve detail does not fit A3 at the explicit scale")
    p = _sheet_start("К1. Окончание стояка воздушным клапаном", "Контрольный узел | Положение по отметкам, не автоматическая замена вытяжки")
    p.extend((_line(43, ceiling_y, 270, ceiling_y, .6), _line(43, floor_y, 270, floor_y, .6),
              _text(45, ceiling_y-3, f"Перекрытие {d.ceiling_level_m:+.2f}"),
              _text(45, floor_y+7, f"Пол верхнего этажа {d.floor_level_m:+.2f}"),
              _line(43, rim_y, 252, rim_y, .25, 'stroke-dasharray="3 2" data-highest-fixture-rim="true"'),
              _text(45, rim_y-3, f"Борт прибора {d.highest_fixture_rim_m:+.2f}"),
              _line(x, floor_y, x, cy, .6, f'data-fan-edge="valve-riser" data-end="{escape(t.terminal_id)}"'),
              _label("valve-riser-dn", f"К1 ⌀{edge.dn_mm:g}", (x, rim_y+5), (x, floor_y-2))))
    # Simplified exterior envelope of the inspected manufacturer's cross-section:
    # 146 x 192 mm, lower 110 mm neck of length 62 mm. NOT a new GOST symbol.
    s = factor / 1000
    p.extend((render_valve_outline(x, cy, s),
              _dimension(245, cy, rim_y, x+5, (d.connection_level_m-d.highest_fixture_rim_m)*1000, "valve-above-rim"),
              _leader("valve", (x+3.65, cy-5), "Воздушный клапан", "Контур-пример HL900N; не подбор",
                      (170, ceiling_y+15, 405, cy-8)),
              _text(280, 169, "Воздух входит в стояк.", 3.5),
              _text(280, 179, "Клапан не удаляет газы.", 3.5),
              _text(280, 189, "Вывода через кровлю нет.", 3.5),
              _text(280, 199, "Доступ для обслуживания", 3.5),
              _text(280, 207, "обязателен по изделию.", 3.5)))
    p.extend(_sheet_end(page, total, "Воздушный клапан К1", d.scale, (
        "1. Контур показан по HL900N_a.pdf (Hutterer & Lechner); это не отдельное УГО ГОСТ.",
        "2. Клапан не выбран по расходу; поле подтверждения подбора задано только для теста движка.",
        f"3. {(d.connection_level_m-d.highest_fixture_rim_m)*1000:g} мм - разница заданных отметок, не универсальный нормативный отступ.",
        "4. Вентиляция наружной сети проверяется отдельно; нельзя заменить все вытяжки клапанами автоматически.",
        "5. СП 30: 18.22-18.25, 19.8-19.9; до включения в проект нужны модель, паспорт и привязка к АР.",
    )))
    svg = ''.join(p)
    validate_fan_control_sheet(svg, page=page, total=total, title="Воздушный клапан К1", scale=d.scale)
    return svg


def build_fan_detail_svgs(data: FanDetailsInput) -> tuple[str, ...]:
    data.validate()
    total = len(data.roofs)+len(data.valves)
    svgs = tuple([_roof_svg(data, d, i+1, total) for i, d in enumerate(data.roofs)] +
                 [_valve_svg(data, d, len(data.roofs)+i+1, total) for i, d in enumerate(data.valves)])
    for svg in svgs:
        errors = audit_fan_detail_svg(svg)
        if errors:
            raise ValueError("fan drawing collision: " + "; ".join(errors))
    return svgs


def _segment_hits_box(a, b, box) -> bool:
    """Slab intersection, including containment and endpoint contact."""
    lo, hi = 0., 1.
    for origin, delta, minimum, maximum in (
        (a[0], b[0]-a[0], box[0], box[2]), (a[1], b[1]-a[1], box[1], box[3]),
    ):
        if abs(delta) < 1e-9:
            if not minimum <= origin <= maximum:
                return False
        else:
            t1, t2 = sorted(((minimum-origin)/delta, (maximum-origin)/delta))
            lo, hi = max(lo, t1), min(hi, t2)
            if hi < lo:
                return False
    return True


def audit_fan_detail_svg(svg: str) -> tuple[str, ...]:
    """Protect readable leader text from pipe and dimension line overlap."""
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    obstacles = [r for r in root.iter(ns+"line") if r.get("data-fan-edge")]
    for dimension in (r for r in root.iter() if r.get("data-dimension")):
        obstacles.extend(dimension.iter(ns+"line"))
    slope_boxes = []
    for group in (r for r in root.iter() if r.get("data-condensate-slope")):
        for label in group.iter(ns+"text"):
            x, y, size = (float(label.get(key, "nan")) for key in ("x", "y", "font-size"))
            width = _text_width("".join(label.itertext()), size)
            anchor = label.get("text-anchor", "start")
            left = x-width/2 if anchor == "middle" else x-width if anchor == "end" else x
            slope_boxes.append((left, y-size, left+width, y+size*.22))
    errors = []
    for leader in (r for r in root.iter() if r.get("data-leader-id")):
        box = tuple(float(leader.get(f"data-text-box-{key}", "nan")) for key in ("x1", "y1", "x2", "y2"))
        if not all(isfinite(v) for v in box):
            errors.append("leader missing text bounds")
            continue
        if any(not (box[2] <= s[0] or s[2] <= box[0] or box[3] <= s[1] or s[3] <= box[1]) for s in slope_boxes):
            errors.append(f"{leader.get('data-leader-id')}: text overlaps slope label")
        for line in obstacles:
            a = (float(line.get("x1", "nan")), float(line.get("y1", "nan")))
            b = (float(line.get("x2", "nan")), float(line.get("y2", "nan")))
            if not all(isfinite(v) for v in (*a, *b)):
                errors.append("pipe/dimension missing coordinates")
                continue
            if _segment_hits_box(a, b, box):
                errors.append(f"{leader.get('data-leader-id')}: text overlaps pipe/dimension")
    return tuple(errors)


def generate_fan_details_pdf(data: FanDetailsInput, output_path: str) -> str:
    import cairosvg  # type: ignore[import-untyped]
    from pypdf import PdfReader, PdfWriter

    svgs = build_fan_detail_svgs(data)  # validate before touching output
    ensure_drafting_font_registered()
    writer = PdfWriter()
    for index, (svg, detail) in enumerate(zip(svgs, (*data.roofs, *data.valves), strict=True), 1):
        validate_fan_control_sheet(svg, page=index, total=len(svgs), scale=detail.scale,
                                   title="Объединение стояков К1" if index <= len(data.roofs) else "Воздушный клапан К1")
        result = cairosvg.svg2pdf(bytestring=svg.encode())
        writer.add_page(PdfReader(BytesIO(result)).pages[0])
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        writer.write(out)
    return str(path)
