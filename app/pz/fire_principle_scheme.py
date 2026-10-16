"""Paper-space V2 station and riser sheets from the accepted ordinary model.

No Samara geometry, guessed DN, additional pressure loss or floor-wise cabinet
expansion. SP 10 12.30 equipment is a minimum design requirement, not a factory
BOM. The exact graph remains an appendix; riser cross-references preserve it.
"""
from math import isfinite
from xml.sax.saxutils import escape

from app.pz import ugo
from app.pz.fire_review_binding import validate_binding, station_requirement_rows
from app.pz.leader_layout import _text_width
from app.pz.section_level_mark import level_mark, level_text
from app.pz.wastewater_building_drafting import drawing_frame_svg


class Sheet:
    def __init__(self, project, title, page, total):
        self.project, self.title, self.page, self.total = project, title, page, total
        self.parts = ['<rect width="420" height="297" fill="white"/>']
        self.text(25, 16, title, 5)

    def text(self, x, y, value, height=3.5, anchor="start", width=None):
        # Height is the physical cap height, not the SVG em box.
        size = height / .823
        value = str(value)
        if width is not None and _text_width(value, size) > width:
            words, lines, line = value.split(), [], ""
            for word in words:
                trial = f"{line} {word}".strip()
                if line and _text_width(trial, size) > width:
                    lines.append(line); line = word
                else:
                    line = trial
            lines.append(line)
            for i, line in enumerate(lines):
                self.text(x, y + i * (height + 2), line, height, anchor)
            return len(lines) * (height + 2)
        self.parts.append(f'<text x="{x:g}" y="{y:g}" font-family="OpenGOST type B" '
            f'font-size="{size:g}" data-paper-text-height-mm="{height:g}" '
            f'text-anchor="{anchor}">{escape(value)}</text>')
        return height + 2

    def line(self, x, y, xx, yy, w=.6, attrs=""):
        self.parts.append(f'<path d="M{x:g},{y:g} L{xx:g},{yy:g}" stroke="black" '
                          f'stroke-width="{w}" fill="none" {attrs}/>')

    def arrow(self, x, y, rot=0):
        self.parts.append(f'<path d="M{x:g},{y:g} l-3,-1.2 v2.4 Z" fill="black" '
                          f'transform="rotate({rot},{x},{y})"/>')

    def component(self, identity, svg):
        self.parts.append(f'<g data-component="{identity}">{svg}</g>')

    def transition(self, identity, x, y, left_dn, right_dn):
        """One-line DN change, not a scale drawing of a reducer product."""
        base, tip = (x-3, x+3) if left_dn > right_dn else (x+3, x-3)
        self.component(identity,
            f'<path data-dn-left="{left_dn}" data-dn-right="{right_dn}" '
            f'd="M{base:g},{y-2:g} V{y+2:g} L{tip:g},{y:g} Z" '
            'fill="white" stroke="black" stroke-width=".25"/>')

    def dot(self, x, y):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r=".9" fill="black"/>')

    def pressure(self, x, y, identity):
        self.component(identity,
            f'<path d="M{x},{y} v-7" fill="none" stroke="black" stroke-width=".25"/>'
            f'<circle cx="{x}" cy="{y-10}" r="3" fill="white" stroke="black" stroke-width=".25"/>'
            f'<path d="M{x-1.3},{y-8.7} l2.6,-2.6" stroke="black" stroke-width=".25"/>')
        self.text(x, y-16, identity, 3.5, "middle")

    def svg(self):
        frame = drawing_frame_svg(self.project.document, width_mm=420, height_mm=297,
            title=self.title, system_label="В2", sheet_no=self.page, sheet_total=self.total)
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
                'viewBox="0 0 420 297">' + ''.join(self.parts) + frame + '</svg>')


