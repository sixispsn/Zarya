"""Generic common-station input/result annex; no hydraulic calculations here."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def frame_station_calculation(content, document, title):
    """Forms 3/6 for one title-less text document, after final pagination."""
    from dataclasses import replace
    from pypdf import PdfReader, PdfWriter
    from app.pz.text_document_frame import apply_frame
    reader, writer = PdfReader(BytesIO(content)), PdfWriter()
    writer.clone_document_from_reader(reader)
    if not reader.outline:
        writer.add_outline_item(title, 0)
    writer.add_metadata({"/Title": title, "/Author": "ЗАРЯ"})
    output = BytesIO()
    writer.write(output)
    return apply_frame(output.getvalue(), replace(document, sheet_title=title))


def render_station_input_report(path, project, result):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    from app.pz.drafting_font import DRAFTING_FONT_PATH

    station, pump = project.fire_station_input, project.fire_pumps
    if station is None or result is None:
        raise ValueError("Нужны явно заданная станция и результат её расчёта")
    pdfmetrics.registerFont(TTFont("StationInput", str(DRAFTING_FONT_PATH)))
    body = ParagraphStyle("station-input", fontName="StationInput", fontSize=11, leading=14, spaceAfter=7)
    title = ParagraphStyle("station-title", parent=body, fontSize=17, leading=21, spaceAfter=12)
    small = ParagraphStyle("station-small", parent=body, fontSize=10, leading=12, spaceAfter=5)
    def clean(value):
        return str(value).replace("—", "-").replace("–", "-").replace("−", "-").replace("³", "3").replace("²", "2")
    def p(text, style=body): return Paragraph(escape(clean(text)), style)
    def number(value, digits=3): return "не задано" if value is None else f"{value:.{digits}f}".replace(".", ",")
    def table(rows, widths):
        t = Table([[p(v, small) for v in row] for row in rows], colWidths=[w*mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0,0), (-1,-1), .4, colors.black),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#eef2f4")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
        return t
    hydraulic = result.hydraulic
    flow = hydraulic.dictating_scenario.total_flow_lps
    duty = hydraulic.pump_duty
    story = [p("В2. Вводы и пожарная насосная", title),
        p("Предварительный расчёт по явной модели. Раздельная В2, одна зона. "
          "Два выхода сети относятся к общему напорному коллектору, а не к двум самостоятельным насосам."),
        p(station.basis, small),
        table([("Параметр", "Значение"),
            ("Отметка оси насоса, м", number(result.pump_axis_m)),
            ("Расчётная подача, л/с / м3/ч", number(flow) + " / " + number(flow*3.6)),
            ("Минимальный напор до насоса, м", number(result.minimum_suction_head_m)),
            ("Требуется на выходе станции, м", number(hydraulic.required_head_at_source_m)),
            ("Требуемая добавка насоса, м", number(duty.required_head_m if duty else 0)),
            ("Максимальный статический напор до насоса, м", number(result.maximum_static_suction_head_m))], [121,53]),
        Spacer(1,3*mm), p("Каждый ввод - полный пожарный расход", title),
        table([("Ввод", "Отметка, м", "Hгар, м", "Потери, м", "До насоса, м"),
            *[(s.name, number(s.source_elevation_m), number(s.guaranteed_head_m), number(s.loss_m), number(s.suction_head_m)) for s in result.supplies]], [34,35,35,35,35]),
        p("Hдо насоса = Hгар + Zисточника - Zнасоса - сумма потерь ввода. "
          "Принята нижняя граница по обоим вводам. Распределение расхода между одновременно открытыми вводами не моделируется. " +
          ("В таблице потерь дополнительно учтена отдельная всасывающая обвязка. Добавка насоса включает также напорную обвязку." if result.pipework_audit else ''), small),
        PageBreak(), p("Исходные сопротивления вводов", title),
        table([("Путь / участок", "DN", "L, м", "Lэкв, м", "A"),
            *[(f"{s.name} / {i+1}", str(seg.diameter_mm), number(seg.length_m), number(seg.equiv_length_m), f"{seg.A:g}")
              for s in station.supplies for i,seg in enumerate(s.segments)]], [62,22,30,30,30]),
        p("Существующий расчёт: h = A · (L + Lэкв) · q2; q в л/с, длины в м. "
          "A в м/(м·(л/с)2). Lэкв задаётся явно и включает принятые местные сопротивления; "
          "повторной процентной надбавки нет. Нулевой Lэкв допустим только как явное исходное значение.", small),
        p("Сортамент: стальные ВГП обыкновенные трубы. Геометрия внутреннего диаметра "
          "берётся из существующего каталога; сопротивления A заданы в модели, а не угаданы по DN.", small)]
    from app.intake.studio_fire_location import from_model as location_from_model, description
    location = location_from_model(project.fire_station_model_input)
    if location:
        story += [p('Привязка насосной', title), p(description(location)),
            p(location['basis'], small),
            table([('Параметр', 'Относительная отметка, м'),
                ('Пол насосной', number(location['floor_elevation_m'])),
                ('Ось всасывающих патрубков', number(location['suction_nozzle_elevation_m'])),
                *[(f'Проходка {name}', number(z)) for name,z in location['inlet_elevations_m'].items()]], [121,53]),
            p('Отметка точки подключения наружного ввода не подменяет отметку проходки стены. '
              'Геометрия помещения, высота опор, проходы и сервисные зоны не определены этими отметками. '
              'Привязка сама по себе не меняет заданные длины и сопротивления расчёта.', small)]
    if result.pipework_audit:
        from app.intake.studio_fire_pipework import connection_rows
        pw = result.pipework_audit
        story += [PageBreak(), p('Отдельная обвязка при фиксированном расходе', title),
            p(pw['basis'], small),
            table([('Элемент', 'DN', 'Метод / значение', 'Потери, м'),
                *[(e['name'], str(e['dn']), f"{e['method']} / {e['value']:g}", number(e['loss_m']))
                  for e in pw['elements']]], [80,18,40,36]),
            p(f"Q={number(pw['q_m3h'])} м3/ч; всасывание {number(pw['losses_m']['suction'])} м; "
              f"напор {number(pw['losses_m']['discharge'])} м. "
              'Один активный путь; в исходных вводов и сети эти потери отсутствуют. Паспортная комплектность не подтверждена.', small)]
        from app.intake.studio_fire_fittings import coverage
        fittings = coverage(project.fire_station_model_input, pump.model)
        if fittings['included']:
            a, b = (fittings['sides'][side] for side in ('suction','discharge'))
            story += [p(fittings['note'], small),
                p(f"База суммарного zeta: всасывание {a['zeta']:g} при dвн={a['reference_inner_mm']:g} мм; "
                  f"напор {b['zeta']:g} при dвн={b['reference_inner_mm']:g} мм. " + fittings['basis'], small)]
        connections = connection_rows(project.fire_station_model_input)
        if connections:
            story += [p('Вспомогательные подключения (не пожарный расход)', body),
                table([('Позиция / DN', 'Присоединение', 'Назначение / основание'),
                    *[(f"{c['id']} / DN{c['dn']}",
                       ('Всасывающий' if c['at']=='suction_header' else 'Напорный') + ' коллектор',
                       f"{c['name']}. {c['destination']}. {c['basis']}") for c in connections]], [30,43,101])]
    if result.pipework_audit:
        story.append(PageBreak())
    story.append(p("Каталожный подбор насоса", title))
    if pump.pressure_review:
        from app.pz.fire_review_binding import validate_binding
        reviewed = validate_binding(project)
        story += [p(f"{pump.model}. {pump.count_note}"),
            p("Таблица выше — исходная потребность при фиксированных расходах, без диафрагм. "
              "Это не рабочая точка принятого варианта. Совместные режимы и отверстия проверены отдельно L06.", small),
            p(f"Контрольный режим {', '.join(reviewed['control_mode']['group'])}, "
              f"{reviewed['control_mode']['boundary']}: Q={number(pump.wp_q)} м3/ч; H={number(pump.wp_h)} м."),
            p(reviewed['note'], small)]
    elif duty and pump.model:
        story += [p(f"{pump.model}. {pump.count_note}"),
            p(f"Задание: Q = {number(pump.q_design_m3h)} м3/ч; H = {number(pump.h_design_m)} м. "
              f"Каталожный напор при этой подаче: {number(pump.wp_h)} м."),
            p("Резерв установлен, в нормальном режиме выключен. Подачи не складываются. "
              "Это допуск кандидата по Q/H, не найденное пересечение с характеристикой сети.", small)]
    else:
        story += [p("Повышение напора в проверенном сценарии не требуется." if not duty else
                    "Каталог не дал кандидата. Требуемые Q/H не уменьшены под имеющиеся насосы.")]
    from app.data.fire_pump_geometry import connection_review
    geometry = connection_review(project.fire_station_model_input, pump.model)
    if geometry:
        story += [p('Габариты и присоединения выбранного кандидата', title), p(geometry['note'], small),
            p('Каталожные размеры стандартного насоса: ' +
              '; '.join(f'{k}={v:g}' for k,v in geometry['dimensions_mm'].items()) + ' мм. '
              f"Ось патрубков от основания {geometry['nozzle_axis_from_base_mm']:g} мм; масса CDM {geometry['mass_kg']:g} кг. "
              'Это не габарит и не масса насосной станции 1+1.', small)]
    for note in (() if pump.pressure_review else station.review_notes):
        story.append(p(note, small))
    story += [p("Область результата", title),
        p("Для принятого варианта используйте приложение «Диафрагмы и отключения» и лист узлов той же версии." if pump.pressure_review else
          "Отдельный гидравлический лист содержит участки сети после насоса. В графике подбора "
          "показана кривая одного насоса и расчётное задание. Диафрагмы и результаты L06 из другого здания не применяются.", small),
        p("ГОСТ Р 21.619-2023, п. 5.1.8: сведения о напорах и насосном оборудовании. "
          "Проверки оборудования и расстановка ПК остаются открытыми. Приложение не заменяет ПЗ, "
          "баланс формы 2 и графическую часть по п. 5.2.2.", small)]
    content = BytesIO()
    SimpleDocTemplate(content, pagesize=A4, leftMargin=25*mm, rightMargin=10*mm,
        topMargin=12*mm, bottomMargin=65*mm, title="В2 - вводы и пожарная насосная").build(story)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(frame_station_calculation(content.getvalue(), project.document,
                                                   "В2. Вводы и насосная. Расчёт"))
    return str(path)
