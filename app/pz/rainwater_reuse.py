"""Presentation of the optional rainwater study, not a fabricated pipe layout."""
from html import escape

from app.calc.rainwater_reuse import assess
from app.calc.rainwater_treatment import assess_treatment, project_context


def functional_svg(project) -> str:
    r = assess(project.rainwater_reuse, **project_context(project))
    if not r["enabled"]:
        return ""
    # Rectangular process blocks are explicitly NOT equipment UGO or a routed
    # principle drawing. No invented DN, elevations, valve counts or K2→K1 edge.
    blocks = [
        (40, ["Кровля, подключённая к сбору", "Площадь — по исходным данным"]),
        (135, ["Отстаивание / подготовка", "Технология — по качеству воды"]),
        (230, ["Накопительный резервуар", r["location"]]),
        (325, ["Подача и обеззараживание", "Насос: кандидат по расчётной точке" if r["pump"]["selected"] else "Насос и оборудование не подобраны"]),
        (420, ["Отдельная техническая сеть", r["purpose"]]),
    ]
    pack = r["treatment"]["status"] != "not_configured"
    overflow_y = 230
    if pack:
        blocks = [
            (40, ["Кровля / задержание мусора", "Отведение первого стока"]),
            (135, ["Отстаивание и накопление", r["location"] + "; удаление осадка"]),
            (230, ["Насос → фильтрация", "Контроль перепада давления"]),
            (325, ["УФ → защитная отсечка", "Доза, расход, отказ оборудования"]),
            (420, ["Отдельная сеть полива", "Декоративное озеленение"]),
        ]
        overflow_y = 135
    g = ['<svg xmlns="http://www.w3.org/2000/svg" width="175mm" height="151mm" viewBox="0 0 660 570" role="img" aria-label="Функциональная структура использования дождевой воды">',
         '<defs><marker id="rw-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="black"/></marker></defs>',
         '<g fill="none" stroke="black" stroke-width="1.2">']
    for y, _ in blocks:
        g.append(f'<rect x="15" y="{y}" width="345" height="64"/>')
        if y < 420:
            g.append(f'<path d="M187,{y+64} V{y+95}" marker-end="url(#rw-arrow)"/>')
    if pack:
        g.extend(['<path d="M360,72 H403" marker-end="url(#rw-arrow)"/>',
                  '<rect x="405" y="40" width="240" height="64"/>'])
    g.extend([f'<path d="M360,{overflow_y+32} H403" marker-end="url(#rw-arrow)"/>',
              f'<rect x="405" y="{overflow_y}" width="240" height="64"/>', '</g>',
              '<g font-family="DejaVu Sans,Arial,sans-serif" font-size="13" fill="black" text-anchor="middle">'])
    for y, lines in blocks:
        for i, line in enumerate(lines):
            g.append(f'<text x="187" y="{y+25+i*23}">{escape(line)}</text>')
    for y, line in ((overflow_y+25, "Перелив и опорожнение"), (overflow_y+48, "Точка отвода — уточнить")):
        g.append(f'<text x="525" y="{y}">{line}</text>')
    if pack:
        g.extend(['<text x="525" y="65">Первый загрязнённый сток</text>',
                  '<text x="525" y="88">Отвод — по проекту, не К1</text>'])
    g.extend(['<text x="330" y="525">Прямое подключение к питьевому В1 не предусмотрено.</text>',
              '<text x="330" y="549">Дефицит воды требует отдельного решения; К2 в К1 не соединяется.</text>',
              '</g></svg>'])
    return "".join(g)


def specification_rows(project):
    from app.pz.spec import SpecRow

    d = project.rainwater_reuse
    if not d.enabled:
        return []
    volume = f"Полезный объём {d.useful_volume_m3:g} м³ — задан для проверки" if d.useful_volume_m3 else "Полезный объём не определён"
    rows = [SpecRow(None, name, unit=unit, qty=None, note=note,
                    quantity_source="Состав системы предварительный; тип, количество и параметры требуют проектного подбора")
            for name, unit, note in (
                ("Резервуар атмосферной воды", "шт.", volume),
                ("Оборудование отстаивания и подготовки дождевой воды", "компл.", "По составу загрязнений; производительность не задана"),
                ("Установка обеззараживания технической воды", "компл.", "По требованиям к качеству воды и расчётному расходу"),
                ("Насосная установка технической воды", "компл.", "Q/H не определены; не заменяет насос В1"),
                ("Контроль уровней, сигнализация перелива и защита от сухого хода", "компл.", "По выбранной ёмкости и автоматике насоса"),
                ("Трубопроводы отдельной сети технической воды, перелива и опорожнения", "м", "Материал, DN и длины — по принятой трассе; отдельная маркировка"),
                ("Арматура системы дождевого водоснабжения", "компл.", "Состав и количество — по проектной схеме"),
            )]
    if d.pump_setup == "submersible_irrigation" and d.purpose == "irrigation":
        # Replace, do not add another pump/valve set over the old placeholders.
        rows = [row for row in rows if row.name not in {
            "Насосная установка технической воды", "Арматура системы дождевого водоснабжения",
            "Контроль уровней, сигнализация перелива и защита от сухого хода",
        }]
        for row in rows:
            if row.name.startswith("Трубопроводы отдельной сети"):
                row.name = "Трубопроводы сбора, перелива и опорожнения резервуара"
                row.note = "Напорная труба подачи учитывается отдельно; DN и длины без трассы не назначены."
        rows.extend(assembly_rows(project))
    if d.treatment_setup:
        # Keep the settling requirement; a cartridge is not a settling tank.
        rows = [row for row in rows if row.name not in {
            "Оборудование отстаивания и подготовки дождевой воды",
            "Установка обеззараживания технической воды",
        }]
        rows.extend(treatment_rows(project))
    return rows


