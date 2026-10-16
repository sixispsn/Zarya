"""Traceable joint cards. Published conflicting lengths are NOT dimensions."""
from app.data.metering_products import get_metering_catalogue
from app.pz.metering_connections import CONNECTION_ROLES
from app.pz.metering_pipes import PIPE_ROLES, MATERIALS
from app.pz.metering_product_selection import resolve_metering_products


def connection_contents(project, state):
    from app.pz.metering_detail import _text, _line, _lines, _n, _arrow
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    catalog = get_metering_catalogue()
    pages = []
    for check in selection.connections:
        _, _, pipe_role, product_role = CONNECTION_ROLES[check.role]
        product = selection.selected(product_role)
        pipe = project.metering_detail.pipe_sections.get(pipe_role)
        part = check.requested
        lines = [check.title,
                 "Статус: требуется исправление / подтверждение" if check.errors else
                 "Статус: проверены порты; монтаж требует уточнения" if check.ports_confirmed else
                 "Статус: недостаточно данных о присоединениях"]
        if product:
            sex = "ВР" if product.connection_sex == "female" else "НР"
            lines.append(f"Арматура: {product.name}; присоединение {product.connection_standard}{product.thread} {sex}.")
        if pipe:
            size = lambda v: _n(v,1) if v is not None else "не задано"
            lines.append(f"Труба {PIPE_ROLES[pipe_role][0]}: {MATERIALS[pipe.material]}; {pipe.series or 'серия не задана'}; "
                         f"Ø{size(pipe.outer_diameter_mm)}×{size(pipe.wall_thickness_mm)} мм.")
        adapter = check.thread_adapter
        if adapter:
            sex = lambda s: "НР" if s == "male" else "ВР"
            lines += [f"Промежуточная деталь: {adapter.manufacturer} {adapter.article}; "
                      f"{adapter.connection_standard}{adapter.equipment_thread} {sex(adapter.equipment_sex)} / "
                      f"{adapter.connection_standard}{adapter.pipe_connector_thread} {sex(adapter.pipe_connector_sex)}.",
                      f"Длина отдельного корпуса L = {_n(adapter.body_length_mm,1)} мм. Глубины свинчивания не вычтены."] if adapter.body_length_mm is not None else [
                      "Промежуточная деталь: габарит не подтверждён."]
        if part:
            sex = "НР" if part.connection_sex == "male" else "ВР"
            lines += [f"Заданный кандидат: {part.manufacturer} {part.article}.",
                      f"Порты: {part.connection_standard}{part.thread} {sex} / раструб под трубу "
                      f"Ø{part.pipe_outer_diameter_mm:g} мм, {part.pipe_material.upper()}."]
            if part.body_length_mm is not None:
                lines.append(f"Длина отдельного корпуса L = {_n(part.body_length_mm,1)} мм, не установленного стыка.")
            else:
                dims = part.dimensions_mm
                lines += ["ГАБАРИТ НЕ ПРИНЯТ: источники производителя расходятся.",
                          f"Паспорт: A = {_n(dims['passport_L'],1)} мм; отдельный чертёж: "
                          f"L = {_n(dims['drawing_L'],1)} мм."]
            if "passport_socket_depth" in part.dimensions_mm:
                lines.append(f"Раструб по паспорту: B = {_n(part.dimensions_mm['passport_socket_depth'],1)} мм. "
                             "Это глубина раструба, не назначенная глубина посадки трубы.")
        lines += ["Ошибка: " + text for text in check.errors]
        lines += ["Уточнение: " + text for text in check.pending]
        lines += ["Присоединение не заменяет всю цепочку узла. Остальные соединители, прямые участки, "
                  "монтажные зазоры и опоры требуют отдельного подбора.",
                  "Схема ИОС2 остаётся принципиальной. Монтажная длина стыка и всего ВУ не определена."]
        if part:
            for source in dict.fromkeys((*part.source_ids, *(adapter.source_ids if adapter else ()))):
                s = catalog.sources[source]
                lines.append(f"Источник: {s['title']}; PDF стр. {s['pages']}.")
        content = [_text(28,17,"Присоединения труб к арматуре ВУ",5),
                   _text(28,26,"Карточка проверки стыка. Размеры из источников не являются монтажным заданием.",3.5)]
        y = 42
        if part and adapter and product and pipe:
            # An exploded connection sequence, NOT a made-up 1:1 contour.
            # Thin boxes intentionally avoid masquerading as fitting UGOs.
            product_sex = " ВР" if product.connection_sex == "female" else " НР"
            boxes = [(28, "Арматура", product.connection_standard+product.thread+product_sex),
                     (126, "Соединитель", adapter.article),
                     (224, "Муфта PP-R", part.article),
                     (322, "Труба", "Ø"+size(pipe.outer_diameter_mm)+"×"+size(pipe.wall_thickness_mm))]
            for x, title, label in boxes:
                content += [_line(x,38,x+80,38,.25), _line(x,60,x+80,60,.25),
                            _line(x,38,x,60,.25), _line(x+80,38,x+80,60,.25),
                            _text(x+40,46,title,3.5,"middle"), _text(x+40,55,label,3.5,"middle")]
                if x < 322:
                    content += [_line(x+80,49,x+95,49,.25), _arrow(x+95,49)]
            content.append(_text(28,69,"Последовательность соединений без масштаба; длины корпусов не складываются в монтажный размер.",3.5))
            y = 82
        for text in lines:
            for line in _lines(text,376,3.5):
                if y > 226:
                    pages.append(''.join(content))
                    content = [_text(28,17,"Присоединения труб к арматуре ВУ - продолжение",5)]
                    y = 32
                content.append(_text(28,y,line,3.5))
                y += 5.5
            y += 2.5
        pages.append(''.join(content))
    return pages
