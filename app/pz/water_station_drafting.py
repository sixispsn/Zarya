"""Paper-space IOS2 station/HWS sheets; presentation only, no sizing.

The station and building fragment are separate sheets (§5.2.2.3 of
GOST R 21.619-2023). A representative circulation path is a principle,
not a calculated T4 ring or a bill of quantities for the whole building.
"""
from html import escape

from app.pz import ugo
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.metering_detail import _text, _line, _path, _arrow, _gate, _leader, _lines
from app.pz.section_level_mark import level_mark
from app.pz.water_pipe_binding import bind_t3_pipes
from app.pz.wastewater_building_drafting import drawing_frame_svg
from app.pz.hws_presentation import hws_principle
from app.pz.water_service_assemblies import shows_riser_balance, BALANCE_MODES
from app.pz.drawing_numbers import water_elevation_value
from app.pz.water_station_review import station_counts  # compatibility export


def _num(value, places=2):
    return f"{value:.{places}f}".replace(".", ",")


def _level(key,x,y,value,caption,**kwargs):
    # IOS2 display rounding agrees with the main V1 sheet; retain raw datum.
    shown = float(water_elevation_value(value))
    return _tag(key,level_mark(key,x,y,shown,caption,**kwargs),source_elevation_m=value)


def _tag(key, body, **data):
    attrs = " ".join(f'data-{name.replace("_", "-")}="{escape(str(value))}"' for name, value in data.items())
    return f'<g data-component="{escape(key)}" {attrs}>{body}</g>'


def _pipe(key, points, system="В1", *, start="", end="", scope="principle"):
    d = "M" + " L".join(f"{x:g},{y:g}" for x, y in points)
    return _path(d, .6, f'data-pipe="{key}" data-system="{system}" '
                 f'data-from="{start}" data-to="{end}" data-scope="{scope}"')


def _flow(x, y, angle=0):
    return f'<g transform="rotate({angle},{x},{y})">{_arrow(x,y)}</g>'


def _instrument(key, x, y, code):
    return _tag(key, _line(x,y,x,y-9,.25)
        + f'<circle cx="{x}" cy="{y-12}" r="3" fill="white" stroke="black" stroke-width=".25"/>'
        + _text(x,y-11,code,2.5,"middle"))


def _meter(key, x, y, row):
    if row is None:
        return ""
    return _tag(key, ugo.meter(x,y,rw=8,rh=6,ext=0,w=.35)
        + _text(x,y+10,f"DN{row.dn}",3.5,"middle"), dn=row.dn)


def _branch_meter(project, node):
    # Same semantic identity used by the specification. Never treat the
    # common inlet meter as a second meter on the cold/HWS branch.
    from app.pz.meter_validation import meter_node_key
    from app.pz.meter_products import primary_meter
    primary = primary_meter(project)
    return next((row for row in project.meters.rows if row is not primary and meter_node_key(row) == node), None)


def _notes(lines, *, x=28, y=193, width=378):
    out = []
    for value in lines:
        for line in _lines(value, width, 3.5):
            out.append(_text(x,y,line))
            y += 6
    return "".join(out)


def _sheet(project, title, body, page, total, *, show_title=True):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
            f'viewBox="0 0 420 297" data-water-sheet="{page}">'
            '<rect width="420" height="297" fill="white"/>'
            + (_text(28,18,title,5) if show_title else '') + body
            + drawing_frame_svg(project.document,width_mm=420,height_mm=297,
                title=title,system_label="В1, Т3, Т4",sheet_no=page,sheet_total=total)
            + '</svg>')


def _station_sheet(project, total):
    from app.pz.water_station_principle import station_sheet
    return station_sheet(project, total)