def treatment_rows(project):
    from app.pz.spec import SpecRow
    from app.calc.rainwater_pump import assess_pump
    r = assess_treatment(project.rainwater_reuse, **project_context(project))
    if r["status"] == "not_configured":
        return []
    basis = "Предварительный состав для жилой террасы; не подтверждение качества и не закупочная спецификация."
    pump = assess_pump(project.rainwater_reuse, **project_context(project))
    quantity_confirmed = r["ready_for_pump"] and pump["selected"] is not None
    rows = []
    for item in r["candidates"]:
        # Candidates may be shown by name without being silently purchased.
        rows.append(SpecRow(None, item["name"], type_mark=item["model"],
            code=item["article"], manufacturer=item["manufacturer"], unit="компл.",
            qty=1 if quantity_confirmed else None, quantity_basis="assembly_estimate",
            quantity_source=basis, note=item["included"] + " " + item["rating_note"] +
            (" Пригодность по давлению проверяется совместно с насосом." if r["ready_for_pump"] else " Подбор не завершён.")))
    if not r["candidates"]:
        rows.extend(SpecRow(None, name, unit="компл.", qty=None,
                            note="Типовой комплект не применён: " + "; ".join(r["missing"] + r["errors"]),
                            quantity_source=basis)
                    for name in ("Оборудование фильтрации дождевой воды", "Установка обеззараживания технической воды"))
    for name, note in (
        ("Узел задержания крупного мусора и отведения первого стока", "Пропускная способность и режим по кровле; модель и количество не определены."),
        ("Отстойная зона с удалением осадка", "Конструкция в составе бака либо отдельное оборудование; не дублировать резервуар. Размеры требуют обоснования."),
        ("Контроль перепада давления фильтра", "Уставка по загрязнению картриджа; модель и комплектность уточнить."),
        ("Контроль расхода и отсечка подачи при отказе обеззараживания", "Внешний расходомер и исполнительный клапан не включены автоматически в комплект УФ. Без байпаса в сеть полива."),
    ):
        rows.append(SpecRow(None, name, unit="компл.", qty=None, note=note,
                            quantity_source=basis))
    return rows