def build_station_sheet(project, *, page=1, total=4, graph_page=3):
    r = validate_binding(project)
    if r is None:
        raise ValueError("Нужен принятый предварительный вариант В2")
    model, pump = project.fire_station_model_input, project.fire_pumps
    from app.intake.studio_fire_pipework import from_model, connection_rows
    from app.intake.studio_fire_location import from_model as location_from_model, description
    pipework = from_model(model)
    location = location_from_model(model)
    from app.data.fire_pump_geometry import connection_review
    geometry = connection_review(model, pump.model)
    roles = {e.id:e for e in pipework.elements} if pipework else {}
    s = Sheet(project, "Насосная В2. Принципиальная схема", page, total)
    s.text(25, 25, f"{pump.model}: Н1 рабочий, Н2 резервный. Один насос питает оба выхода.")
    s.text(25, 33, f"Контрольный режим Q={pump.wp_q:.3f} м3/ч; H={pump.wp_h:.3f} м. "
           f"N двигателя {pump.power_kw:g} кВт; потребляемая мощность не подтверждена.", 3)
    # Known source paths terminate at a common suction boundary. Their datum is
    # at the connection, NOT a guessed wall-penetration elevation.
    for i, (feed, y) in enumerate(zip(model['supplies'], (78, 134)), 1):
        s.line(25, y, 108, y); s.arrow(47, y)
        s.text(25, y-13, feed['name'])
        dns = '/'.join(str(seg['dn']) for seg in feed['segments'])
        if location:
            # Local wall fragments: flow really crosses them. No XY location or
            # construction detail is inferred from an elevation-only input.
            for x in (33, 36):
                s.line(x, y-4, x, y+4, .25, 'data-inlet-wall="true"')
            s.parts.append(level_mark(f'inlet-{i}', 88, y,
                location['inlet_elevations_m'][feed['name']], 'проходка', width=28))
            s.text(25, y+8, f"DN {dns}; L={sum(seg['length_m'] for seg in feed['segments']):g} м; Hгар={feed['guaranteed_head_m']:g} м", 2.5)
        else:
            s.text(25, y-6, f"DN {dns}; путь {sum(seg['length_m'] for seg in feed['segments']):g} м", 3)
            s.text(25, y+8, f"Hгар={feed['guaranteed_head_m']:g} м", 3)
        s.text(25, y+15, f"Точка подключения {level_text(feed['source_elevation_m'])}", 3)
    s.line(108, 78, 108, 134)
    for i, y in enumerate((78, 134), 1):
        s.line(108, y, 323, y)
        if pipework:
            for side, x in (('suction', 121), ('discharge', 311)):
                header, branch = roles[side+'_header'].dn, roles[side+'_branch'].dn
                if header != branch:
                    left_dn, right_dn = (header, branch) if side=='suction' else (branch, header)
                    s.transition(('ПС' if side=='suction' else 'ПН')+str(i), x, y, left_dn, right_dn)
            s.text(177, y-4, f"DN{roles['suction_branch'].dn}", 3)
            s.text(274, y-4, f"DN{roles['discharge_branch'].dn}", 3)
        for x, ident in ((133, f'ЗС{i}'), (293, f'ЗН{i}')):
            s.component(ident, ugo.gate_h(x, y, tri=2.5, bar=3, w=.25))
            s.text(x, y+10, ident, 3.5, 'middle')
        s.pressure(165, y, f'PG{2*i-1}')
        s.component(f'Н{i}', ugo.pump(201, y, r=5, w=.5))
        if geometry:
            s.text(201, y-8, f"DN{geometry['nozzle_dn']}", 3, 'middle')
            for transition in geometry['transitions']:
                x = 185 if transition['side']=='suction' else 217
                ident = transition['prefix']+str(i)
                s.transition(ident, x, y, transition['left_dn'], transition['right_dn'])
                s.text(x, y+8, ident, 3, 'middle')
        s.text(201, y+12, f'Н{i}', 3.5, 'middle')
        s.text(201, y+19, 'рабочий' if i == 1 else 'резервный', 3, 'middle')
        s.pressure(235, y, f'PG{2*i}')
        s.component(f'КО{i}', ugo.check_h(263, y, tri=2.5, w=.25))
        s.text(263, y+10, f'КО{i}', 3.5, 'middle')
        if i == 1:
            reducer = pipework and roles['discharge_header'].dn != roles['discharge_branch'].dn
            s.arrow(304 if reducer else 313, y)
        s.dot(108, y); s.dot(323, y)
    s.line(323, 78, 323, 134)
    for j, y in enumerate((78, 134)):
        port = model['network']['source_node' if j == 0 else 'second_source_node']
        incident = [e['dn'] for e in model['network']['runs'] if port in (e['from_node'], e['to_node'])]
        s.line(323, y, 398, y); s.arrow(393, y)
        s.text(333, y-13, f"Выход {j+1}; см. лист {graph_page}", 3)
        s.text(333, y-6, 'DN ' + '/'.join(map(str, sorted(set(incident)))), 3)
        code = _node_code(model, port)
        s.text(333, y+9, f'{code} · {port}', 2.5, width=70)
    if pipework:
        s.text(140, 49, f"Коллекторы: всасывание DN{roles['suction_header'].dn}; напор DN{roles['discharge_header'].dn}", 3.5)
        for c in connection_rows(model):
            x = 108 if c['at']=='suction_header' else 323
            s.parts.append(f'<g data-auxiliary="{c["id"]}" data-at="{c["at"]}" data-kind="{c["kind"]}">')
            if c['kind']=='air':
                s.line(x, 78, x, 63)
                s.component(c['id'], ugo.air_valve(x, 63, stem=5, tw=1.8, th=2.5, w=.25))
                s.text(x-24 if x==108 else x+6, 54, f"{c['id']} DN{c['dn']}", 3)
            elif c['kind']=='drain':
                s.line(x, 134, x, 158)
                s.component(c['id'], ugo.gate_v(x, 147, tri=2, bar=2.5, w=.25))
                s.arrow(x, 158, 90)
                s.text(x-30 if x==108 else x+6, 156, f"{c['id']} DN{c['dn']}", 3)
            else:
                s.line(x, 106, 396, 106); s.arrow(396, 106)
                s.component(c['id'], ugo.gate_h(356, 106, tri=2, bar=2.5, w=.25))
                s.text(333, 101, f"{c['id']} DN{c['dn']}; закрыт", 3)
            s.parts.append('</g>')
        s.text(25, 41, f'Вспомогательные подключения и расчётная обвязка - лист {page+1}.', 3)
    else:
        s.text(115, 49, 'Коллекторы и насосные ветви: DN не задан', 3.5)
    s.parts.append(level_mark('pump-axis', 178, 167, model['pump_axis_m'],
                               'ось всас. патрубков' if location else 'ось насосов',
                               reference_x=222, width=32))
    basement = project.building.floor_elevations_m.get(-1)
    if location:
        s.line(25, 180, 401, 180, .25)
        s.parts.append(level_mark('station-floor', 65, 180,
                                 location['floor_elevation_m'], 'пол насосной', width=32))
        s.text(238, 168, description(location), 3, width=160)
        s.text(238, 176, 'Размещение условное; не монтажный план', 2.5)
    elif basement is not None:
        s.line(25, 180, 401, 180, .25)
        s.parts.append(level_mark('basement-reference', 65, 180, basement, 'пол подвала', width=32))
        s.text(238, 175, 'Пол и помещение насосной уточнить по АР', 3)
    else:
        s.text(25, 179, 'Пол и номер помещения насосной по АР не заданы', 3.5)
    notes = [
        'ЗС, ЗН, КО, PG: минимальный состав по СП 10, п.12.30 с изм.1. Позиции включены в спецификацию.',
        ('Материал обвязки: сталь ВГП. DN заданы; марки изделий и монтажная компоновка требуют подтверждения.' if pipework else
         'Материал путей: сталь ВГП. DN обвязки и марки арматуры уточнить; потери - по заданным расчётным путям.'),
        ('Спуск и испытательный отвод в пожарном режиме закрыты; испытательный режим и дренаж помещения не рассчитаны.' if pipework else
         'Спуск, удаление воздуха, испытательный отвод, дренаж, опоры и отметки проходок требуют компоновки.'),
        'Подключение пожарной техники и ёмкости: применимость и решения проверить отдельно; автоматически не добавлены.',
        'ШУ-В2: автоматический резерв 1+1, контроль давления и затопления; подробное задание автоматики в ПЗ.',
    ]
    if geometry and geometry['mismatched_sides']:
        notes.append('ПВ, ПД: переходы к патрубкам насоса. DN по каталогу, с.62; ' +
            ('потери в суммарном zeta ветви, без повторной надбавки.' if geometry['fittings_coverage']['included'] else
             'исполнение и учёт потерь требуют увязки.'))
    for i, note in enumerate(notes): s.text(25, 193+i*8, note, 3)
    s.text(25, 240, 'Предварительная схема. Паспорта и полный состав не подтверждены.', 3, width=190)
    return s.svg()


