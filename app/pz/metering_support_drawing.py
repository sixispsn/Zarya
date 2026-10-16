"""Support references in the same VU package, not an invented mounting drawing."""
from app.pz.metering_supports import support_report


def support_contents(project, state, layout):
    if not project.metering_detail.mounting.supports:
        return []
    from app.pz.metering_detail import _text, _lines, _line
    from app.pz.metering_layout import _part_svg, _connection_svg
    report = support_report(project, state)
    g = [_text(28,17,'ВУ. Точки постоянных опор',5),
         _text(28,26,'Привязка к участкам схемы; расстояния до опор и строительных конструкций не назначены.',3.5),
         _text(28,34,'ОП - обозначение точки, не условное изображение готового крепления. Схема без масштаба.',3.5)]
    # Reuse the actual network/UGO, not a hand-maintained copy of its topology.
    all_points = [xy for p in layout.parts for xy in p.points]
    if all_points:
        xs, ys = zip(*all_points)
        scale = min(350 / max(max(xs)-min(xs),1), 70 / max(max(ys)-min(ys),1), 1)
        dx, dy = 216.5-(min(xs)+max(xs))*scale/2, 49-min(ys)*scale
        g.append(f'<g transform="translate({dx:g},{dy:g}) scale({scale:g})" data-support-network="true">')
        g.extend(_connection_svg(link) for link in layout.links)
        g.extend(_part_svg(p,layout.scale,symbols_only=True,include_dimension=False) for p in layout.parts)
        g.append('</g>')
        for r in report['rows']:
            if not r['active']:
                continue
            p = layout.part(r['node'])
            # Anchor ON a real pipe segment, never the polyline bounding-box centre.
            segments = list(zip(p.points,p.points[1:]))
            a,b = max(segments,key=lambda ab:(ab[0][0]-ab[1][0])**2+(ab[0][1]-ab[1][1])**2)
            x,y = dx+(a[0]+b[0])*scale/2, dy+(a[1]+b[1])*scale/2
            g += [f'<g data-support-point="{r["key"]}" data-pipe-node="{r["node"]}">',
                  f'<circle cx="{x:g}" cy="{y:g}" r="1.3" fill="white" stroke="black" stroke-width=".3"/>']
            if abs(a[0]-b[0]) < abs(a[1]-b[1]):
                g += [_line(x-1.3,y,x-12,y,.25), _text(x-14,y+1,r['mark'],3.5,'end')]
            else:
                g += [_line(x,y+1.3,x,y+8,.25), _text(x,y+13,r['mark'],3.5,'middle')]
            g.append('</g>')
    y=141
    g += [_text(30,y+6,'Поз.',3.5),_text(49,y+6,'Участок / изделие (предварительно)',3.5),
          _text(366,y+6,'Всего',3.5)]
    boundaries=[y,y+10]; y+=10
    for r in report['rows']:
        p=r['product'] if r['active'] else None
        lines = _lines(r['title'] + ': ' + (p.title if p else 'выбор несовместим, см. проверку'),310,3.5)
        g += [_text(30,y+6,r['mark'],3.5), _text(366,y+6,r['quantity'] if r['quantity'] else '?',3.5)]
        for i,line in enumerate(lines):
            g.append(_text(49,y+6+i*5,line,3.5))
        y+=max(12,len(lines)*5+5); boundaries.append(y)
    for x in (28,47,361,405):
        g.append(_line(x,boundaries[0],x,y,.25))
    g.extend(_line(28,v,405,v,.25) for v in boundaries)
    pages=[''.join(g)]
    # Sourced dimensions and unresolved checks are text, never half-drawn tables.
    content=[]; y=0
    blocks=[]
    for r in report['rows']:
        p=r['product']; lines=[r['mark']+' - '+r['title']]
        if p:
            lines += [p.title + '. ' + p.manufacturer + '.',
                      'Размеры: основание '+ ' x '.join(f'{v:g}' for v in p.base_mm)+' мм; '
                      + (f'L={p.length_mm:g} мм; профиль '+' x '.join(f'{v:g}' for v in p.section_mm)+' мм.'
                         if p.length_mm else f'высота {p.height_range_mm[0]:g}-{p.height_range_mm[1]:g} мм.')]
            if p.kind=='wall_console':
                lines.append(f'Табличная сила вниз: в L/2 - {p.center_load_n:g} Н; в L - {p.end_load_n:g} Н. Это предел консоли, не всей опоры.')
            lines.append('Комплект: '+', '.join(f'{name} {qty} шт.' for name,qty in p.included)+'.')
            from app.data.metering_supports import SOURCES
            lines.append('Источник: '+'; '.join(SOURCES[s]['locator'] for s in p.sources)+'.')
        if r['height_mm'] is not None:
            lines.append(f'Заданная высота стойки {r["height_mm"]:g} мм; не отметка оси трубы.')
        if r['reaction_n'] is not None:
            lines.append(f'Заданная сила {r["reaction_n"]:g} Н; статус: '+ ('превышение предела.' if r['load_status']=='overload'
                         else 'в пределах компонента; крепление не подтверждено.' if r['load_status']=='component_limit_only'
                         else 'нет применимого предела.'))
        lines += ['Ошибка: '+x for x in r['errors']] + ['Уточнить: '+x for x in r['pending']]
        blocks.append(lines)
    blocks.append(['Обслуживание: проверка связности после снятия элемента',
                  *[r['title']+': '+ (f'групп без точки опирания - {len(r["uncovered"])}.' if r['uncovered']
                         else 'точки есть во всех оставшихся группах; устойчивость не подтверждена.') for r in report['scenarios']],
                  *report['errors'], 'Нагрузки, деформации, временные крепления и монтаж проверяются отдельно. Разрешение на разборку не выдано.'])
    for block in blocks:
        lines=[line for paragraph in block for line in _lines(paragraph,375,3.5)]
        if not content or y+len(lines)*5.5+7>222:
            if content: pages.append(''.join(content))
            content=[_text(28,17,'ВУ. Опоры - размеры и границы проверки',5),
                     _text(28,26,'Постоянные опоры; монтажные временные подставки не включены в поставку автоматически.',3.5)]
            y=39
        for line in lines:
            content.append(_text(28,y,line,3.5)); y+=5.5
        y+=7
    if content: pages.append(''.join(content))
    return pages
