"""Compact passport schedule for every calculated water-meter node."""
from app.pz.meter_products import evaluate_meter_product, primary_meter
from app.pz.metering_accessories import select_connection_kit
from app.pz.metering_table_grid import table_grid_sides


def product_contents(project):
    from app.pz.metering_detail import _text, _line, _lines, _n
    from app.data.metering_products import get_metering_catalogue
    catalog, detail = get_metering_catalogue(), project.metering_detail
    pages, content, y = [], [], 0
    for row in project.meters.rows:
        check = evaluate_meter_product(project, row)
        p = check.product
        texts = [row.label, p.name if p else "Модель не подтверждена"]
        if p:
            texts += [f"Паспорт: Qmin={_n(check.evidence.q_min_passport_m3h,3)}; "
                      f"Qmax={_n(p.flows_m3h['qmax'],1)} м³/ч; L корпуса={p.body_length_mm:g} мм; PN {p.pn_bar:g} бар."
                      if check.evidence.q_min_passport_m3h is not None else
                      f"Qmax={p.flows_m3h['qmax']:g} м³/ч; Qmin для ориентации монтажа не подтверждён.",
                      f"Расчёт по СП 30, п. 12.15: h=S·q²={_n(row.h_a,3)} м; S={_n(row.s_resist,5)} по табл. 12.1."]
            hydraulic = check.summary()['hydraulic_evidence']
            if hydraulic:
                texts.append(hydraulic['note'])
            texts += ["Источник: " + get_metering_catalogue().sources[s]['title'] for s in p.source_ids]
        kit = select_connection_kit(catalog,p,
            explicit_id=detail.catalogue_items.get('meter_connections') if row is primary_meter(project) else None,
            automatic=detail.meter_selection_mode == 'catalogue_proposal',
            revision_ok=detail.catalogue_revision == catalog.revision)
        texts.append(f"{kit.name}; 1 комплект на счётчик." if kit else
                     "Присоединительный комплект: требуется подбор; 1 комплект на счётчик.")
        if kit:
            texts.append(f"G{kit.meter_thread} / G{kit.pipe_thread}; "
                         f"L1 со счётчиком = {kit.length_with_meter_reference_mm:g} мм СПРАВОЧНО, не длина узла.")
        texts += [check.minimum_note] + list(check.errors)
        block = [line for text in dict.fromkeys(texts) for line in _lines(text, 374, 3.5)]
        if not content or y + len(block)*5.5 > 194:
            if content:
                content.append(table_grid_sides((27,407),35,y-5,kind='meter-products'))
                pages.append("".join(content))
            content = [_text(28,17,"Подбор моделей узлов учёта воды",5),
                       _text(28,27,"Паспортные данные отделены от принятой расчётной таблицы СП",3.5)]
            y = 40
        content.append(_line(27,y-5,407,y-5,.25))
        for line in block:
            content.append(_text(28,y,line,3.5))
            y += 5.5
        y += 7
    if content:
        content.append(table_grid_sides((27,407),35,y-5,kind='meter-products'))
        for text in (
            "Автоматические модели - предложения каталога, не подтверждённая комплектация к закупке.",
            "Класс и Qmin проверяются по паспорту для текущего положения и направления потока.",
            "Проверить P/T, прямые участки, присоединения, режим выше Qn и сопротивление изделия по техдокументации.",
            "Комплект учтён отдельно в СО; если входит в поставку счётчика, повторно не закупать.",
        ):
            for line in _lines(text,374,3.5):
                content.append(_text(28,y,line,3.5))
                y += 5.5
        pages.append("".join(content))
    return pages
