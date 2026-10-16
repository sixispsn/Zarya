"""Fully gridded A3 mode schedules, using the same IDs as G.1 and the audit."""
from html import escape

from app.pz.metering_modes import POSITION_LABELS, STATUS_LABELS, modes_for_project


def _schedule(title, columns, header, rows, *, kind, intro='', footer=()):
    from app.pz.metering_detail import _text, _lines, _line
    from app.pz.metering_table_grid import table_grid_sides
    pages = []
    def begin():
        g = [f'<g data-vu-mode-table="{kind}">', _text(28,17,title,5)]
        if intro:
            g.append(_text(28,26,intro,3.5))
        return g
    g, y, top = begin(), 33., 33.

    def draw(values, attrs=''):
        nonlocal y
        wrapped = [_lines(str(v), columns[i+1]-columns[i]-4, 3.5) for i,v in enumerate(values)]
        height = max(10, 4 + 5.5*max(map(len, wrapped)))
        g.append(_line(columns[0],y,columns[-1],y,.25))
        g.append('<g '+attrs+'>')
        for i, lines in enumerate(wrapped):
            for j, line in enumerate(lines):
                g.append(_text(columns[i]+2,y+5.5+j*5.5,line,3.5))
        g.append('</g>')
        y += height

    def finish():
        g.append(table_grid_sides(columns,top,y,kind=kind))
        for i,line in enumerate(footer):
            g.append(_text(28,222+i*5.5,line,3.5))
        g.append('</g>')
        pages.append(''.join(g))

    draw(header)
    for ident, values in rows:
        height = max(10,4+5.5*max(len(_lines(str(v),columns[i+1]-columns[i]-4,3.5)) for i,v in enumerate(values)))
        if y + height > 215:
            finish(); g = begin(); y = top; draw(header)
        if y + height > 215:
            raise ValueError('Строка режимов ВУ не помещается на лист')
        draw(values, f'data-mode-row="{escape(ident)}"')
    finish()
    return pages


def mode_contents(project, state=None):
    report = modes_for_project(project,state)
    if not report:
        return []
    valves = report['valves']
    from app.pz.metering_spec import build_metering_spec_section
    spec_marks = {ident: row.diagram_pos for row in build_metering_spec_section(project).rows
                  for ident in row.component_ids}
    pages = _schedule('ВУ Г.1. Обозначения арматуры', (27,52,87,263,407),
        ('Метка','Поз. СО','Назначение','Штатное состояние'),
        [(v['id'],(v['mark'],spec_marks.get(v['id'],'-'),v['title'],
           'По алгоритму В2' if v['normal']=='unknown' else
           'Закрыто, пломба' if v['group']=='bypass' else
           'Сообщение с манометром' if v['normal']=='measurement' else
           'Открыто' if v['normal']=='open' else 'Закрыто')) for v in valves],
        kind='mode-tags',intro='Метки З/К относятся к управлению; позиции спецификации обозначены отдельно.',
        footer=('Обратные клапаны не имеют команды О/З и не заменяют ремонтную отсечку.',
                'Наличие сливного крана не подтверждает опорожнение всей отключённой части.'))
    n = len(valves)
    columns = (27,100,*[100+12*i for i in range(1,n+1)],407)
    pages += _schedule('ВУ Г.1. Проектная таблица режимов', columns,
        ('Режим',*[v['mark'] for v in valves],'Статус'),
        [(r['id'],(r['title'],*[('-' if r['status']=='not_applicable' else POSITION_LABELS[r['positions'][v['id']]]) for v in valves],
                    'Уточнить' if r['status']=='needs_data' else STATUS_LABELS[r['status']])) for r in report['modes']],
        kind='mode-matrix',intro='Не инструкция переключений. Гидравлика и фактические положения не подтверждены.',
        footer=('О - открыто; З - закрыто; ? - не задано; М - измерение; С - снимаемый элемент.',
                'Штатно З7/З8 опломбированы. Сервисные отборы открывают только после безопасного отсечения.'))
    findings = {
        'NO_SUPPLY':'Подача к требуемым выходам не обеспечена.',
        'SUPPLY_NOT_PROVEN':'Подача зависит от неизвестных положений.',
        'UNMETERED_PATH':'Есть путь в обход счётчика.',
        'INLET_CROSSFEED_POSSIBLE':'Есть связь вводов до счётчика; проверить давления и ТУ.',
        'UNAVAILABLE_INLET_CONNECTED':'Отключённый ввод остаётся связан с источником/подпором.',
        'LIVE_SERVICE_PORT':'Сервисный отбор не отсечён от воды.',
        'TARGET_NOT_ISOLATED':'Снимаемый элемент не изолирован от всех источников.',
        'SERVICE_NOT_CONFIRMED':'Сброс давления, слив и впуск воздуха не подтверждены.',
        'UNKNOWN_POSITIONS':'Часть положений не определена.',
    }
    rows=[]
    for row in report['modes']:
        result = row['checks']
        messages = list(row['notes'])
        if result:
            messages += [findings[c] for c in (*result['failures'],*result['pending'])
                         if c not in ('INLET_CROSSFEED_POSSIBLE','UNKNOWN_POSITIONS')]
            if result['paths']:
                # Short engineering result, not a made-up traversal order.
                messages.append('Путь к выходам '+row['output_scope']+': '+('есть.' if result['supplied'] else 'не подтверждён.'))
        rows.append((row['id'],(row['title'],' '.join(dict.fromkeys(messages)))))
    pages += _schedule('ВУ Г.1. Условия и ограничения режимов',(27,105,407),
        ('Режим','Проверка и необходимые решения'),rows,kind='mode-conditions',
        intro='СП 30: 8.23, 12.11 (изм. 3), 12.12, 12.16; ГОСТ Р 21.619-2023: 5.2.2.6, Г.1.',
        footer=('Для ремонта каждой задвижки/клапана: отдельные границы отсечения на листах обслуживания.',
                'Ни одно состояние этой таблицы не является разрешением на эксплуатационные переключения.'))
    return pages