def build_pipework_sheet(project, *, page, total):
    from app.intake.studio_fire_pipework import from_model, connection_rows, ROLES
    review = validate_binding(project)
    model = project.fire_station_model_input
    pipework = from_model(model)
    if pipework is None: raise ValueError('Отдельная обвязка не задана')
    s = Sheet(project, 'В2. Обвязка и вспомогательные подключения', page, total)
    audit = review['pipework']
    s.text(25, 27, f"При Q={audit['q_m3h']:.3f} м3/ч: потери всасывания {audit['losses_m']['suction']:.3f} м; "
           f"напора {audit['losses_m']['discharge']:.3f} м.", 3.5)
    s.text(25, 36, 'Расчёт: один активный путь. Спецификация: две установленные ветви, общие коллекторы по одному.', 3)
    s.text(25, 49, 'Элемент / DN / исходное сопротивление', 3.5)
    s.text(250, 49, 'Подключения к коллекторам', 3.5)
    for i, e in enumerate(pipework.elements):
        y = 60+i*14
        s.line(25, y-7, 232, y-7, .25)
        s.text(25, y, f'{e.name}; DN{e.dn}', 3)
        value = f"A={e.value:g}; L={e.length_m:g} м" if e.method=='A_L' else f'{e.method}={e.value:g}'
        count = ROLES[e.id][1]
        quantity = (f'на каждую из {count} ветвей; состав по компоновке' if e.method=='zeta' else
                    f'установлено {count} ' + ('участок(а)' if e.method=='A_L' else 'шт.'))
        s.text(25, y+6, value + '; ' + quantity, 2.5)
    connections = connection_rows(model)
    if not connections: s.text(250, 61, 'Не заданы', 3.5)
    for i,c in enumerate(connections):
        y=61+i*26
        s.text(250, y, f"{c['id']} DN{c['dn']}: {c['name']}", 3, width=145)
        side='всасывающий' if c['at']=='suction_header' else 'напорный'
        s.text(250, y+12, f"Подключение: {side} коллектор", 2.5, width=145)
    from app.intake.studio_fire_fittings import coverage
    fittings = coverage(model, project.fire_pumps.model)
    s.text(25, 198, 'Kv и zeta заданы проектировщиком; это не паспорт изделия. ' +
           ('Переходы включены в zeta ветвей, отдельно не добавляются.' if fittings['included'] else
            'Состав суммарных местных сопротивлений требует увязки.'), 3)
    s.text(25, 207, 'Испытания, спуск воды и трассы до приёмников требуют отдельной увязки. Прямое подключение к канализации не подтверждено.', 3)
    s.text(25, 218, 'Входы и выходы обвязки: отдельная граница учёта. Повторной надбавки к потерям вводов и сети нет.', 3)
    if fittings['included']:
        a, b = (fittings['sides'][side] for side in ('suction','discharge'))
        s.text(25, 228, f"База zeta: всасывание dвн={a['reference_inner_mm']:g} мм; напор dвн={b['reference_inner_mm']:g} мм. "
               'Потери резервной ветви не суммируются.', 3)
    else:
        s.text(25, 228, 'Назначения подключений и основания решений приведены в расчёте общей насосной В2.', 3)
    s.text(25, 239, 'Предварительная геометрия; не монтажная деталировка.', 3, width=190)
    return s.svg()


