"""Readable calculation attachment bound to the same opt-in model as the A2."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle  # type: ignore[import-untyped]

from app.pz.drafting_font import DRAFTING_FONT_PATH
from app.pz.small_residential_calculation import FUNNEL_CAPACITY_LPS, FUNNEL_MODEL, FUNNEL_URL, ResidentialCalculation
from app.pz.small_residential_preview import ResidentialPreview
from app.pz.study_document_frame import build_study_text_pdf


def generate_residential_calculation_pdf(output: str, model: ResidentialPreview,
                                          calc: ResidentialCalculation, *, rain_source_sha256: str) -> str:
    calc.validate(model)
    if len(rain_source_sha256) != 64:
        raise ValueError("verified original rain source hash required")
    pdfmetrics.registerFont(TTFont("StudyGOST", str(DRAFTING_FONT_PATH)))
    pdfmetrics.registerFontFamily("StudyGOST", normal="StudyGOST", bold="StudyGOST", italic="StudyGOST", boldItalic="StudyGOST")
    normal = ParagraphStyle("Body", fontName="StudyGOST", fontSize=12, leading=15, spaceAfter=5)
    small = ParagraphStyle("Small", parent=normal, fontSize=10.5, leading=13)
    heading = ParagraphStyle("Heading", parent=normal, fontSize=17, leading=20, spaceBefore=9, spaceAfter=9)
    sub = ParagraphStyle("Sub", parent=normal, fontSize=14, leading=17, spaceBefore=7, spaceAfter=6)
    story = []

    def supported(value):
        # OpenGOST has no u-umlaut/arrow glyph. Never emit missing-glyph boxes.
        return str(value).replace("ü", "u").replace("→", " - ").replace("–", "-").replace("—", "-").replace("−", "-")

    def text(value, style=normal):
        story.append(Paragraph(supported(value), style))

    def number(v, places=3):
        if v is None:
            return "не определено"
        return f"{v:.{places}f}".replace('.', ',')

    def table(rows, widths):
        t = Table([[Paragraph(escape(supported(cell)), small) for cell in row] for row in rows],
                  colWidths=[v*mm for v in widths], hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf0f2")),
            ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#596168")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend((t, Spacer(1, 5*mm)))

    text("К1 и К2. Расчёт к общей схеме", heading)
    text(f"Двухэтажный жилой дом: 8 квартир, {calc.residents} жителей. Числа в этом приложении и на схеме сформированы из одного расчётного объекта.")
    table([
        ("Исходные данные", "Значение / происхождение"),
        ("Этажи / подвал / кровля", "0,000; +3,300 / -3,100; низ плиты -0,300 / +6,600, неэксплуатируемая — задано пользователем"),
        ("Расчётный дождь", f"{calc.storm.city.name}; P=1 год; F={number(calc.storm.f_calculated_m2, 1)} м²; стены 0 м² — учебное принятие, не обмер кровли"),
        ("Воронки и водосбор", f"4 шт.; по {number(calc.catchments_m2[0], 2)} м² на воронку — предложенное деление, разуклонка по АР не подтверждена"),
        ("Благоустройство квартир", "Для примера принята строка legacy: ванна ≥1500 мм, душ, 180 л/(житель·сут). Категорию и ГВС подтвердить."),
    ], [49, 126])
    text("1. Дождевой расход — исходный calcStorm()", sub)
    s = calc.storm
    text(f"F = Fкровли + 0,3 × Fстен = {number(s.f_calculated_m2, 1)} м².<br/>"
         f"q20 = {s.q20_base:g} л/(с·га); n = {number(s.n, 2)}; P=1; γ = {s.gamma:g}.<br/>"
         f"q5 = 4<super>n</super> × q20 × γ = {number(s.q5, 2)} л/(с·га).<br/>"
         f"Qк2 = F × q5 / 10000 = <b>{number(s.q_total_l_per_s)} л/с</b>.")
    text(f"Умножение выполняется до округления q5. На каждый условный водосбор: {number(calc.catchment_flows_lps[0])} л/с. Сумма округлённых расходов не заменяет расчёт всей кровли.", small)
    text(f"Предложены 4 воронки {FUNNEL_MODEL}, патрубок DN110, обогрев. Каталожный расход {number(FUNNEL_CAPACITY_LPS, 1)} л/с. Сопоставить с расходом водосбора; проверить подпор, гидроизоляцию и аварийный водоотвод. Подбор не утверждён.", small)
    text(f"Стояк К2 DN100: предел по таблице 21.1 СП 30 — {calc.riser_capacity_lps:g} л/с; Q всего здания={number(s.q_total_l_per_s)} л/с. Фактическое распределение водосборов требует плана.", small)
    text("2. Бытовой расход — исходный calcBlock()", sub)
    w = calc.water
    text(f"NP = 11,6 × {calc.residents} / (0,3 × 3600); α — таблица Б.2 legacy.<br/>"
         f"qtot = 5 × q0 × α; на выводе {number(w.total.q_sec)} л/с.<br/>"
         f"qs = qtot (до округления) + q0s = <b>{number(w.sewage_flow)} л/с</b>; q0s=1,600 л/с.<br/>"
         f"Qсут = {calc.residents} × 180 / 1000 = {number(w.total.q_day, 1)} м³/сут.")
    text("Перед экспортом выполнена проверка совпадения с исходным JavaScript legacy. Программное совпадение не заменяет проверку нормативной применимости и исходных данных.", small)
    text(f"SHA-256 исходного дождевого блока:<br/>{rain_source_sha256[:32]}<br/>{rain_source_sha256[32:]}", small)

    story.append(PageBreak())
    text("Гидравлика и подвальная прокладка", heading)
    text("3. Проверка конечных участков перед опусками", sub)
    text("Использован существующий решатель Шези–Маннинга: V=C√(R·i), C=R^(1/6)/n, Q=A·V. Площадь A и гидравлический радиус R вычислены для частично заполненного круглого сечения. Это не перенос таблиц Шевелева из legacy: их дождевой блок не содержит.", small)
    table([
        ("Показатель", "К1, конечный участок", "К2, конечный участок"),
        ("Труба / Dвнутр", "Ostendorf HT PP 110×2,7 / 104,6 мм", "Düker SML DN100, 110×3,5 / 103,0 мм"),
        ("Q / i / n", f"{number(calc.k1.design_flow_lps)} л/с / 0,020 / 0,011" if calc.k1 else "Расход по п. 5.7 не определён", f"{number(calc.k2.design_flow_lps)} л/с / 0,015 / 0,013"),
        ("V / h/D", f"{number(calc.k1.velocity_mps)} м/с / {number(calc.k1.fill_ratio, 4)}" if calc.k1 else "Не рассчитано", f"{number(calc.k2.velocity_mps)} м/с / {number(calc.k2.fill_ratio, 4)}"),
        ("Пропускная способность Qmax", f"{number(calc.k1.maximum_capacity_lps)} л/с" if calc.k1 else "Проверка не выполнена", f"{number(calc.k2.maximum_capacity_lps)} л/с"),
    ], [52, 61.5, 61.5])
    if calc.k1:
        text(calc.k1_flow.note, small)
        text(f"К1 при n=0,011: V√(h/D)={number(calc.k1.self_cleaning_value)}. Самоочищение {'проходит' if calc.k1.self_cleaning_ok else 'НЕ проходит'}. Критерии: V√(h/D) ≥ 0,5; V ≥ 0,7 м/с; h/D ≥ 0,3. Условие самоочищения К1 не переносится на дождевую К2.", small)
    else:
        text("Для К1 не задано L по примечанию таблицы 5.1 СП 30: от последнего стояка до следующего присоединения либо колодца. Предложенные 9 м разводки подвала не заменяют L. Расход стояков по формуле (5) не используется для горизонтальной гидравлики; самоочищение не проверено.", small)
    text("n — явно принятый учебный коэффициент, не паспортное измерение. Ниже проверка чувствительности; выбранный базовый результат не скрывает неустойчивость проверки К1.", small)
    table([("Система", "n", "V, м/с", "h/D", "Вывод при этом n")]+[
        (r.section_id, number(r.manning_n), number(r.velocity_mps), number(r.fill_ratio, 4),
         ("Самоочищение проходит" if r.self_cleaning_ok else "Самоочищение НЕ проходит") if r.section_id == "K1"
         else ("Q проходит, режим неполный" if r.fill_ratio is not None else "Перегрузка"))
        for r in calc.sensitivities
    ], [20, 20, 26, 26, 83])
    text("Это не проверка всех этажных ветвей и каждого промежуточного отрезка коллектора: до присоединения последнего стояка расходы меньше. Их наполнение и самоочищение требуется проверить по распределению жильцов и трассам; общий расход здания туда автоматически не переносится.", small)
    text("4. Профили под потолком — предложенные длины", sub)
    table([("Система", "L / уклон", "Лоток начало → конец", "Проход / зазор сверху")]+[
        (p.system, f"{p.length_m:g} м / {number(p.slope)}", f"{number(p.start_invert_m, 2)} → {number(p.end_invert_m, 2)} м",
         f"{number(p.passage_height_m(model.basement.basement_floor_m), 3)} / {number(p.ceiling_clearance_m(model.basement.ceiling_m), 3)} м")
        for p in (calc.basement.k1, calc.rain_profile)
    ], [23, 35, 58, 59])
    text("Zкон = Zнач − L·i. Ось = лоток + Dвнутр/2. Для габарита приняты добавки креплений 20 мм сверху и 30 мм снизу. Критерии примера: проход К1 ≥2,0 м, К2 ≥1,8 м; зазор ≥0,05 м. Это не универсальные расстояния из СП. Под К2 не достигнута комфортная высота 2 м. Балки, пересечения и изоляция требуют АР.", small)

    story.append(PageBreak())
    text("Обслуживание и границы проверки", heading)
    text("5. Доступ к сети: топология отдельно от возможности обслуживания", sub)
    table([("Маршрут", "Длина / предел", "Результат")]+[
        (f"{s.system}: начальная соосная прочистка → проходные тройники → опуск",
         f"{s.length_m:g} / {s.limit_m:g} м",
         "Путь непрерывен; расстояние соблюдено. Физический доступ не подтверждён.")
        for s in calc.services
    ], [83, 28, 64])
    text("Таблица 18.1 СП 30: для DN100–150 интервалы прочисток К1 ≤10 м, К2 ≤15 м; ревизий К1 ≤15 м, К2 ≤20 м. Здесь проверены предложенные прямые коллекторы от начала до опуска, не неизвестный участок до наружного колодца.", small)
    text("Проверены все четыре нижних узла каждой системы, включая два не показанных в разрезе. Заглушка только на свободном начале. В проходных тройниках нет заглушек. Сохранены этажные прочистки, ревизии и отдельные ревизии на опусках. Геометрия фасонины и путь троса должны подтверждаться выбранными изделиями.", small)
    text("Обязательное уточнение: обслуживание подвесной сети по п.18.26 / 21.8 СП 30, люки и вывод прочисток на вышележащий этаж. Без плана подвала и первого этажа вывод через перекрытие автоматически не добавлен. Для К2 отдельно проверить доступность нижних ревизий по п.21.15.", small)
    text("6. К2 при засоре и раздельные выпуски", sub)
    text(f"Для учебного лотка К2 {number(calc.provisional_k2_outlet_m, 2)} м: H = 6,60 − ({number(calc.provisional_k2_outlet_m, 2)}) = {number(calc.hydrostatic_head_m, 2)} м; p = ρgH = {number(calc.hydrostatic_bar)} бар. Это гидростатика до отметки кровли, без неизвестного слоя воды на ней и без наружного подпора.", small)
    text("По каталогу SML DN100: труба и фасонные части до 10 бар; удерживающие Kombi-Kralle DN50–100 до 10 бар. Нужны совместимые уплотняющие соединения, фиксация и расчёт опор. Прочность собранной системы, герметичность узла воронки и испытание этим сравнением не подтверждены.", small)
    text("Выпуск К1 -2,20 м — прежний предварительный предел по морозу. Выпуск К2 -2,25 м — отдельное учебное предложение, не расчёт по морозу и не отметка ТУ. Крышка колодца -1,00 м НЕ является отметкой лотка или достоверным уровнем подпора. К2 не соединяется с К1.", small)
    text("7. Нормативная трассировка и открытые пункты", sub)
    text("СП 30: 19.1 — гидравлика К1; 21.7 — подвесной уклон К2; 21.10–21.12 — дождевой расход, воронки, стояки; 21.13–21.15 — прочность, материал, обслуживание. ГОСТ Р 21.620-2023: 5.2.2.3 — общий лист разных систем; 5.2.2.4 — состав обозначений и отметок, приложение В — композиция разреза.", small)
    text("До выпуска ИОС3 нужны: план/трассы АР, фактические длины и расходы ветвей, доступ к арматуре, узлы кровли и аварийного отвода, соединения и опоры К2, отметки внешнего присоединения/подпор, абсолютная привязка, проверка этажной вентиляции и всего состава ПЗ. Этот расчёт не объявляет весь комплект соответствующим ГОСТ.", small)
    text("Источники и воспроизводимость", sub)
    text(f'<link href="{escape(calc.rain_pipe.series.source_url)}" color="#225577">Düker SML: таблица размеров, стр.37; соединения, стр.65, 73–78.</link><br/>'
         f'<link href="{escape(FUNNEL_URL)}" color="#225577">Hutterer &amp; Lechner: HL62.1/1, технические данные.</link><br/>'
         f'<link href="{escape(model.stack_pipe.series.source_url)}" color="#225577">Ostendorf HT: каталог 2026.01, стр.2.</link><br/>'
         'СП 30.13330.2020 с изменениями; ГОСТ Р 21.620-2023, файл «ГОСТ К.pdf».<br/>'
         'Код: legacy/sp30_calculator.html; app/calc/storm.py; app/calc/water_demand.py; app/calc/sewer_hydraulics.py.', small)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_study_text_pdf(story, title="К1, К2 - расчёт к общей схеме",
        sheet_title="Учебный расчёт К1, К2", cipher="УЧЕБНЫЙ-К1К2.Р",
        detail="Не заменяет комплект ИОС3 и рабочую документацию."))
    return str(path)
