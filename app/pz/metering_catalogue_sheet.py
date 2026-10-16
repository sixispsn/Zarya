"""Paginated product binding audit, not a mounting drawing or purchase BOM."""
from app.data.metering_products import get_metering_catalogue
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_table_grid import table_grid_sides


def catalogue_contents(project, state) -> list[str]:
    # Lazy import avoids a rendering-module cycle.
    from app.pz.metering_detail import _text, _line, _lines, _n
    result = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                      electric_bypass=state.electric_bypass)
    catalog = get_metering_catalogue()
    blocks = []
    for pos in result.positions:
        product = pos.product
        count_scope = "на общий ВУ" if state.common_inlets else "на ввод"
        title = f"{pos.title} · DN{pos.dn or '—'} · {pos.quantity_per_inlet} шт. {count_scope}"
        lines = [title]
        if state.switching_bridge and pos.role in ('inlet_valve', 'bypass_valve'):
            lines.append('Кандидат для внешней переключающей обвязки Г.1. Не входит в размерную цепочку вставки; монтаж и присоединения отдельно не подтверждены.')
        if product:
            lines += [f"{product.name}" + (f" · {product.article}" if product.article else ""),
                      f"Длина корпуса L = {_n(product.body_length_mm,1)} мм; "
                      f"{product.connection_label}, "
                      + ("фланцы" if product.flange else "внутренняя резьба" if product.connection_sex == "female" else "наружная резьба")
                      + f"; PN {product.pn_bar:g} бар."]
            if product.kit_pipe_thread:
                lines.append(f"С комплектом L1 = {_n(product.dimensions_mm['L1_reference'],1)} мм "
                             f"СПРАВОЧНО; трубное присоединение G{product.kit_pipe_thread}. "
                             "Комплект и длину подтвердить при заказе.")
            if product.flows_m3h:
                q = product.flows_m3h
                from app.pz.metering_orientation import check_product_orientation
                orientation = check_product_orientation(product,project.metering_detail.meter_mounting)
                minimum = (f"класс {orientation.metrological_class}: Qmin={orientation.qmin_m3h:g}"
                           if orientation.qmin_m3h is not None else "Qmin для ориентации не подтверждён")
                lines.append(f"Паспорт, {minimum}; Qn={q['qn']:g}; "
                             f"Qmax={q['qmax']:g} м³/ч. Не замена расчётной таблицы СП.")
            if product.remote_interface:
                lines.append(f"Выход данных: {product.remote_interface}. Настройка регистратора не подтверждена.")
            if product.kind == "check":
                lines.extend("Монтаж: " + note for note in product.notes)
            for source in product.source_ids:
                s = catalog.sources[source]
                lines.append(f"Источник: {s['title']}; PDF стр. {s['pages']}.")
        else:
            lines.append("Изделие не подтверждено. " + ("; ".join(pos.errors) or "Требуется выбор модели."))
        lines.extend("Уточнение: " + item for item in pos.pending)
        # Keep each product block together; wrap by actual embedded font metrics.
        blocks.append([line for text in lines for line in _lines(text,376,3.5)])
    for accessory in result.accessories:
        lines = [accessory.title] + list(accessory.details)
        lines += ["Ошибка: " + text for text in accessory.errors]
        lines += ["Уточнение: " + text for text in accessory.pending]
        for source in accessory.source_ids:
            s = catalog.sources[source]
            lines.append(f"Источник: {s['title']}; PDF стр. {s['pages']}.")
        blocks.append([line for text in lines for line in _lines(text,376,3.5)])
    from app.pz.metering_chain import build_metering_chain
    chain = build_metering_chain(project.metering_detail, state, result)
    marks = {n.id: f"С{i}" for i, n in enumerate(
        (n for n in chain.nodes if n.role == "inline_nipple"), 7)}
    for check in result.inline_joints:
        if not check.part and not check.errors:
            continue  # Unassigned generic fittings remain in the composition.
        lines = ["Прямое резьбовое соединение " + marks.get(check.id, "(назначение неактуально)")]
        if part := check.part:
            lines += [f"{part.manufacturer} {part.article}; G{part.equipment_thread} НР/НР; "
                      f"L корпуса {part.body_length_mm:g} мм",
                      f"PN {part.pn_bar:g} бар; диапазон температуры "
                      f"{part.temperature_c[0]:g}...{part.temperature_c[1]:g} °C"]
            for source in part.source_ids:
                s = catalog.sources[source]
                lines.append(f"Источник: {s['title']}; PDF стр. {s['pages']}.")
        lines += ["Ошибка: " + e for e in check.errors]
        lines += ["Уточнение: " + p for p in check.pending]
        blocks.append([line for text in lines for line in _lines(text,376,3.5)])
    from app.pz.metering_service import SERVICE_ROLES
    for check in result.services:
        if not check.part and not check.errors:
            continue
        title, _, ids = SERVICE_ROLES[check.role]
        lines = [f"{title}: {len(ids)} шт. " + ("на общий ВУ" if state.common_inlets else "на ввод")]
        if part := check.part:
            lines.append(f"{part.manufacturer} {part.article}" + ("; предварительное предложение" if check.proposed else ""))
            lines.extend(part.notes if check.role != 'control_cocks' else ())
            for source in part.source_ids:
                s = catalog.sources[source]
                lines.append(f"Источник: {s['title']}; {s.get('pages','')}.")
        lines += ["Ошибка: " + e for e in check.errors]
        lines += ["Уточнение: " + p for p in check.pending]
        blocks.append([line for text in lines for line in _lines(text,376,3.5)])
    final = ["Общие ограничения"] + list(result.errors) + list(result.pending)
    for check in result.fittings:
        lines = ["Фасонная часть: " + check.role]
        if part := check.part:
            dimension = (f"A={part.dimensions_mm['A']:g} мм от оси до торца каждой ветви" if part.kind == 'elbow90'
                         else f"L корпуса {part.body_length_mm:g} мм")
            lines += [part.name, f"{dimension}; {part.material}; PN{part.pn_bar:g}",
                      "Порты: " + "; ".join(f"DN{p.dn} {p.connection} {p.thread}" for p in part.ports)]
            lines += [f"Источник: {catalog.sources[s]['title']}, стр. {part.source_page}" for s in part.source_ids]
        lines += list(check.errors) + list(check.pending)
        blocks.append([line for text in lines for line in _lines(text,376,3.5)])
    blocks.append([line for text in final for line in _lines(text,376,3.5)])
    pages, content, y = [], [], 0
    def start_page():
        return [_text(28,17,"Каталожная комплектация водомерного узла",5),
                _text(28,26,f"Предварительный подбор изделий · база {result.revision}",3.5),
                _text(28,34,"Габариты из паспортов. Общая монтажная длина узла не определена.",3.5)]
    for block in blocks:
        height = len(block)*5.5 + 6
        if height > 188:
            raise ValueError("Описание изделия слишком длинное для листа комплектации")
        if not content or y+height > 228:
            if content:
                content.append(table_grid_sides((27,407),41,y-4,kind='catalogue'))
                pages.append("".join(content))
            content, y = start_page(), 45
        content.append(_line(27,y-4,407,y-4,.25))
        for line in block:
            content.append(_text(28,y,line,3.5))
            y += 5.5
        y += 6
    if content:
        content.append(table_grid_sides((27,407),41,y-4,kind='catalogue'))
        pages.append("".join(content))
    return pages