def assembly_rows(project):
    """Counts refer ONLY to the expressly chosen reference assembly.

    Pump + supplied check valve -> prepared-water treatment block with 2 service
    valves and 2 unions -> controller with pressure indication -> N outlet valves.
    An N-outlet comb has N-1 tees; one additional tee serves the low drain.
    Elbows, physical transitions, pipe supports and sealant are NOT guessed.
    """
    from app.pz.spec import SpecRow
    from app.calc.rainwater_pump import assess_pump, validate
    d = project.rainwater_reuse
    if (not d.enabled or d.pump_setup != "submersible_irrigation"
            or d.purpose != "irrigation" or validate(d)):
        return []
    p = assess_pump(d, **project_context(project))
    pump = p["selected"]
    n = d.outlets_count
    source = "По выбранной типовой обвязке полива; не обмер трасс. Размеры присоединений и исполнения уточняются по оборудованию."
    def row(name, qty=None, unit="шт.", note="", **kwargs):
        return SpecRow(None, name, unit=unit, qty=qty, note=note, quantity_basis="assembly_estimate", quantity_source=source, **kwargs)
    rows = [
        row("Погружной насос подготовленной дождевой воды", 1 if pump else None,
            type_mark=pump["model"] if pump else "Подбор не завершён", manufacturer="ДЖИЛЕКС" if pump else "",
            code=pump["article"] if pump else "", note=(f"{pump['power_kw']:g} кВт; 220 В; кандидат по Q/H. Обратный клапан, донный фильтр и поплавок в поставке, отдельно не дублируются." if pump else "Отсутствие подбора не заменяется условной моделью.")),
        row("Арматура отключения блока подготовки", 2, note="До и после оборудования; байпас неочищенной воды не предусмотрен. DN/PN по подобранному блоку."),
        row("Разъёмные соединения блока подготовки", 2, note="Для демонтажа; резьба/фланцы по паспорту блока."),
        row("Контроллер насосной подачи с контролем давления и остановкой при отсутствии расхода", 1, unit="компл.", note="Модель, уставки и совместимость требуют подбора. Встроенный поплавок не заменяет остановку при закрытом кране."),
        row("Поливочный запорный кран", n, note="По одной точке на каждый отвод коллектора; непитьевая вода."),
        row("Тройник распределительной линии и спускника", n if n else None, note="N−1 для распределения + 1 для спускника. Не дополнительные тройники трассы; DN уточнить."),
        row("Кран опорожнения напорной линии с заглушкой", 1, note="В нижней точке; отвод воды в согласованное безопасное место, не автоматически в К1."),
        row("Табличка «Вода непитьевая»", n, note="На каждой точке разбора; маркировка трубопровода дополнительно."),
        row("Контроль верхнего уровня и сигнализация переполнения", 1, unit="компл.", note="Отдельная функция; не подменяется поплавком защиты насоса."),
        row("Подвес насоса: трос, крепления и зажимы", None, unit="компл.", note="Длина и несущая способность по установке; не подвешивать за электрический кабель."),
        row("Фасонные части трассы, переходники, опоры и уплотнения", None, unit="компл.", note="Не включены в подсчитанные тройники обвязки. По материалу трубы, DN, маршруту и резьбам выбранных изделий."),
    ]
    rows.append(row("Напорная труба от насоса до распределения", d.pump_pipe_length_m, "м",
                    f"dвн={d.pump_pipe_inner_mm:g} мм; материал, наружный размер и длину по трассе уточнить" if d.pump_pipe_inner_mm else "Материал, размеры и длину уточнить"))
    if d.hose_choice == "custom":
        size = f"dвн={d.hose_inner_mm:g} мм" if d.hose_inner_mm else "dвн не задан"
        length = f"; L={d.hose_length_m:g} м на комплект" if d.hose_length_m else ""
        pressure = f"; рабочее давление {d.hose_pn_bar:g} бар" if d.hose_pn_bar else ""
        # Keep a failed item as an explicit requirement, not a purchased product.
        qty = d.hose_sets if pump else None
        rows.append(row("Поливочный шланг", qty, "шт.", size + length + pressure + ("; совместимость не подтверждена" if not pump else ""), type_mark=d.hose_model))
        rows.append(row("Присоединители шланга к крану и поливочному устройству", 2 * qty if qty else None,
                        note="Два на комплект. Если входят в поставку шланга — исключить отдельную закупку; резьбы и давление проверить."))
        rows.append(row("Поливочное устройство / насадка", qty,
                        note="Модель по расчётным расходу и конечному напору; паспорт и совместимость подтвердить."))
    return rows


def pump_chart_svg(project):
    """Catalog + required duty, deliberately no fictitious operating intersection."""
    from app.calc.rainwater_pump import assess_pump
    r = assess_pump(project.rainwater_reuse, **project_context(project))
    p, duty = r["selected"], r["duty"]
    if not p or not duty:
        return ""
    w, h, left, top = 500, 240, 65, 25
    ymax = max(p["shutoff_head_m"] * 1.15, duty["h_m"]) * 1.1
    x = lambda q: left + q / 3.2 * w
    y = lambda head: top + h - head / ymax * h
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="175mm" height="96mm" viewBox="0 0 640 350">',
           '<g font-family="DejaVu Sans,Arial,sans-serif" font-size="13" fill="black">']
    for i in range(6):
        head = ymax * i / 5
        svg += [f'<path d="M{left},{y(head):.2f} H{left+w}" stroke="#ccc" stroke-width="0.7"/>',
                f'<text x="55" y="{y(head)+4:.2f}" text-anchor="end">{head:.0f}</text>']
    for q in (0, 1, 2, 3):
        svg.append(f'<text x="{x(q):.2f}" y="285" text-anchor="middle">{q}</text>')
    for factor, dash in ((1, ""), (0.85, ' stroke-dasharray="6 4"')):
        points = ' '.join(f'{x(q):.2f},{y(head*factor):.2f}' for q, head in p['curve'])
        svg.append(f'<polyline points="{points}" fill="none" stroke="black" stroke-width="1.5"{dash}/>')
    xx, yy = x(duty['q_m3h']), y(duty['h_m'])
    svg += [f'<path d="M{xx-5:.2f},{yy-5:.2f} l10,10 m-10,0 l10,-10" stroke="black" stroke-width="2"/>',
            '<text x="18" y="20">H, м</text><text x="580" y="285">Q, м³/ч</text>',
            '<text x="65" y="312">Сплошная: каталог. Штриховая: напор с допуском −15%.</text>',
            '<text x="65" y="337">× Требуемая точка; не фактическая рабочая точка насоса.</text>', '</g></svg>']
    return ''.join(svg)
