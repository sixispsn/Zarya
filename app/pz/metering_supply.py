"""Explicit common-VU feed boundary; not inferred pipe lengths or hydraulics.

The detailed VU remains one reusable MeteringChain. The selected external
graph (merge-before or G.1 switching) is shared by maintenance, drawing and
specification. No flow is divided by inlet count.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class InletFeed:
    number: int
    source_id: str
    valve_id: str
    junction_id: str = "inlet"

    @property
    def fire_ids(self):
        return tuple(f"supply_fire_{role}_{self.number}" for role in ("takeoff", "valve", "outlet"))


def inlet_feeds(state):
    if not state.common_inlets:
        return ()
    return tuple(InletFeed(i, f"supply_source_{i}", f"supply_valve_{i}")
                 for i in range(1, state.inputs_count + 1))


def supply_component_ids(state):
    if state.switching_bridge:
        from app.pz.metering_switching import component_ids
        return component_ids(state)
    feeds = inlet_feeds(state)
    if not feeds:
        return set()
    return {'supply_header', *(f.valve_id for f in feeds),
            *(i for f in feeds for i in f.fire_ids if state.fire_branch)}


def supply_spec_rows(project, state, selection):
    if state.switching_bridge:
        from app.pz.metering_switching import spec_rows
        return spec_rows(project, state, selection)
    from app.pz.spec import SpecRow
    feeds = inlet_feeds(state)
    if not feeds:
        return []
    part = selection.selected("inlet_valve")
    ids = tuple(f.valve_id for f in feeds)
    dn = f"DN{project.metering_detail.inlet_dn}" if project.metering_detail.inlet_dn else "DN уточнить"
    rows = [SpecRow(1, f"Запорная арматура отдельных вводов перед общим ВУ, {dn}",
        type_mark=(part.model + (f", арт. {part.article}" if part.article else "")) if part else "",
        manufacturer=part.manufacturer if part else "", unit="шт.", qty=len(feeds),
        diagram_pos="ВВ", component_ids=ids, catalogue_id=part.id if part else "",
        quantity_basis="metering_scheme", quantity_source=f"1 на ввод × {len(feeds)} вводов",
        note="Вне размерной цепочки общего ВУ; монтаж и присоединения уточнить. "
             + ("Исполнение предварительное; проверки P/T и ориентации сохраняются." if part else "Модель уточнить.")),
        SpecRow(1, "Соединительный трубопровод вводов перед общим ВУ",
            unit="компл.", qty=None, component_ids=("supply_header",),
            note="Трубы, фасонные части, опоры и соединения по привязке; длина рисунка не является количеством. "
                 "Проверить давления источников и защиту от обратного перетока; ТУ не заменяются схемой.")]
    if state.fire_branch:
        dn_fire = f"DN{project.metering_detail.fire_branch_dn}" if project.metering_detail.fire_branch_dn else "DN уточнить"
        rows += [SpecRow(1, f"Арматура ответвлений В2 до объединения вводов, {dn_fire}",
            unit="шт.",qty=len(feeds),diagram_pos="ВП",component_ids=tuple(f.fire_ids[1] for f in feeds),
            quantity_basis="metering_scheme",quantity_source="1 на каждом вводе до общего учёта",
            note=("С электроприводом. " if project.fire.branch_electric_valves else "") + "Модель и автоматику уточнить; В2 не проходит через общий ВУ."),
            SpecRow(1,"Узлы и трубопроводы ответвлений В2 до учёта",unit="компл.",qty=None,
                component_ids=tuple(i for f in feeds for i in (f.fire_ids[0], f.fire_ids[2])),
                note="Два самостоятельных подключения В2 сохранены. Фасонные части, трубы и монтаж по схеме пожарной насосной; не включены по длине рисунка.")]
    return rows


def extend_service_network(network, state):
    if state.switching_bridge:
        from app.pz.metering_switching import extend_network
        return extend_network(network, state)
    from dataclasses import replace
    from app.pz.maintenance_engine import ServiceNode, ServiceLink
    feeds = inlet_feeds(state)
    if not feeds:
        return network
    # The core inlet is a junction now, not a third fictitious water source.
    nodes = tuple(replace(n, kind="component", wet=True) if n.id == "inlet" else n
                  for n in network.nodes)
    links = list(network.links)
    for feed in feeds:
        nodes += (ServiceNode(feed.source_id, f"Ввод {feed.number}: наружная сеть", "source", wet=False),
                  ServiceNode(feed.valve_id, f"Отсечка ввода {feed.number}", "isolation"))
        links.append(ServiceLink(feed.source_id, feed.valve_id))
        if state.fire_branch:
            tee, valve, outlet = feed.fire_ids
            nodes += (ServiceNode(tee,f"Ответвление В2 ввода {feed.number}"),
                      ServiceNode(valve,f"Отсечка В2 ввода {feed.number}","isolation"),
                      ServiceNode(outlet,f"В2 ввода {feed.number}: возможный подпор","source",wet=False))
            links.extend((ServiceLink(feed.valve_id,tee),ServiceLink(tee,feed.junction_id),
                          ServiceLink(tee,valve),ServiceLink(valve,outlet)))
        else:
            links.append(ServiceLink(feed.valve_id, feed.junction_id))
    return replace(network, nodes=nodes, links=tuple(links))


def common_inlet_contents(project, state):
    """Feed overview in the lower half of the existing Appendix-Г sheet.

    The VU block refers to the scaled core above/on dimensional sheets; its
    size is not a manufacturing length. No duplicated meter symbol per inlet.
    """
    from app.pz.metering_detail import _text, _line, _path, _gate, _arrow, _dn
    feeds = inlet_feeds(state)
    g = [_text(28,149,"2. Два ввода - общий водомерный узел",5)]
    if len(feeds) != 2:
        return ''.join(g + [_text(28,166,"Более двух вводов: отдельная компоновка по ТУ.")])
    g += ['<g data-common-metering="true" data-assembly-count="1">',
          '<defs><pattern id="vu-supply-wall" width="3" height="3" patternUnits="userSpaceOnUse"><path d="M0 3 L3 0" stroke="black" stroke-width=".2"/></pattern></defs>',
          '<rect x="65" y="160" width="6" height="59" fill="url(#vu-supply-wall)" stroke="black" stroke-width=".35"/>']
    for feed, y in zip(feeds, (174,211)):
        g += [f'<g data-inlet="{feed.number}" data-feed-source="{feed.source_id}">',
              f'<rect x="63" y="{y-2}" width="10" height="4" fill="white"/>',
              _line(63,y-2,73,y-2,.25), _line(63,y+2,73,y+2,.25),
              _line(31,y,110,y,attrs='data-wall-crossing="true"'),
              _gate(88,y,size=2), _arrow(104,y),
              _text(31,y-5,f"Ввод {feed.number}",3.5),
              _text(31,y+6,_dn(project.metering_detail.inlet_dn),2.5),
              _text(88,y-5,"ВВ",2.5,"middle"), '</g>']
    g += [_line(110,174,110,211), _line(110,192,137,192),
          '<rect data-common-vu-reference="true" x="137" y="183" width="75" height="18" fill="white" stroke="black" stroke-width=".35"/>',
          _text(174.5,190,"Общий ВУ-1",3.5,"middle"),
          _text(174.5,197,"Состав и обводная - фрагмент 1",2.5,"middle"),
          _line(212,192,277,192), _arrow(274,192),
          _text(217,187,"К насосной / сети",2.5),
          _text(217,199,"В1+В2" if state.combined else "В1",3.5),
          '</g>']
    if state.fire_branch:
        for feed,y,branch_y in zip(feeds,(174,211),(162,222)):
            g += [_path(f'M100 {y} V{branch_y} H184',.45,
                        f'data-pre-meter-fire="true" data-feed-fire="{feed.fire_ids[2]}"'),
                  _gate(125,branch_y,size=1.8,electric=project.fire.branch_electric_valves),
                  _arrow(181,branch_y), _text(189,branch_y+1,f"К В2 · ввод {feed.number}",2.5)]
        g.append(_text(116,231,"В2 до объединения вводов; общий ВУ только для В1",2.5))
    else:
        g += [_text(116,218,"Каждый ввод - 100% расчётного расхода",2.5),
              _text(116,224,"Учёт и переключения - согласовать по ТУ",2.5)]
    return ''.join(g)