def _hws_sheet(project,total):
    source = project.source
    principle = hws_principle(project)
    kind = getattr(project.building.hws_type,"value",project.building.hws_type)
    pipes = bind_t3_pipes(project)
    if principle.zones_unresolved:
        body = _notes([
            "ГВС разделяется на зоны. Привязка источников, стояков и циркуляционных колец не задана.",
            "Объединять зоны в один условный контур без исходной схемы недопустимо.",
            "Т3/Т4: требуется дополнение топологии; окончательная схема не сформирована.",
        ],y=42)
        return _sheet(project,"ГВС. Зональная схема требует данных",body,2,total)
    if kind == "local":
        body = _notes([
            "Местные водонагреватели. Общая циркуляционная сеть Т4 автоматически не добавляется.",
            "Размещение, схема учёта и обвязка местных приборов должны быть заданы проектом.",
        ],y=42)
        return _sheet(project,"ГВС. Местное приготовление",body,2,total)
    if not shows_riser_balance(project):
        body = _notes([
            "Балансировка: " + BALANCE_MODES[project.building.water_service_layout.balance_mode] + ".",
            "Состав и количество клапанов переданы в спецификацию по выбранной компоновке.",
            "Геометрия этой циркуляционной схемы пока не задана. Типовой стояковый контур её не заменяет.",
            "Размещение ветвей и соединений требует дополнения. DN, Kv и настройки - по расчёту колец.",
        ],y=42)
        return _sheet(project,"ГВС. Компоновка циркуляции требует дополнения",body,2,total)
    g = [_text(28,28,"Характерный циркуляционный контур. Не аксонометрия и не расчёт колец Т4."),
         _text(250,40,"К водоразборным приборам Т3"),
         _text(250,47,f"Подводки {pipes['apartment'].label}")]
    # A draw-off branches from T3; it is not put in series with the return.
    g += [_pipe("hws-draw-off",[(260,75),(260,55),(303,55)],"Т3",start="top",end="fixtures"),
          _gate(285,55),_flow(302,55),
          _pipe("t3-riser",[(260,150),(260,75)],"Т3",start="t3-main",end="top"),
          _pipe("representative-circulation",[(260,75),(350,75),(350,200)],"Т4",start="top",end="t4-return",scope="representative"),
          _flow(260,105,-90),_flow(324,75),_flow(350,158,90),
          _text(219,112,f"Т3 {pipes['riser'].label}"),
          _text(356,122,"Т4"),_text(356,129,"DN уточнить",2.5),
          _gate(260,150),_tag("circulation-balance",ugo.balance_v(350,175,tri=2.5,stem=7,rk=2,w=.35)),
          _leader("circulation-balance",(350,175),(363,190),406,"Ручной клапан","DN, Kv не заданы"),
          _instrument("temperature-supply",238,150,"TI"),
          _instrument("temperature-return",293,200,"TI")]
    if principle.local_circulation_pump:
        # Cold makeup meets the return AFTER the heater-branch meter and
        # the cold check valve. Circulation cannot run through the cold meter.
        g += [_pipe("cold-to-heater",[(40,150),(115,150)],start="heater-meter-out",end="return-join"),
              _pipe("mixed-heater-feed",[(115,150),(145,150)],start="return-join",end="heater-in"),
              _gate(68,150),ugo.check_h(94,150,tri=2.8,w=.35),_flow(108,150),
              _text(28,125,"В1 после узла учёта ГВС"),_text(28,132,"См. лист 1"),
              _text(30,161,pipes['feed'].label),
              _pipe("heater-water-path",[(145,150),(170,150)],"Т3",start="heater-in",end="heater-out"),
              # Dashed boundary identifies a design interface, not a made-up
              # manufacturer's heat-exchanger symbol or primary-side piping.
              _tag("heater-interface",f'<rect x="140" y="135" width="36" height="30" fill="none" '
                   'stroke="black" stroke-width=".25" stroke-dasharray="2 1"/>'),
              _leader("heater",(145,135),(160,98),245,"Узел нагрева ГВС","Схема узла - ТМ/ИТП"),
              _pipe("t3-main",[(170,150),(260,150)],"Т3",start="heater-out",end="t3-main"),_flow(214,150),
              _text(184,162,f"Т3 {pipes['main'].label}"),
              _pipe("t4-return",[(350,200),(115,200),(115,150)],"Т4",start="t4-return",end="return-join",scope="representative"),
              _tag("return-join",'<circle cx="115" cy="150" r="1.1" fill="black"/>'),
              _gate(217,200),ugo.check_h(151,200,tri=2.8,w=.35,flow="left"),_gate(134,200),
              _tag("circulation-pump-pending",ugo.pump(183,200,r=5,w=.35,ext=0,rot=180),selection="pending"),
              _flow(254,200,180),
              _leader("circulation-pump",(183,195),(200,178),266,"НЦ - циркуляция","Q/H не определены"),
              _text(36,191,"Возврат Т4"),_text(36,198,"после учёта и ОК",2.5)]
    else:
        g += [_pipe("external-t3",[(60,150),(260,150)],"Т3",start="external-t3",end="t3-main"),
              _pipe("external-t4",[(350,200),(60,200)],"Т4",start="t4-return",end="external-t4",scope="representative"),
              _flow(202,150),_flow(200,200,180),_text(30,137,"Т3 от внешнего источника"),
              _text(30,216,"Т4 к источнику; условия присоединения по ТУ")]
    g += [_notes(principle.drawing_notes,y=222),
          _notes(["Т3: размеры - из заданных участков.",
                  "Теплоизоляция - по расчёту проекта.",
                  "Т3/Т4: схема требует дополнения;",
                  "не окончательный подбор оборудования."],y=252,width=193)]
    return _sheet(project,"Т3, Т4. Принципиальная схема ГВС",
        f'<g data-hws-mode="{principle.mode}" data-circulation-status="principle-only">'+''.join(g)+'</g>',2,total)


def build_pump_zone_scheme_pages(project, *, include_building_section=True, include_review=False):
    ensure_drafting_font_registered()
    from app.pz.hws_building_drafting import can_draw_hws_section, build_hws_section
    from app.pz.water_residential_section import (
        can_draw_residential_water_section, build_residential_water_section,
    )
    # A standalone station PDF must not resurrect the old anonymous draw-off
    # lines when the same project supports the accepted residential cutaway.
    # Match IOS2's explicit split only when a separate V2 design exists. Never
    # hide an unsupported fire topology or mutate the source project.
    building_project = project
    if include_building_section and (project.fire_pumps.station_design or project.fire_pumps.pressure_review):
        from copy import deepcopy
        building_project = deepcopy(project)
        building_project.fire.required = False
        building_project.fire_pumps.required = False
    residential = include_building_section and can_draw_residential_water_section(building_project)
    has_hws = getattr(project.building.hws_type,"value",project.building.hws_type) != "none"
    section = include_building_section and (residential or can_draw_hws_section(project))
    from app.pz.water_station_review_drawing import station_review_contents
    review = station_review_contents(project) if include_review else []
    total = (2 if has_hws else 1) + int(section) + len(review)
    pages = [_station_sheet(project,total)]
    if has_hws:
        pages.append(_hws_sheet(project,total))
    if section:
        pages.append(build_residential_water_section(building_project,
            profile='residential_full_bath',sheet_no=3,sheet_total=total).svg
            if residential else build_hws_section(project,3,total))
    for content in review:
        from xml.etree import ElementTree as ET
        title = next(e.text for e in ET.fromstring('<g>'+content+'</g>').iter() if e.tag=='text' and e.text)
        pages.append(_sheet(project, title, content, len(pages)+1, total, show_title=False))
    return pages
