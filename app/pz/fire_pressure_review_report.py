"""Object-specific L06 diagnostics; never certifies a pump or fire design."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def render_pressure_review(path, project, review):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    from app.pz.drafting_font import DRAFTING_FONT_PATH
    from app.pz.fire_station_input_report import frame_station_calculation
    from app.calc.fire_hydraulics import MPA_TO_M
    pdfmetrics.registerFont(TTFont("PressureReview", str(DRAFTING_FONT_PATH)))
    body = ParagraphStyle("body", fontName="PressureReview", fontSize=11, leading=14, spaceAfter=7)
    heading = ParagraphStyle("heading", parent=body, fontSize=17, leading=21, spaceAfter=11)
    small = ParagraphStyle("small", parent=body, fontSize=9.5, leading=12, spaceAfter=4)
    def p(text, style=body):
        text = str(text)
        for a, b in (("—", "-"), ("–", "-"), ("−", "-"), ("³", "3")):
            text = text.replace(a, b)
        return Paragraph(escape(text), style)
    def n(v): return "нет данных" if v is None else f"{v:.3f}".replace(".", ",")
    def table(rows, widths):
        out = Table([[p(v, small) for v in row] for row in rows], colWidths=[w*mm for w in widths], repeatRows=1)
        out.setStyle(TableStyle([("GRID", (0,0), (-1,-1), .35, colors.black),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#edf1f3")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
        return out
    r = review
    if r.get("adoption", {}).get("state") == "preliminary":
        from app.pz.fire_review_binding import validate_binding
        if validate_binding(project) != r:
            raise ValueError("Расчётное приложение не совпадает с принятым вариантом В2")
    story = [p("В2. Диафрагмы и отключения", heading), p(r["note"])]
    if r.get("error"):
        story += [p("Расчёт не выполнен: " + r["error"])]
    else:
        pump = r["pump"]
        trace = [p("Границы источников и нормативная трассировка", heading),
            p("Каждый ввод отдельно: Hгар и, если задан, Hmax с его сопротивлением. "
              "Дополнительная верхняя огибающая - максимальный Hmax без потерь наружных подводов, "
              "не точный расчёт двух параллельных вводов. " +
              ("Обвязка считается отдельно от вводов и сети при текущем расходе каждого режима; " if r.get('pipework') else
               "Обвязка уже включена в явные пути модели; ") +
              "добавочная процентная надбавка не используется.", small),
            p("СП 10.13130.2020 с предоставленным изменением 1: пп. 7.6, 7.14 и таблица 7.3 - "
              "совместная работа и минимумы; п. 7.5 - снижение избыточного давления; п. 6.2.20 - "
              "статика самостоятельного ВПВ; пп. 6.1.12, 13.1, 12.27 - секционирование и подводы. "
              "Границы реальных ремонтных секций и покрытие помещений этим расчётом не подтверждены.", small),
            p(f"Кривая: {pump['curve_source']}, PDF с. {pump['curve_pdf_page']}; "
              f"SHA-256 {pump['curve_sha256']}. Характеристика ПК - справочная ВНИИПО 2010, "
              "с. 109 и 385; не паспорт конкретного ствола. Номограмма - приложение Б СП10, "
              "область DN50. Оформление расчётного приложения - ГОСТ Р 21.619-2023, п. 5.1.8.", small),
            p("SHA-256 исходной модели: " + r["input_sha256"], small)]
        label = lambda case: "Целая сеть" if case == "intact" else case
        adopted = r.get("adoption", {}).get("state") == "preliminary"
        story += [p(("Принятый предварительный насос: " if adopted else "Проверяемый насос: ") + pump["pump_model"] +
                    ". Один рабочий + один резервный. " +
                    ("Единый вариант для ПЗ, листа узлов и спецификации." if adopted else
                     "Проверка варианта не заменяет автоматически насос в ПЗ и спецификации.")),
            p(r["basis"], small),
            p(f"Рассчитано {r['solved_count']} из {r['scenario_count']} режимов. "
              f"Минимумы обеспечены в {r['minimum_pass_count']}. "
              "Количество относится только к явно заданной матрице, не ко всем пожарам здания."),
            table([("Контроль", "Результат модели"),
                ("Минимумы расхода и давления", "Проходят" if r["all_model_minima_met"] else "Есть дефицит / нерассчитанные режимы"),
                ("Давление при расходе <= 0,45 МПа", "Проходит" if r["all_model_dynamic_limits_met"] else "Есть превышение / нет решения"),
                ("Статика <= 0,9 МПа", "Проходит для заданных ПК" if r["all_model_static_limits_met"] else "Превышение / недостаточно исходных"),
                ("Допуск к выпуску", "Не открыт; паспортные и проектные проверки не завершены")], [91,83]),
            Spacer(1,3*mm), p("Режимы и чувствительность", heading)]
        cases = [("Отключение", "Решено / всего", "Минимумы", "Динамика")]
        for case in r["cases"]:
            rows = [row for row in r["rows"] if row["case"] == case["id"]]
            cases.append((label(case["id"]), f"{sum(bool(x['result'] and x['result']['operating']) for x in rows)} / {len(rows)}",
                f"{sum(x['minimum_ok'] for x in rows)} / {len(rows)}", f"{sum(x['dynamic_ok'] for x in rows)} / {len(rows)}"))
        story += [table(cases, [66,40,34,34])]
        if r.get('pipework'):
            pw = r['pipework']
            story.append(p(f"Обвязка: Rвс={n(pw['resistances_m_per_lps2']['suction'])}, "
                f"Rнап={n(pw['resistances_m_per_lps2']['discharge'])} м/(л/с)2. "
                "Один активный путь; установленный резерв не складывается. "
                "При Q=0 потери обвязки равны нулю и статику не снижают.", small))
        solved = [(row, c) for row in r["rows"] if row["result"] and row["result"]["operating"]
                  for c in row["result"]["operating"]["cabinets"]]
        if solved:
            row, cab = min(solved, key=lambda pair: pair[1]["outlet_head_m"]-pair[1]["minimum_head_m"])
            story.append(p(f"Наименьший запас по давлению: {cab['cabinet_id']}, {label(row['case'])}, "
                f"{row['boundary']}, шкала {n(row['axis_offset_px'])} px. "
                f"p={n(cab['outlet_head_m']/MPA_TO_M)} МПа при минимуме {n(cab['minimum_head_m']/MPA_TO_M)}; "
                f"q={n(cab['flow_lps'])} л/с при минимуме {n(cab['minimum_flow_lps'])}.", small))
        story += [
            p("Учтены все выбранные смещения шкалы. ±2 px - чувствительность оцифровки, "
              "не допуск изготовления диафрагмы. Неизвестные решения не засчитаны как успешные.", small),
            PageBreak(), p("Диафрагмы и заданные отключения", heading),
            table([("Расчётный ПК / стояк", "Отверстие, мм", "Отметка ПК, м"),
                *[(s["name"], "без диафрагмы" if r["apertures_mm"][s["name"]] is None else n(r["apertures_mm"][s["name"]]),
                   n(s["cabinet_elevation_m"])) for s in project.fire_station_model_input["network"]["risers"]]], [78,48,48]),
            p("При Q=0 диафрагма не ограничивает статическое давление. Отверстия взяты из "
              "исходных, автоматически не увеличивались и не уменьшались.", small)]
        for i, group in enumerate(r["groups"], 1):
            story.append(p(f"Группа {i}: " + ", ".join(group), small))
        for case in r["cases"]:
            details = [" - ".join(pair) for pair in case["closed_runs"]] + case["closed_ports"]
            story.append(p(f"{label(case['id'])}: {case['basis']}. Закрыто: " + (", ".join(details) or "ничего"), small))
        story += [p("Статика на отметках заданных ПК", heading),
            table([("ПК / стояк", "Давление при Q=0, МПа"),
                *[(row["riser"], n(row["pressure_mpa"])) for row in r["static_rows"]]], [109,65]),
            p("Номинальная оценка: максимальный напор источников + напор одного насоса при Q=0 "
              "+ разность отметок. Не проверяет неуказанные нижние ПК, допуски насоса и переходные процессы. "
              "При отсутствии Hmax хотя бы одного ввода результат остаётся неопределённым.", small)]
        story += trace + [PageBreak(), p("Рабочие режимы: номинальная шкала", heading)]
        rows = [("Группа / отключение / источник", "Q, м3/ч", "H нас., м", "p min/max, МПа", "Результат")]
        for row in r["rows"]:
            if row["axis_offset_px"] != 0:
                continue
            result = row["result"]
            op = result["operating"] if result else None
            pressures = [c["outlet_head_m"]/MPA_TO_M for c in op["cabinets"]] if op else []
            status = ("Минимумы и динамика проходят" if row["minimum_ok"] and row["dynamic_ok"] else
                "Превышение давления" if row["minimum_ok"] else "Дефицит / нет решения")
            rows.append((f"Гр. {r['groups'].index(row['group'])+1} / {label(row['case'])} / {row['boundary']}",
                n(result["pump_flow_m3h"]) if result else "-",
                n(result["pump_head_m"]) if result else "-",
                f"{n(min(pressures))} / {n(max(pressures))}" if pressures else "-", status))
        story += [table(rows,[62,24,24,32,32]), Spacer(1,3*mm)]
        errors = sorted({row["error"] or row["result"]["status"] for row in r["rows"]
                         if not row["result"] or not row["result"]["operating"]})
        if errors:
            story.append(p("Неопределённые режимы: " + "; ".join(errors), small))
    content = BytesIO()
    SimpleDocTemplate(content, pagesize=A4, leftMargin=25*mm, rightMargin=10*mm,
        topMargin=12*mm, bottomMargin=65*mm).build(story)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(frame_station_calculation(content.getvalue(), project.document,
        "В2. Диафрагмы и отключения. Проверка"))
    return str(path)