def _node_code(model, node):
    return f"N{list(model['network']['node_elevations']).index(node) + 1}"


def _floor_layout(project, risers):
    floors = {int(k): float(v) for k, v in project.building.floor_elevations_m.items()
              if int(k) > 0 and isfinite(v)}
    if (set(floors) != set(range(1, project.building.floors_above + 1)) or
            any(floors[a] >= floors[b] for a, b in zip(sorted(floors), sorted(floors)[1:]))):
        return {}, {}, []
    selected = set(sorted(floors)[:2])
    terminals = {}
    for row in risers:
        below = [f for f in floors if floors[f] <= row['cabinet_elevation_m']]
        if not below:
            return {}, {}, []
        floor = max(below, key=floors.get)
        # A terminal above the highest known storey cannot silently extend it.
        if floor == max(floors) and len(floors) > 1:
            previous = sorted(floors)[-2]
            if row['cabinet_elevation_m'] >= floors[floor] + floors[floor]-floors[previous]:
                return {}, {}, []
        selected.add(floor); terminals[row['name']] = floor
    bands, breaks, y, previous = {}, [], 48., None
    for floor in sorted(selected, reverse=True):
        if previous is not None and previous-floor > 1:
            breaks.append((y, y+10, floor+1, previous-1)); y += 10
        bands[floor] = (y, y+30, floors[floor]); y += 30; previous = floor
    return bands, terminals, breaks


