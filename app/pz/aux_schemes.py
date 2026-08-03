"""Дополнительные принципиальные схемы ИОС2 без вымышленной аксонометрии."""
from html import escape

from app.pz.rules import decide_fire_network


def _text(x, y, value, size=22, anchor="middle", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-family="Arial" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')


def _box(x, y, w, h, label, *, stroke="#8fa3b8"):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
            f'fill="white" stroke="{stroke}" stroke-width="3"/>'
            + _text(x + w / 2, y + h / 2 + 7, label, 19))


def _box_lines(x, y, w, h, lines, *, stroke="#8fa3b8"):
    content = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
        f'fill="white" stroke="{stroke}" stroke-width="3"/>'
    ]
    first_y = y + h / 2 - (len(lines) - 1) * 13
    for index, line in enumerate(lines):
        content.append(_text(x + w / 2, first_y + index * 28 + 6, line, 18))
    return "".join(content)


def _line(x1, y1, x2, y2, *, color="#111827", width=4):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{width}" marker-end="url(#a)"/>')


def _technical_frame(project, title):
    """Рамка и основная надпись 185×55 мм для листа А3."""
    doc = project.document
    px = 1600 / 420
    fx0, fy0 = 20 * px, 5 * px
    fx1, fy1 = 1600 - 5 * px, 1131 - 5 * px

    def mmx(value):
        return fx1 - (185 - value) * px

    def mmy(value):
        return fy1 - (55 - value) * px

    def line(x1, y1, x2, y2, width=1.4):
        return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#111827" stroke-width="{width}"/>')

    g = [
        f'<rect x="{fx0:.1f}" y="{fy0:.1f}" width="{fx1-fx0:.1f}" height="{fy1-fy0:.1f}" fill="none" stroke="#111827" stroke-width="3"/>',
        f'<rect x="{mmx(0):.1f}" y="{mmy(0):.1f}" width="{185*px:.1f}" height="{55*px:.1f}" fill="white" stroke="#111827" stroke-width="3"/>',
        line(mmx(65), mmy(0), mmx(65), mmy(55), 2),
    ]
    for value in (7, 17, 25, 37, 53):
        g.append(line(mmx(value), mmy(0), mmx(value), mmy(25)))
    for value in (17, 37, 53):
        g.append(line(mmx(value), mmy(25), mmx(value), mmy(55)))
    g += [
        line(mmx(135), mmy(25), mmx(135), mmy(55), 1.8),
        line(mmx(150), mmy(25), mmx(150), mmy(40)),
        line(mmx(165), mmy(25), mmx(165), mmy(40)),
    ]
    for value in range(5, 55, 5):
        g.append(line(mmx(0), mmy(value), mmx(65), mmy(value)))
    g += [
        line(mmx(65), mmy(10), mmx(185), mmy(10)),
        line(mmx(65), mmy(25), mmx(185), mmy(25)),
        line(mmx(135), mmy(30), mmx(185), mmy(30)),
        line(mmx(65), mmy(40), mmx(185), mmy(40)),
    ]
    for label, start, end in (
        ("Изм.", 0, 7), ("Кол.уч.", 7, 17), ("Лист", 17, 25),
        ("№ док.", 25, 37), ("Подп.", 37, 53), ("Дата", 53, 65),
    ):
        g.append(_text(mmx((start + end) / 2), mmy(25) - 5, label, 9))
    for label, name, row in (
        ("Разраб.", doc.developer_name, 30),
        ("Проверил", doc.inspector_name, 35),
        ("Нач. отдела", doc.dept_head_name, 40),
        ("ГИП", doc.gip_name, 45),
        ("Н. контр.", doc.norm_control_name, 55),
    ):
        g.append(_text(mmx(1) + 2, mmy(row) - 5, label, 9, anchor="start"))
        if name:
            g.append(_text(mmx(27), mmy(row) - 5, name, 9))
    g += [
        _text(mmx(125), mmy(8), doc.cipher or "", 19),
        _text(mmx(125), mmy(19), doc.object_name or "", 11),
        _text(mmx(100), mmy(34.5), doc.object_part or "", 13),
        _text(mmx(142.5), mmy(30) - 5, "Стадия", 8),
        _text(mmx(157.5), mmy(30) - 5, "Лист", 8),
        _text(mmx(175), mmy(30) - 5, "Листов", 8),
        _text(mmx(142.5), mmy(37), doc.stage_label, 12),
        _text(mmx(157.5), mmy(37), "1", 12),
        _text(mmx(175), mmy(37), "1", 12),
        _text(mmx(125), mmy(48), title, 12),
        _text(mmx(125), mmy(53), doc.organization or "", 10),
    ]
    return "".join(g)


def _sheet(project, title, body, note):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 1600 1131">
<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#111827"/></marker></defs>
<rect width="1600" height="1131" fill="white"/>
{_text(800, 88, title, 30, weight="bold")}{body}
{_text(85, 880, note, 16, anchor="start")}{_technical_frame(project, title)}
</svg>'''


def build_metering_scheme_svg(project):
    decision = decide_fire_network(project.fire, project.materials, project.normative)
    topology = decision.topology if decision else "separate"
    n = max(int(project.source.inputs_count or 1), 1)
    meter = next((r for r in project.meters.rows if "ввод" in r.label.lower()
                  or "хвс" in r.label.lower()), None)
    dn = f"DN{meter.dn}" if meter else "DN уточнить"
    g = []
    for index in range(n):
        y = 210 + index * 230
        g += [_box(70, y, 190, 64, f"Ввод {index+1} · 100% Q"),
              _line(260, y+32, 345, y+32)]
        if topology in ("pre_meter_branch", "separate") and project.fire.required:
            g += [_line(305, y+32, 305, y-70),
                  _line(305, y-70, 335, y-70),
                  _box(335, y-102, 300, 64,
                       "В2 · задвижка с электроприводом" if project.fire.branch_electric_valves else "В2 · отдельное ответвление",
                       stroke="#ef4444")]
        g += [_box(345, y, 150, 64, "Фильтр"), _line(495, y+32, 550, y+32),
              _box(550, y, 210, 64, f"Счётчик В1 {dn}"), _line(760, y+32, 850, y+32),
              _box(850, y, 230, 64, "Коллектор В1")]
        if topology == "combined" and project.fire.required:
            g += [_line(1080, y+32, 1170, y+32),
                  _box(1170, y, 300, 64, "Объединённая сеть В1+В2", stroke="#ef4444")]
        if project.meters.has_bypass:
            g += [f'<path d="M520 {y+32} V{y+115} H790 V{y+32}" fill="none" stroke="#ef4444" stroke-width="4"/>',
                  _text(655, y+108, "Обводная линия · электроклапан", 16)]
    verdict = (
        "ВУ без обводных линий: два ввода; пожарный расход проходит по отдельным ответвлениям."
        if n > 1 and topology == "pre_meter_branch" and not project.meters.has_bypass
        else "Состав обводной линии принят по результату проверок водомера."
    )
    return _sheet(project, "Принципиальная схема узлов учёта и вводов", "".join(g),
                  verdict + " СП 30.13330.2020: пп. 8.23, 12.10–12.12.")


def build_pump_zone_scheme_svg(project):
    p = project.pumps
    g = [_box(70, 300, 230, 70, "Вводной коллектор"), _line(300, 335, 400, 335)]
    pump_lines = (
        [f"НС В1 · {p.model or 'модель не выбрана'}",
         f"Q={p.wp_q or p.q_m3h:.1f} м³/ч · H={p.wp_h or p.head_m:.1f} м"]
        if p.required else ["НС В1 не требуется"]
    )
    g += [_box_lines(400, 285, 420, 100, pump_lines, stroke="#2563eb"),
          _line(820, 335, 930, 335)]
    zones = max(int(project.building.zones or 1), 1)
    regs = list(getattr(getattr(project, "v1_hydraulic_result", None), "zone_regulators", []) or [])
    for index in range(zones):
        y = 170 + index * 160
        regulator = regs[index] if index < len(regs) else None
        if regulator and regulator.required and regulator.topology_feasible:
            control = f"РД-В1-{index+1}; Hвых={regulator.outlet_setpoint_m:.1f} м"
        elif zones > 1:
            control = "РД/отдельная НС · настройка после топологии"
        else:
            control = "без отдельного регулятора зоны"
        g += [_line(930, 335, 1030, y+40),
              _box_lines(1030, y, 430, 80, [f"Зона {index+1}", control])]
    if getattr(project.building.hws_type, "value", project.building.hws_type) != "none":
        heater = "Водонагреватель / теплообменник"
        if not project.source.hws_heater_in_scope:
            heater += " · принадлежность уточнить"
        g += [_line(650, 375, 650, 650), _box(500, 650, 300, 75, heater, stroke="#f59e0b"),
              _line(800, 688, 1030, 688), _box(1030, 650, 260, 75, "Т3 · подача ГВС"),
              f'<path d="M1290 688 H1450 V820 H650 V725" fill="none" stroke="#f59e0b" stroke-width="4" marker-end="url(#a)"/>',
              _text(1090, 812, "Т4 · циркуляция; Q и настройки после аксонометрии Р", 17)]
    paths = getattr(project, "head_paths", None)
    note = "Рабочая точка НС — по диктующей трассе."
    if paths:
        note += " " + "; ".join(
            f"{x.code}: Hтр={x.head.h_required_m:.2f} м" if x.head.h_required_m is not None else f"{x.code}: данных недостаточно"
            for x in paths.paths
        )
    return _sheet(project, "Принципиальная схема насосной, зон В1 и ГВС", "".join(g), note)
