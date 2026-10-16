"""IOS2 meter assembly sheet, GOST R 21.619-2023 §5.2.2.6 / Appendix Г.

Physical millimetres throughout. This is a schematic, not a fabrication
drawing: no inferred installation lengths, passport values or pipe DNs.
The hydraulic result is consumed, never recalculated or modified here.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import ceil, isfinite

from app.pz import ugo
from app.pz.drafting_font import DRAFTING_FONT_FAMILY
from app.pz.leader_layout import (
    LeaderBounds, LeaderLayoutEngine, LeaderPlacement, LeaderRequest, _text_width,
)
from app.pz.meter_validation import check_meter_average
from app.pz.rules import decide_fire_network
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_rules import control_cock_dn, remote_readout_required, special_layout_pending
from app.pz.metering_pipes import PIPE_ROLES
from app.pz.drawing_numbers import water_elevation_text


@dataclass(frozen=True)
class MeteringDrawingState:
    inputs_count: int
    meter: object | None
    bypass: bool
    electric_bypass: bool
    fire_branch: bool
    combined: bool
    missing: tuple[str, ...]
    node_key: str = ""
    inlet_metering_mode: str = "per_inlet"
    common_topology: str = "merge_before"

    @property
    def common_inlets(self):
        return self.node_key != "hot" and self.inputs_count > 1 and self.inlet_metering_mode == "common"

    @property
    def assemblies_count(self):
        return 1 if self.common_inlets else self.inputs_count

    @property
    def switching_bridge(self):
        return self.common_inlets and self.inputs_count == 2 and self.common_topology == "gost_g1"

    @property
    def core_bypass(self):
        return self.bypass and not self.switching_bridge


def drawing_state(project) -> MeteringDrawingState:
    if getattr(project, "metering_node", "") == "hot":
        from app.pz.metering_hot_node import hot_drawing_state
        return hot_drawing_state(project)
    detail = project.metering_detail
    errors = detail.validate()
    if errors:
        raise ValueError("; ".join(errors))
    inlets = getattr(project.v1_network, "inlets", []) or []
    count = len(inlets) or max(int(project.source.inputs_count or 1), 1)
    rows = project.meters.rows
    # A common inlet meter measures total demand; a DHW/apartment meter must
    # never accidentally replace it just because it occurs first in the list.
    candidates = [r for r in rows if "ввод" in r.label.lower()]
    if not candidates:
        candidates = [r for r in rows if "хвс" in r.label.lower()
                      and "кварт" not in r.label.lower()]
    row = candidates[0] if len(candidates) == 1 else None
    missing = []
    if project.meters.selection_error:
        row = None
        missing.append("Подбор водомера не подтверждён")
    if row is not None:
        average_ok = check_meter_average(row, project.flows, project.source)[0]
        if average_ok is False:
            row = None
            missing.append("Сохранённый водомер не проходит текущий Qсред")
        elif average_ok is None:
            missing.append("Нет данных для текущей проверки Qсред")
    if row is None or row.dn <= 0:
        row = None
        missing.append("Нет однозначного вводного водомера")
    if not detail.inlet_dn:
        missing.append("DN трубопровода ввода не задан")
    if row and detail.inlet_dn and detail.inlet_dn < row.dn:
        missing.append("DN ввода меньше DN счётчика: проверить решение")
    if not detail.room_number:
        missing.append("Не задан номер помещения по экспликации")
    if not detail.meter_model:
        missing.append("Модель и паспорт водомера не заданы")
    if row and (row.q_min_passport_m3h is None or not row.passport_reference):
        missing.append("Паспортный Qmin не подтверждён")
    if row and not row.ok_a:
        missing.append("Потери на водомере превышают допустимые")
    if row and row.ok_v is False:
        missing.append("Проверка малых расходов не пройдена")
    # Hydraulic requirement remains untouched. Common metering adds a DESIGN
    # service bypass; §12.12's two-meter exemption does not apply to one meter.
    common = count > 1 and detail.inlet_metering_mode == "common"
    if common and detail.common_topology == 'gost_g1':
        if count != 2:
            missing.append('Компоновка Г.1 поддерживает ровно два ввода; нужна отдельная топология')
        missing.append('Переключающая обвязка Г.1: монтажные длины, присоединения и потери требуют проверки')
    bypass = bool(project.meters.has_bypass or common)
    electric = bool(bypass and row and row.need_bypass)
    if project.meters.single_input_bypass_note and not bypass:
        missing.append("Расчётное примечание об обводной не отражено в решении")
    if bypass and not detail.bypass_dn:
        missing.append("DN обводной линии не задан")
    if row and row.need_bypass and not bypass:
        missing.append("Проверка счётчика требует обводную линию")
    if count != project.meters.inputs_count:
        missing.append("Число вводов расходится с расчётом водомеров")
    decision = decide_fire_network(project.fire, project.materials, project.normative)
    topology = decision.topology if decision else "separate"
    if project.fire.required and topology == "pre_meter_branch" and not detail.fire_branch_dn:
        missing.append("DN ответвления В2 не задан")
    if detail.catalogue_items or detail.fitting_items or detail.meter_products or detail.meter_selection_mode == "catalogue_proposal" or detail.pipe_sections or detail.support_pipe_section or detail.connection_items or detail.connection_thread_items or detail.reducer_items or detail.inline_joint_items or detail.service_items or detail.service_selection_mode == "catalogue_proposal" or detail.flexible_connections:
        products = resolve_metering_products(project, row, bypass=bypass, electric_bypass=electric)
        if products.selected("meter") and "Модель и паспорт водомера не заданы" in missing:
            missing.remove("Модель и паспорт водомера не заданы")
        if products.selected("meter") and "Паспортный Qmin не подтверждён" in missing:
            missing[missing.index("Паспортный Qmin не подтверждён")] = (
                "Проверка малых расходов по паспорту не завершена")
        if products.errors:
            missing.append("Каталожная комплектация требует исправления: см. ведомость изделий и труб")
    return MeteringDrawingState(
        count, row, bypass, electric,
        bool(project.fire.required and topology == "pre_meter_branch"),
        bool(project.fire.required and topology == "combined"), tuple(missing),
        inlet_metering_mode=detail.inlet_metering_mode,
        common_topology=detail.common_topology,
    )


def _n(value, digits=2):
    return f"{value:.{digits}f}".replace(".", ",")


def _dn(value):
    return f"DN{value}" if value else "DN — уточнить"


def _pipe_size(detail, role, nominal_dn):
    section = detail.pipe_sections.get(role)
    if section is None:
        return _dn(nominal_dn)
    if section.outer_diameter_mm is None:
        return "Размер уточнить"
    value = "Ø" + f"{section.outer_diameter_mm:g}".replace(".", ",")
    if section.wall_thickness_mm is not None:
        value += "×" + f"{section.wall_thickness_mm:g}".replace(".", ",")
    return value


def _text(x, y, value, h=3.5, anchor="start"):
    value = str(value)
    if "Ø" in value or "⌀" in value:
        # OpenGOST lacks these glyphs. Use the vector-diameter strategy of
        # wastewater labels, without their pipe mask or approximate widths.
        parts = value.replace("⌀", "Ø").split("Ø")
        width = _label_width(value,h)
        cursor = x - (width/2 if anchor == "middle" else width if anchor == "end" else 0)
        font = h/.823
        g = [f'<g aria-label="{escape(value)}">']
        for i, part in enumerate(parts):
            if part:
                g.append(_text(cursor,y,part,h))
                cursor += _text_width(part,font)
            if i < len(parts)-1:
                cx, cy = cursor+font*.41, y-font*.42
                r, slash = font*.29, font*.39
                g += ['<g data-vector-diameter-sign="true">',
                      f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="none" '
                      f'stroke="black" stroke-width="{font*.085:g}"/>',
                      _line(cx-slash,cy+slash,cx+slash,cy-slash,font*.085), '</g>']
                cursor += font*.98
        return ''.join(g) + '</g>'
    return (f'<text x="{x:g}" y="{y:g}" font-family="{DRAFTING_FONT_FAMILY}" '
            f'font-size="{h / .823:.4f}" data-text-height-mm="{h:g}" '
            f'text-anchor="{anchor}">{escape(value)}</text>')


def _label_width(value,h):
    parts = str(value).replace("⌀", "Ø").split("Ø")
    font = h/.823
    return sum(_text_width(part,font) for part in parts) + (len(parts)-1)*font*.98


def _lines(value, width, h=3.5):
    """Metric wrapping, including long document numbers / model names."""
    result, current = [], ""
    for word in str(value).split():
        candidate = f"{current} {word}".strip()
        if _label_width(candidate,h) <= width:
            current = candidate
            continue
        if current:
            result.append(current)
        current = ""
        for char in word:
            if current and _label_width(current+char,h) > width:
                result.append(current)
                current = ""
            current += char
    if current:
        result.append(current)
    return result or [""]


def _line(x1, y1, x2, y2, w=.6, attrs=""):
    return (f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
            f'stroke="black" stroke-width="{w:g}" {attrs}/>')


def _path(d, w=.6, attrs=""):
    return f'<path d="{d}" fill="none" stroke="black" stroke-width="{w:g}" {attrs}/>'


def _arrow(x, y):
    return f'<path d="M{x:g},{y:g} l-3,-1.2 v2.4 Z" fill="black"/>'


def _gate(x, y, *, electric=False, size=2.8):
    # A general shutoff as in Appendix Г, not a gate valve for every product.
    from app.pz.metering_ugo import shutoff
    return shutoff(x,y,size=size,electric=electric)


def _leader(ident, target, knee, outer, title, detail):
    """Fixed annotation lanes, same tested leader renderer as other sheets."""
    x = min(knee[0], outer) + 1
    y = knee[1]
    font = 3.5 / .823
    width = max(_text_width(title, font), _text_width(detail, font))
    if width + 2 > abs(outer - knee[0]):
        raise ValueError(f"Недостаточно места для выноски {ident}")
    placement = LeaderPlacement(
        knee, (outer, y), (x, y-5.1, x+width, y+5.1),
        (x, y-1.2), (x, y+font+0.8), font,
    )
    engine = LeaderLayoutEngine(bounds=LeaderBounds(20, 5, 415, 292), units_per_mm=1)
    return engine.render(LeaderRequest(ident, ident, target, title, detail), placement)


def _assembly(project, state):
    from app.pz.metering_orientation import nonhorizontal_layout_pending
    if nonhorizontal_layout_pending(project.metering_detail):
        return (_text(28,45,"Вертикальный/смешанный ВУ: монтажная ориентация задана.",3.5)
                + _text(28,53,"Размерная компоновка требует дополнения; горизонтальный шаблон не применён.",3.5))
    if project.metering_detail.assembly_orientation.startswith('vertical'):
        from app.pz.metering_layout import build_metering_layout
        from app.pz.metering_vertical_drawing import vertical_contents
        layout = build_metering_layout(project,state)
        if layout.issues:
            lines = [line for issue in layout.issues for line in _lines(issue,245,3.5)]
            return ''.join(_text(28,45+i*5.5,line,3.5) for i,line in enumerate(lines[:15]))
        return vertical_contents(project,state,layout,include_notes=False,include_heading=False)
    if project.metering_detail.flexible_connections or project.metering_detail.maintenance_layout == 'serviceable':
        return (_text(28,45,"Состав этого исполнения показан на листе размерной компоновки.",3.5)
                + _text(28,53,"Все изделия, сервисные отборы и связи — из единой модели ВУ.",3.5))
    from app.pz.metering_ugo import gauge, shutoff
    row = state.meter
    d = project.metering_detail
    y = 83
    g = [_text(28, 37, "1. Состав водомерного узла", 5),
         _line(38, y, 274, y), _arrow(272, y)]
    for x, mark in ((58, "1.1"), (91, "1.2"), (219, "1.2")):
        g += [_gate(x, y), _text(x, y-6, mark, 2.5, "middle")]
    g += [ugo.filt(119, y, hd=4, vd=4, ext=0, w=.35),
          ugo.meter(150, y, rw=9, rh=6, ext=0, w=.35),
          _text(119, y+9, "2", 2.5, "middle"),
          _text(156, y+9, "7", 2.5, "middle"),
          ugo.check_h(247, y, tri=3, w=.35), _text(247, y-6, "5", 2.5, "middle")]
    g += [_leader("filter", (119, 79), (109, 57), 76, "Фильтр", _dn(row.dn if row else None)),
          _leader("meter", (150, 80), (163, 50), 215, "Водосчётчик", _dn(row.dn if row else None))]
    # Instrument branch. Control taps below are separate, capped connections
    # under SP30 §12.9, not an always-open drain drawn from the reference.
    g += [_line(186, y, 186, 65, .35),
          f'<g transform="rotate(90,186,72)">{_gate(186,72,size=1.6)}</g>',
          gauge(186,61,radius=4), _text(193, 62, "PI · 3.1", 2.5),
          _text(193, 73, "3.2", 2.5)]
    for index, x in enumerate((186, 239), 1):
        g += [f'<g data-control-cock="{index}" data-dn="{control_cock_dn(row) or ""}" '
              f'data-connection-x="{x}" data-capped="true">',
              _line(x,y,x,99,.35),
              f'<g transform="rotate(90,{x},93)">{shutoff(x,93,size=3,ball=True)}</g>',
              _line(x-2.2,99,x+2.2,99,.6), _text(x+4,93,"4.1",2.5),
              _text(x+4,100,"4.2",2.5), '</g>']
    g += [_text(214,104,"≤500 мм",2.5),
          _line(219,89,219,102,.25), _line(239,100,239,102,.25),
          _line(219,101,239,101,.25),
          _line(217.8,102.2,220.2,99.8,.25), _line(237.8,102.2,240.2,99.8,.25)]
    g += [_text(39, 73, _pipe_size(d,"inlet",d.inlet_dn), 3.5),
          _text(254, 73, _pipe_size(d,"outlet",d.inlet_dn), 3.5)]
    # Transitions are shown only when both nominal diameters are known.
    if row and d.inlet_dn and d.inlet_dn != row.dn:
        entry_expands = row.dn > d.inlet_dn
        for a, b, flip in ((79, 85, entry_expands), (225, 231, not entry_expands)):
            left, right = ((0, 2) if flip else (2, 0))
            g.append(f'<path data-meter-transition="true" d="M{a},{y-left} '
                     f'L{b},{y-right} V{y+right} L{a},{y+left} Z" '
                     'fill="white" stroke="black" stroke-width=".35"/>')
        for role, mark, x, level in (("reducer_in", "П1", 82, 96), ("reducer_out", "П2", 228, 76)):
            g.append(f'<g data-reducer-role="{role}">' + _text(x,level,mark,3.5,"middle") + '</g>')
    if state.bypass:
        g += [_path("M76 83 V113 H232 V83", attrs='data-bypass="true"'),
              _gate(143, 113, electric=state.electric_bypass),
              _text(143, 122, "6", 2.5, "middle"),
              _text(85, 109, _pipe_size(d,"bypass",d.bypass_dn), 3.5),
              _leader("bypass", (193,113), (206,129), 274, "Обводная линия",
                      "Электропривод" if state.electric_bypass else "Ручная арматура")]
    else:
        g.append(_text(38, 119, "Обводная линия не предусмотрена расчётным решением.", 3.5))
    if remote_readout_required(project):
        g += [_path("M150 86 V101 H164", .25, 'stroke-dasharray="2 1" data-askue="true"'),
              _text(153, 106, "Выход данных*", 2.5)]
    # These are traceable pipe-zone tags, not new equipment positions or
    # proposed dimensions of transition fittings. No hydraulic mutation.
    for role, x, level in (("inlet",43,83), ("before_meter",104,83),
                           ("after_meter",205,83), ("outlet",262,83), ("bypass",100,113)):
        if role in d.pipe_sections and (role != "bypass" or state.bypass):
            g.append(f'<g data-pipe-section="{role}">' +
                     _text(x,level+7,PIPE_ROLES[role][0],3.5,"middle") + '</g>')
    from app.pz.metering_connections import CONNECTION_ROLES
    # Cards locate ports, not fictitious dimensioned fittings. The symbols
    # already on this principle drawing stay unchanged.
    for role, x, level in (("inlet_valve_in",52,98), ("filter_in",111,98),
                          ("meter_valve_out",226,70), ("check_valve_out",262,98),
                          ("bypass_valve_in",134,122), ("bypass_valve_out",153,122)):
        if role in d.connection_items and (not role.startswith("bypass") or state.bypass):
            g.append(f'<g data-connection-port="{role}">' +
                     _text(x,level,CONNECTION_ROLES[role][0],3.5,"middle") + '</g>')
    # The generic nipple required between selected F/F ports belongs to the
    # same graph/SO as the new dimensional view, even on the principle sheet.
    from app.pz.metering_spec import build_metering_spec_section
    centers = {"inlet_valve":58,"reducer_in":82,"valve_before":91,"filter":119,
               "meter":150,"valve_after":219,"reducer_out":228,"check_valve":247,
               "outlet_thread":255,"outlet_connector":263,"bypass_valve":143}
    for item in build_metering_spec_section(project).rows:
        for ident in item.component_ids:
            if not ident.startswith("joint_"):
                continue
            ends=ident[6:].split("__")
            if len(ends)==2 and all(n in centers for n in ends):
                x=sum(centers[n] for n in ends)/2
                g += [f'<g data-inline-nipple="{ident}">',
                      _line(x-1.5,y-2,x-1.5,y+2,.35),
                      _line(x+1.5,y-2,x+1.5,y+2,.35),
                      _text(x,y-5,item.diagram_pos,3.5,"middle"),'</g>']
    return "".join(g)


def _inlets(project, state, first):
    if project.metering_detail.assembly_orientation.startswith('vertical'):
        return ''  # Dedicated supply page avoids overlap with the tall core.
    if state.common_inlets and not special_layout_pending(project):
        from app.pz.metering_supply import common_inlet_contents
        return common_inlet_contents(project, state)
    d = project.metering_detail
    room = f"Помещение № {d.room_number}" if d.room_number else "Помещение ВУ: № уточнить"
    if d.room_name:
        room += " · " + d.room_name
    g = [_text(28, 149, "2. Включение узлов во вводы", 5)]
    if special_layout_pending(project):
        # Do not present the ordinary wall-and-basement template as an
        # engineered seismic/permafrost installation. A written basis alone
        # doesn't supply the joints, movements or installation geometry.
        g.append('<g data-special-layout="unresolved">')
        text = ("Специальная компоновка требует отдельной привязки. Обычная схема ввода не применяется. "
                "Условия размещения, гибкие соединения, проходки и защита от замерзания — "
                "по применимым требованиям на листах «Условия компоновки».")
        for i, line in enumerate(_lines(text,240,3.5)):
            g.append(_text(28,164+i*6,line,3.5))
        g.append('</g>')
        return ''.join(g)
    # Wall is drawn first; sleeve masks only the actual penetrations.
    g += ['<rect x="65" y="158" width="6" height="64" fill="url(#wall)" '
          'stroke="black" stroke-width=".35"/>',
          _path("M71 158 H280 V222 H71", .25)]
    for i, label in enumerate(_lines(room, 200, 2.5)[:2]):
        g.append(_text(74, 156+i*4, label, 2.5))
    for local, number in enumerate(range(first, min(first+2, state.inputs_count+1))):
        y = 179 + local * 29
        g += [f'<g data-inlet="{number}">',
              f'<rect x="63" y="{y-2}" width="10" height="4" fill="white"/>',
              _line(63,y-2,73,y-2,.25), _line(63,y+2,73,y+2,.25),
              _line(31,y,273,y, attrs='data-wall-crossing="true"'), _arrow(271,y),
              _text(31,y-4, f"Ввод {number}", 3.5),
              _text(31,y+6,_dn(d.inlet_dn),2.5)]
        if d.inlet_elevation_m is not None:
            # Axis elevation only when explicitly supplied, not Hgar/header.
            g.append(_text(77,y+7,"Ось: " + water_elevation_text(d.inlet_elevation_m),2.5))
        if d.maintenance_layout == 'serviceable':
            # Overview is a block reference, not the obsolete fixed internals.
            g += [f'<rect data-vu-service-reference="true" x="117" y="{y-5}" width="114" height="10" fill="white" stroke="black" stroke-width=".35"/>',
                  _text(174,y+1,f"ВУ-{number} · состав на размерном листе",2.5,'middle'),
                  _text(239,y+6,"К сети В1+В2" if state.combined else "К сети В1",2.5)]
        else:
            for x in (82, 130, 208):
                g.append(_gate(x,y,size=2))
            g += [ugo.filt(149,y,hd=3,vd=3,w=.35,ext=0),
                  ugo.meter(172,y,rw=7,rh=5,w=.35,ext=0),
                  ugo.check_h(233,y,tri=2.5,w=.35),
                  _text(168,y-6,f"ВУ-{number}",3.5),
                  _text(239,y+6,"К сети В1+В2" if state.combined else "К сети В1",2.5)]
        if state.bypass and d.maintenance_layout != 'serviceable':
            g += [_path(f"M117 {y} V{y+9} H220 V{y}",.45),
                  _gate(172,y+9,electric=state.electric_bypass,size=1.8)]
        if state.fire_branch:
            g += [_path(f"M102 {y} V{y-10} H154",.45, 'data-pre-meter-fire="true"'),
                  _gate(123,y-10,electric=project.fire.branch_electric_valves,size=1.8),
                  _arrow(154,y-10), _text(157,y-15,"К В2 · " + _dn(d.fire_branch_dn),2.5)]
            if "fire_branch" in d.pipe_sections:
                g.append('<g data-pipe-section="fire_branch">' + _text(142,y-4,"У6",3.5) + '</g>')
        g.append('</g>')
    return "".join(g)


def _panel_rows(project, state):
    """Current meter evidence shared by overview and dimensional views."""
    r, d = state.meter, project.metering_detail
    selected_model, check = None, None
    if d.catalogue_items or d.meter_products or d.meter_selection_mode == "catalogue_proposal":
        selected_model = resolve_metering_products(
            project, r, bypass=state.bypass, electric_bypass=state.electric_bypass,
        ).selected("meter")
        if r:
            from app.pz.meter_products import evaluate_meter_product
            check = evaluate_meter_product(project,r)
    from app.pz.metering_orientation import check_product_orientation
    orientation = check_product_orientation(selected_model,d.meter_mounting) if selected_model else None
    minimum_ok = check.minimum_ok if check else r.ok_v if r else None
    def value(v, *, positive=False):
        return _n(v,3) if v is not None and isfinite(v) and (not positive or v > 0) else "не задан"
    rows = [
        ("Счётчик", (selected_model.name if selected_model else d.meter_model or "Модель уточнить")
         if r else "Подбор отсутствует"),
        ("Тип / диаметр", f"{r.type_label or 'Тип уточнить'} / {_dn(r.dn)}" if r else "Подбор отсутствует"),
        ("Qmax, м³/ч · расчётный типоразмер", value(r.qmax if r else None,positive=True)),
        ("Qmin, м³/ч · расчётный типоразмер", value(r.q_meter_min if r else None,positive=True)),
        (f"Qmin, м³/ч · модель, класс {orientation.metrological_class}"
         if orientation and orientation.metrological_class else "Qmin, м³/ч · паспорт для ориентации",
         value(orientation.qmin_m3h if orientation else
               (None if check.errors else check.evidence.q_min_passport_m3h) if check else
               r.q_min_passport_m3h if r else None, positive=True)),
        ("Потери расчётного типоразмера, м", value(r.h_a if r else None)),
        ("Проверка малых расходов", ("пройдена" if minimum_ok else "не пройдена")
         if minimum_ok is not None else "требует подтверждения"),
        ("Учёт и диспетчеризация", selected_model.remote_interface + "*"
         if selected_model and selected_model.remote_interface else
         "Выход данных обязателен*" if remote_readout_required(project) else "По заданию проекта"),
    ]
    return rows


def _panel(project, state):
    from app.pz.metering_table_grid import parameter_table
    r, d = state.meter, project.metering_detail
    rows = _panel_rows(project, state)
    table, y = parameter_table(rows)
    g = [_text(292,37,"Данные водомера",5), table,
         '<g data-vu-panel-legend="text">', _text(292,y+7,"Позиции на узле",3.5)]
    y += 14
    first_valve = "кран общего ВУ" if state.common_inlets else "кран ввода"
    components = [f"1.1 — {first_valve}; 1.2 — краны счётчика", "2 — фильтр",
                  "3.1 — манометр; 3.2 — отключающий кран",
                  "4.1 — контрольный шаровой кран, " + _dn(control_cock_dn(r)) + ", 2 шт.",
                  "4.2 — заглушки контрольных кранов, 2 шт.",
                  "5 — обратный клапан"]
    if state.switching_bridge:
        components[0] = "1.2 — краны измерительной вставки"
    if state.core_bypass:
        components.append("6 — обводная: " + ("электропривод" if state.electric_bypass else "ручное управление"))
    components.append("7 — водосчётчик")
    if d.maintenance_layout == 'serviceable':
        components += ["1.3 — отсечка от сети здания",
                       "4.3 / 4.4 — сервисные краны / заглушки"]
    from app.pz.metering_orientation import horizontal_filter_offset
    if horizontal_filter_offset(d):
        components.append("О1, О2 — повороты у горизонтального фильтра")
    for role, mark in (('inlet','Г1'),('before_meter','Г2')):
        if role in d.flexible_connections:
            components.append(mark + ' — гибкая вставка ' + ('на вводе' if role=='inlet' else 'перед прямым участком счётчика'))
    if state.fire_branch and project.fire.branch_electric_valves:
        components.append("В2: задвижка с электроприводом")
    for content in components:
        for line in _lines(content,115,2.5):
            g.append(_text(292,y,line,2.5))
            y += 5
    g.append('</g>')
    if y > 229:
        raise ValueError("Параметры водомера не помещаются на лист: сократите обозначение модели")
    return "".join(g)


def _frame(project, page, total):
    from app.pz.graphic_document_frame import drawing_frame_svg

    return drawing_frame_svg(
        project.document, width_mm=420, height_mm=297,
        title="Узлы учёта воды. Вводы", system_label="",
        sheet_no=page, sheet_total=total,
    )


def build_metering_detail_pages(project) -> list[str]:
    state = drawing_state(project)
    from app.pz.metering_principle_drawing import applicable, common_principle_contents, common_data_contents
    common_principle = applicable(project,state)
    schematic_count = 1 if state.common_inlets else ceil(state.inputs_count / 2)
    # Product dimensions belong on a separate, readable selection sheet; they
    # must not turn this schematic into a fabricated dimensioned assembly.
    from app.pz.metering_catalogue_sheet import catalogue_contents
    from app.pz.metering_rules_sheet import rule_contents
    from app.pz.metering_pipe_sheet import pipe_contents
    from app.pz.metering_connection_sheet import connection_contents
    from app.pz.metering_chain import chain_contents
    from app.pz.metering_reducers import reducer_contents
    catalogue = catalogue_contents(project, state) if (project.metering_detail.catalogue_items
        or project.metering_detail.service_items
        or project.metering_detail.service_selection_mode == "catalogue_proposal") else []
    if project.metering_detail.meter_selection_mode == "catalogue_proposal" or project.metering_detail.meter_products:
        from app.pz.meter_product_sheet import product_contents
        catalogue += product_contents(project)
    pipes = pipe_contents(project, state) if project.metering_detail.pipe_sections else []
    connections = connection_contents(project, state) if project.metering_detail.connection_items else []
    reducers = reducer_contents(project, state) if project.metering_detail.reducer_items else []
    chain = chain_contents(project, state) if project.metering_detail.catalogue_items else []
    conditions = rule_contents(project, state)
    from app.pz.metering_modes_drawing import mode_contents
    modes = mode_contents(project, state)
    if common_principle:
        conditions.insert(0,common_data_contents(project,state))
    if state.common_inlets and not state.switching_bridge and project.metering_detail.assembly_orientation.startswith('vertical') and not special_layout_pending(project):
        from app.pz.metering_supply import common_inlet_contents
        conditions.insert(0, '<g transform="translate(0,-105)">' + common_inlet_contents(project,state) + '</g>')
    from app.pz.metering_maintenance import maintenance_contents
    conditions += maintenance_contents(project, state)
    from app.pz.metering_mounting import mounting_contents
    mounting = mounting_contents(project, state) if (project.metering_detail.mounting.enabled
        or project.metering_detail.assembly_orientation.startswith('vertical')
        or project.metering_detail.maintenance_layout == 'serviceable'
        or project.metering_detail.flexible_connections) else []
    from app.pz.metering_hot_node import hot_detail_contents
    hot_pages = hot_detail_contents(project)
    # Put the operating key directly after the referenced scheme, not hidden
    # behind catalogue appendices. Existing calculations/order within appendices stay unchanged.
    has_catalogue = bool(catalogue)
    catalogue = modes + catalogue
    total = schematic_count + len(catalogue) + len(pipes) + len(connections) + len(reducers) + len(chain) + len(conditions) + len(mounting) + len(hot_pages)
    notes = ["Состав и оформление: ГОСТ Р 21.619-2023, п. 5.2.2.6, приложение Г.",
             "Схема без масштаба. Монтажные длины и прямые участки — по паспорту счётчика.",
             "ВУ на вводах однотипные: состав каждого узла см. на фрагменте 1.",
             "Проход через стену — в гильзе; герметизацию назначить по КР и геологии."]
    if project.metering_detail.assembly_orientation.startswith('vertical'):
        notes[1] = 'Масштаб указан для УГО с известной длиной корпуса; он не задаёт монтажные посадки и раскрой.'
        notes[2] = 'ВУ на вводах однотипные; показан состав одного узла. Количество — в спецификации.'
        notes[3] = 'Проходки вводов и привязку вертикального узла к помещению разработать по КР и геологии.'
    if state.common_inlets:
        notes[2] = 'Один общий ВУ; вводы объединяются до учёта. Режимы и границу учёта согласовать по ТУ.'
    if state.switching_bridge:
        notes[1] = 'Общая схема соединений без масштаба; ориентация вставки и размеры изделий — на отдельных листах.'
        notes[2] = 'Один общий счётчик на перемычке двух магистралей по рисунку Г.1; режимы согласовать по ТУ.'
    notes.append("Условия исполнения и незакрытые проверки — на листах «Условия компоновки».")
    if project.metering_detail.enhancements:
        notes[-1] = "Показан базовый ВУ. Дополнительные опции к подбору — на листах «Условия компоновки»."
    if remote_readout_required(project):
        selected_meter = resolve_metering_products(project, state.meter, bypass=state.bypass,
            electric_bypass=state.electric_bypass).selected("meter")
        notes.append("* Выход подтверждён паспортом исполнения; регистратор и линию связи согласовать."
                     if selected_meter and selected_meter.remote_readout else
                     "* Выход данных требуется; исполнение и интерфейс подтвердить паспортом.")
    if state.fire_branch:
        notes.append("Ответвления В2 до узлов учёта — по принятой в проекте схеме.")
    if has_catalogue:
        notes.append("Каталожные изделия предварительные: гидравлика модели и соединения требуют проверки.")
    if pipes:
        notes.append("У1-У6: материалы и размеры труб приведены на листах «Трубы водомерного узла».")
    if state.missing:
        notes += ["Требует дополнения: " + "; ".join(state.missing) + "."]
    pages = []
    for page in range(1,schematic_count+1):
        content = ([common_principle_contents(project,state)] if common_principle else
                   [_text(28,17,"Узлы учёта воды и вводы водопровода",5),
                   _text(28,25,"ИОС2 · Принципиальная схема водомерного узла",3.5),
                   _assembly(project,state), _inlets(project,state,1+(page-1)*2), _panel(project,state)])
        y = 235
        for note in notes:
            for line in _lines(note,196,2.5):
                content.append(_text(25,y,line,2.5))
                y += 4.3
        if y > 290:
            raise ValueError("Примечания ВУ не помещаются на лист")
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-detail="gost-21.619-annex-g">'
                     '<defs><pattern id="wall" width="3" height="3" patternUnits="userSpaceOnUse">'
                     '<path d="M0 3 L3 0" stroke="black" stroke-width=".2"/></pattern></defs>'
                     '<rect width="420" height="297" fill="white"/>' + ''.join(content)
                     + _frame(project,page,total) + '</svg>')
    for index, content in enumerate(catalogue, schematic_count+1):
        page_kind = 'data-meter-modes="true"' if 'data-vu-mode-table' in content else 'data-meter-catalogue="true"'
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" '+page_kind+'>'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for index, content in enumerate(pipes, schematic_count+len(catalogue)+1):
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-pipes="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for index, content in enumerate(connections, schematic_count+len(catalogue)+len(pipes)+1):
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-connections="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for index, content in enumerate(reducers, schematic_count+len(catalogue)+len(pipes)+len(connections)+1):
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-reducers="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for index, content in enumerate(chain, schematic_count+len(catalogue)+len(pipes)+len(connections)+len(reducers)+1):
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-chain="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for index, content in enumerate(conditions, schematic_count+len(catalogue)+len(pipes)+len(connections)+len(reducers)+len(chain)+1):
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-rules="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,index,total) + '</svg>')
    for content in mounting:
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-mounting="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,len(pages)+1,total) + '</svg>')
    for content in hot_pages:
        pages.append('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                     'viewBox="0 0 420 297" data-meter-hot-node="true">'
                     '<rect width="420" height="297" fill="white"/>' + content
                     + _frame(project,len(pages)+1,total) + '</svg>')
    return pages