def build_riser_sheet(project, risers, *, page, total, graph_page):
    r = validate_binding(project)
    if not r: raise ValueError('Нужен принятый предварительный вариант В2')
    s = Sheet(project, 'В2. Характерные стояки и заданные ПК', page, total)
    s.text(25, 25, 'Фрагмент по расчётной модели. ПК на остальных этажах автоматически не добавлены.', 3.5)
    s.text(25, 33, 'Номера помещений, отсеков, нижние ПК и трассы по АР требуют дополнения.', 3.5)
    bands, terminals, breaks = _floor_layout(project, risers)
    schedule = {row['riser']:row for row in r['schedule']}
    bottom = max((b[1] for b in bands.values()), default=182) + 24
    break_bounds = {y for lo, hi, _, _ in breaks for y in (lo, hi)}
    for floor, (top, end, z) in bands.items():
        if end not in break_bounds:
            s.line(70, end, 398, end, .25, f'data-floor-boundary="{floor}"')
        s.parts.append(level_mark(f'v2-floor-{floor}', 62, end, z, f'{floor} этаж', reference_x=70, width=34))
        # Section limits stop at the same cutting line as the risers; tails
        # protrude 10 mm. No room subdivision is inferred from a hydraulic graph.
        for x in (70, 398):
            s.line(x, top, x, end, .25, 'data-section-limit="true"')
    if not bands:
        s.text(25, 47, 'Привязка ПК к этажам не определена; показаны только заданные отметки.', 3)
    # Each riser is a true source->terminal path; no fictional inter-riser link.
    for i, row in enumerate(risers):
        x = 112 + i*157
        entry = schedule[row['name']]
        if bands:
            top, end, z = bands[terminals[row['name']]]
            floors = project.building.floor_elevations_m
            higher = [v for f,v in floors.items() if f > terminals[row['name']] and v > z]
            storey_h = min(higher)-z if higher else None
            # With no upper level, place symbol schematically, never fabricate a height.
            offset = (row['cabinet_elevation_m']-z)/storey_h*30 if storey_h else 14
            py = end - max(8, min(20, offset))
        else:
            py = 83+i*35
        s.parts.append(f'<g data-riser="{escape(row["name"])}" data-at-node="{escape(row["at_node"])}" '
                       f'data-cabinet-elevation="{row["cabinet_elevation_m"]}">')
        cursor = py
        for lo, hi, _, _ in breaks:
            if lo > cursor:
                s.line(x, cursor, x, lo, attrs='data-riser-segment="true"'); cursor = hi
        s.line(x, cursor, x, bottom, attrs='data-riser-segment="true"')
        s.arrow(x, bottom-9, -90)
        s.line(x, py, x+52, py)
        s.component('ПК-'+row['name'], ugo.pk(x+38, py, r=3, w=.35, conn=()))
        s.text(x+4, py-9, f"{row['name']} DN{row['dn']}", 3.5)
        s.text(x+4, py+10, f"ПК {level_text(row['cabinet_elevation_m'])}; DN{entry['valve_dn']}", 3)
        if entry['aperture_mm']:
            s.line(x+46, py, x+56, py-7, .25); s.line(x+56, py-7, x+102, py-7, .25)
            s.arrow(x+46, py, 145)
            s.text(x+58, py-9, entry['id'], 3.5)
            s.text(x+58, py-2, f"Отверстие {entry['aperture_mm']:g} мм", 3)
        else:
            s.text(x+62, py+10, 'Без диафрагмы', 3)
        s.dot(x, bottom)
        code = _node_code(project.fire_station_model_input, row['at_node'])
        s.text(x-8, bottom+7, f"От {code} ({row['at_node']}) · лист {graph_page}", 3)
        s.text(x-8, bottom+14, f"DN{row['dn']}; L={row['height_m']:g} м", 3)
        s.parts.append('</g>')
    for lo, hi, first, last in breaks:
        for y in (lo, hi):
            s.parts.append(f'<path data-building-break="true" d="M60,{y} H224 l3,-3 v6 l3,-3 H408" '
                           'fill="none" stroke="black" stroke-width=".25"/>')
        word = f'{first}' if first == last else f'{first}-{last}'
        s.text(235, lo+7, f'Этажи {word} пропущены ({last-first+1})', 2.5)
    s.text(25, 237, 'Разрез условный; связи магистралей сохранены на листе расчётной сети.', 3, width=190)
    s.text(25, 251, 'Низший ПК здания и количество изделий по этажам не восстановлены из расчётных ПК.', 3, width=190)
    return s.svg()


def build_principle_sheets(project):
    """Prepend station + readable two-riser fragments to the exact graph/UGO."""
    validate_binding(project)
    rows = project.fire_station_model_input['network']['risers']
    groups = [rows[i:i+2] for i in range(0, len(rows), 2)]
    has_pipework = project.fire_station_model_input.get('schema_version') == 3
    total, graph_page = 3+len(groups)+int(has_pipework), 2+len(groups)+int(has_pipework)
    sheets = [(build_station_sheet(project, total=total, graph_page=graph_page), 'В2. Насосная')]
    if has_pipework:
        sheets.append((build_pipework_sheet(project, page=2, total=total), 'В2. Обвязка и подключения'))
    for i, group in enumerate(groups):
        sheets.append((build_riser_sheet(project, group, page=i+2+int(has_pipework), total=total, graph_page=graph_page),
                       f'В2. Стояки {i+1}'))
    return sheets, graph_page, total
