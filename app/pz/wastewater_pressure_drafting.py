"""Vector A1 sheets for a confirmed internal pressure-sewer system."""
from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from app.pz.project import Project, SewerElementSpec
from app.pz.wastewater_building_drafting import (
    _FRAME_BOTTOM,
    _FRAME_LEFT,
    _FRAME_RIGHT,
    _FRAME_TOP,
    _title_block_svg,
)
from app.pz.wastewater_drafting import BLACK, FONT, GRAY
from app.pz.wastewater_pressure_project_inputs import (
    WastewaterPressureProjectInputs,
    resolve_wastewater_pressure_project_inputs,
)
from app.pz.wastewater_ugo import render_ugo


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _short(value: str, limit: int = 24) -> str:
    clean = " ".join((value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _svg_page(body: str, project: Project, *, page: int, title: str) -> str:
    return "".join((
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        body,
        _title_block_svg(
            project.document,
            sheet_no=page,
            sheet_total=2,
            title=title,
            system_label=f"{project.sewage.pump_system}н",
        ),
        '</svg>',
    ))


def _text(x: float, y: float, value: str, size: float = 18, *, bold: bool = False,
          anchor: str = "start", color: str = BLACK) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" '
        f'font-size="{size:.1f}" text-anchor="{anchor}" '
        f'font-weight="{"bold" if bold else "normal"}" fill="{color}">'
        f'{escape(value)}</text>'
    )


def _element_svg(element: SewerElementSpec, x: float, y: float, label_y: float) -> str:
    rotation = 90.0 if element.kind == "pump" else 0.0
    return "".join((
        f'<g data-pressure-element="{escape(element.element_id)}" '
        f'data-pressure-kind="{escape(element.kind)}">',
        render_ugo(element.kind, x, y, scale=1.25, rotation=rotation),
        _text(x, label_y, element.element_id, 15, bold=True, anchor="middle"),
        _text(
            x,
            label_y + 21,
            f"{_short(element.type_mark or element.name)}; {element.quantity} шт.",
            12,
            anchor="middle",
        ),
        '</g>',
    ))


def build_wastewater_pressure_scheme_svg(
    project: Project,
    inputs: WastewaterPressureProjectInputs,
) -> str:
    sewage = project.sewage
    system = inputs.system.replace("K", "К")
    y = 845.0
    rows = [
        _text(170, 165, f"Принципиальная схема напорной канализации {system}н", 31, bold=True),
        _text(170, 205, "Внутренняя сеть здания · только подтверждённые участки и оборудование", 17, color=GRAY),
        f'<g data-pressure-source="{escape(inputs.mode)}">',
    ]
    if inputs.mode == "internal_station" and inputs.sump_element is not None:
        rows.append(_element_svg(inputs.sump_element, 310, y, y + 96))
        rows.append(_text(310, y - 72, "приёмная часть", 15, anchor="middle"))
    else:
        rows.extend((
            f'<rect x="190" y="{y-80:.1f}" width="230" height="160" '
            f'fill="white" stroke="{BLACK}" stroke-width="2"/>',
            _text(305, y - 20, "Подключённые приборы", 16, bold=True, anchor="middle"),
            _text(
                305,
                y + 15,
                f"{sewage.pump_fixture_count} шт.; состав по заданию",
                15,
                anchor="middle",
            ),
            _text(305, y + 45, "без выдуманных типов приборов", 13, anchor="middle", color=GRAY),
        ))
    rows.append('</g>')
    rows.append(f'<line x1="420" y1="{y}" x2="505" y2="{y}" stroke="{BLACK}" stroke-width="4"/>')

    fixed_elements = (
        (inputs.pump_element, 545.0, y + 82),
        (inputs.check_valve_element, 670.0, y + 82),
        (inputs.isolation_valve_element, 795.0, y + 82),
    )
    for element, x, label_y in fixed_elements:
        if element is not None:
            rows.append(_element_svg(element, x, y, label_y))
    rows.append(f'<line x1="505" y1="{y}" x2="850" y2="{y}" stroke="{BLACK}" stroke-width="4"/>')

    start_x, end_x = 850.0, 2380.0
    count = max(1, len(inputs.pressure_pipes))
    width = (end_x - start_x) / count
    for index, pipe in enumerate(inputs.pressure_pipes):
        x1 = start_x + index * width
        x2 = start_x + (index + 1) * width
        label = f"{system}н ⌀{pipe.nominal_diameter_mm} · {pipe.section_id}"
        rows.extend((
            f'<g data-pressure-section="{escape(pipe.section_id)}">',
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" '
            f'stroke="{BLACK}" stroke-width="4"/>',
            f'<rect x="{(x1+x2)/2-78:.1f}" y="{y-14:.1f}" width="156" height="28" fill="white"/>',
            _text((x1 + x2) / 2, y + 5, label, 13, anchor="middle"),
            _text(
                (x1 + x2) / 2,
                y - 38,
                f"Lр={_fmt(pipe.calculation_length_m)} м; PN {_fmt(pipe.pressure_class_bar, 1)}",
                12,
                anchor="middle",
            ),
            f'<path d="M{(x1+x2)/2-12:.1f},{y+28:.1f} L{(x1+x2)/2+12:.1f},{y:.1f} '
            f'L{(x1+x2)/2-12:.1f},{y-28:.1f}" fill="none" stroke="{BLACK}" stroke-width="2"/>',
            '</g>',
        ))

    terminal_x = 2450.0
    rows.append(f'<line x1="{end_x}" y1="{y}" x2="{terminal_x}" y2="{y}" stroke="{BLACK}" stroke-width="4"/>')
    if inputs.pressure_break_loop_element is not None:
        rows.append(_element_svg(inputs.pressure_break_loop_element, terminal_x, y, y + 90))
    else:
        rows.append(f'<circle cx="{terminal_x}" cy="{y}" r="6" fill="white" stroke="{BLACK}" stroke-width="3"/>')
    rows.extend((
        f'<line x1="{terminal_x+35:.1f}" y1="{y}" x2="2630" y2="{y}" stroke="{BLACK}" stroke-width="4"/>',
        f'<path d="M2605,{y-12:.1f} L2630,{y:.1f} L2605,{y+12:.1f} Z" fill="{BLACK}"/>',
        _text(2630, y - 34, sewage.pump_discharge_node, 15, bold=True, anchor="end"),
        _text(2630, y + 45, "в подтверждённую самотечную сеть", 14, anchor="end"),
    ))
    if inputs.receiving_gravity_pipe is not None:
        rows.append(_text(
            2630,
            y + 68,
            f"{system} ⌀{inputs.receiving_gravity_pipe.nominal_diameter_mm} · "
            f"{inputs.receiving_gravity_pipe.section_id}",
            13,
            anchor="end",
        ))

    rows.extend((
        f'<rect x="170" y="1160" width="2460" height="330" fill="none" stroke="{BLACK}" stroke-width="2"/>',
        _text(195, 1200, "ДАННЫЕ И УКАЗАНИЯ", 19, bold=True),
        _text(195, 1240, f"Режим: {"малогабаритная установка" if inputs.mode == "local_fixture_unit" else "внутренняя насосная станция"}.", 15),
        _text(195, 1272, f"Насос: {sewage.pump_model}; {sewage.pump_working_units} раб. + {sewage.pump_reserve_units} рез.; P={_fmt(sewage.pump_power_kw)} кВт.", 15),
        _text(195, 1304, f"Рабочая точка: Q={_fmt(sewage.pump_q_m3h)} м³/ч; H={_fmt(sewage.pump_head_m)} м.", 15),
        _text(195, 1336, f"Размещение: {sewage.pump_location}.", 15),
        _text(195, 1368, f"Автоматизация: {sewage.pump_automation_note}", 14),
        _text(195, 1400, f"Аварийный режим: {sewage.pump_emergency_note}", 14),
        _text(195, 1452, "Положение элементов на листе принципиальное; монтажные координаты принимаются по стадии Р.", 13, color=GRAY),
    ))
    return _svg_page("".join(rows), project, page=1, title=f"Принципиальная схема напорной канализации {system}н")


def build_wastewater_pressure_curve_svg(
    project: Project,
    inputs: WastewaterPressureProjectInputs,
) -> str:
    sewage = project.sewage
    curve = [(float(q), float(h)) for q, h in sewage.pump_curve]
    wp = inputs.working_point
    q_max = max(q for q, _ in curve) * 1.08
    system_head_at_q_max = (
        (sewage.pump_static_head_m or 0)
        + (inputs.system_curve_k or 0) * q_max ** 2
    )
    h_max = max(
        max(h for _, h in curve),
        sewage.pump_static_head_m or 0,
        system_head_at_q_max,
    ) * 1.08
    gx, gy, gw, gh = 250.0, 320.0, 1420.0, 1020.0

    def point(q: float, h: float) -> tuple[float, float]:
        return gx + q / q_max * gw, gy + gh - h / h_max * gh

    pump_points = " ".join(f"{point(q, h)[0]:.1f},{point(q, h)[1]:.1f}" for q, h in curve)
    system_points = []
    for index in range(81):
        q = q_max * index / 80.0
        h = (sewage.pump_static_head_m or 0) + (inputs.system_curve_k or 0) * q ** 2
        system_points.append(f"{point(q, h)[0]:.1f},{point(q, h)[1]:.1f}")
    rows = [
        _text(170, 165, "Рабочая точка канализационной насосной установки", 31, bold=True),
        _text(170, 205, "Паспортная Q-H характеристика и подтверждённая характеристика системы", 17, color=GRAY),
        f'<g data-pump-curve="confirmed" data-system-curve="confirmed">',
        f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" fill="white" stroke="{BLACK}" stroke-width="2"/>',
    ]
    for index in range(1, 6):
        x = gx + gw * index / 5
        y = gy + gh * index / 5
        rows.extend((
            f'<line x1="{x:.1f}" y1="{gy}" x2="{x:.1f}" y2="{gy+gh}" stroke="#ddd" stroke-width="1"/>',
            f'<line x1="{gx}" y1="{y:.1f}" x2="{gx+gw}" y2="{y:.1f}" stroke="#ddd" stroke-width="1"/>',
            _text(x, gy + gh + 28, _fmt(q_max * index / 5), 13, anchor="middle"),
            _text(gx - 18, gy + gh - gh * index / 5 + 5, _fmt(h_max * index / 5), 13, anchor="end"),
        ))
    rows.extend((
        f'<polyline points="{pump_points}" fill="none" stroke="#0057b8" stroke-width="6"/>',
        f'<polyline points="{" ".join(system_points)}" fill="none" stroke="#d7263d" stroke-width="6"/>',
        _text(gx + gw, gy + gh + 62, "Q, м³/ч", 16, bold=True, anchor="end"),
        _text(gx - 5, gy - 20, "H, м", 16, bold=True),
        '</g>',
    ))
    if wp is not None:
        wx, wy = point(wp.q_m3h, wp.pump_head_m)
        rows.extend((
            f'<g data-working-point="Q={wp.q_m3h:.6f};H={wp.pump_head_m:.6f}">',
            f'<line x1="{wx:.1f}" y1="{gy+gh}" x2="{wx:.1f}" y2="{wy:.1f}" stroke="#777" stroke-dasharray="10 7" stroke-width="2"/>',
            f'<line x1="{gx}" y1="{wy:.1f}" x2="{wx:.1f}" y2="{wy:.1f}" stroke="#777" stroke-dasharray="10 7" stroke-width="2"/>',
            f'<circle cx="{wx:.1f}" cy="{wy:.1f}" r="11" fill="white" stroke="{BLACK}" stroke-width="4"/>',
            _text(wx + 18, wy - 18, f"РТ: Q={_fmt(wp.q_m3h)}; H={_fmt(wp.pump_head_m)}", 15, bold=True),
            '</g>',
        ))
    rows.extend((
        f'<line x1="1760" y1="365" x2="1840" y2="365" stroke="#0057b8" stroke-width="6"/>',
        _text(1860, 371, f"Q-H: {sewage.pump_model}", 15),
        f'<line x1="1760" y1="410" x2="1840" y2="410" stroke="#d7263d" stroke-width="6"/>',
        _text(1860, 416, "Hсист = Hст + k·Q²", 15),
        f'<rect x="1745" y="480" width="885" height="700" fill="none" stroke="{BLACK}" stroke-width="2"/>',
        _text(1770, 522, "РАСЧЁТНАЯ ТАБЛИЦА", 19, bold=True),
    ))
    table_rows = (
        ("Расчётный расход Q", f"{_fmt(sewage.pump_q_m3h)} м³/ч"),
        ("Статическая составляющая Hст", f"{_fmt(sewage.pump_static_head_m)} м"),
        ("Динамические потери при Q", f"{_fmt(sewage.pump_dynamic_loss_m)} м"),
        ("Требуемый напор", f"{_fmt((sewage.pump_static_head_m or 0) + (sewage.pump_dynamic_loss_m or 0))} м"),
        ("Пересечение кривых", f"Q={_fmt(wp.q_m3h if wp else None)}; H={_fmt(wp.pump_head_m if wp else None)}"),
        ("Источник гидравлики", sewage.pump_hydraulic_source),
        ("Источник Q-H", sewage.pump_curve_source),
        ("Резервирование", sewage.pump_reserve_note),
        ("Категория питания", sewage.pump_power_category),
    )
    for index, (label, value) in enumerate(table_rows):
        row_y = 565 + index * 61
        rows.extend((
            f'<line x1="1745" y1="{row_y+20}" x2="2630" y2="{row_y+20}" stroke="#888" stroke-width="1"/>',
            _text(1770, row_y, label, 14),
            _text(2605, row_y, value, 14, bold=index < 5, anchor="end"),
        ))
    rows.extend((
        _text(250, 1395, "Проверка выполняется по введённой паспортной кривой; каталог водопроводных насосов не используется.", 14, color=GRAY),
        _text(250, 1430, "Кривая системы построена только из введённых Hст и динамических потерь в расчётной точке.", 14, color=GRAY),
    ))
    return _svg_page("".join(rows), project, page=2, title="Рабочая точка канализационной насосной установки")


def build_wastewater_pressure_svgs(
    project: Project,
    inputs: WastewaterPressureProjectInputs,
) -> tuple[str, str]:
    if not inputs.complete:
        raise ValueError("pressure sewer inputs are incomplete")
    return (
        build_wastewater_pressure_scheme_svg(project, inputs),
        build_wastewater_pressure_curve_svg(project, inputs),
    )


def audit_wastewater_pressure_svgs(
    inputs: WastewaterPressureProjectInputs,
    svgs: tuple[str, ...],
) -> tuple[str, ...]:
    findings: list[str] = []
    if len(svgs) != 2:
        findings.append("Напорный комплект должен состоять из двух листов.")
        return tuple(findings)
    roots = [ElementTree.fromstring(svg) for svg in svgs]
    section_ids = {
        row.get("data-pressure-section")
        for root in roots
        for row in root.iter()
        if row.get("data-pressure-section")
    }
    for pipe in inputs.pressure_pipes:
        if pipe.section_id not in section_ids:
            findings.append(f"Не отрисован напорный участок {pipe.section_id}.")
    element_ids = {
        row.get("data-pressure-element")
        for root in roots
        for row in root.iter()
        if row.get("data-pressure-element")
    }
    for element in (
        inputs.pump_element,
        inputs.check_valve_element,
        inputs.isolation_valve_element,
        inputs.sump_element,
        inputs.pressure_break_loop_element,
    ):
        if element is not None and element.element_id not in element_ids:
            findings.append(f"Не отрисован элемент {element.element_id}.")
    if not any(row.get("data-working-point") for row in roots[1].iter()):
        findings.append("На расчётном листе не отмечена рабочая точка.")
    if not all(any(row.get("data-title-block") == "form-3" for row in root.iter()) for root in roots):
        findings.append("Не на каждом листе есть основная надпись.")
    return tuple(findings)


def generate_wastewater_pressure_pdf_from_project(
    output_path: str,
    project: Project,
) -> str:
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    inputs = resolve_wastewater_pressure_project_inputs(project)
    svgs = build_wastewater_pressure_svgs(project, inputs)
    findings = audit_wastewater_pressure_svgs(inputs, svgs)
    if findings:
        raise ValueError("pressure sewer graphic audit failed: " + "; ".join(findings))
    writer = PdfWriter()
    for svg in svgs:
        page_pdf = BytesIO()
        cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=page_pdf)
        page_pdf.seek(0)
        writer.append(PdfReader(page_pdf))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return str(path)


__all__ = [
    "audit_wastewater_pressure_svgs",
    "build_wastewater_pressure_curve_svg",
    "build_wastewater_pressure_scheme_svg",
    "build_wastewater_pressure_svgs",
    "generate_wastewater_pressure_pdf_from_project",
]
