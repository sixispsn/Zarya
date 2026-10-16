"""Readable, paginated rule trace alongside the meter schematic."""
from app.pz.metering_rules import evaluate_metering_rules
from app.pz.metering_table_grid import table_grid_sides


STATUS_LABELS = {"checked": "Проверено по исходным данным", "requirement": "Требование к исполнению",
                 "needs_data": "Нужны данные", "review": "Нужна проверка решения", "error": "Несоответствие"}


def rule_contents(project, state) -> list[str]:
    from app.pz.metering_detail import _text, _line, _lines
    rules = evaluate_metering_rules(project, state.meter, inputs_count=state.inputs_count, bypass=state.bypass)
    pages, content, y = [], [], 0
    for rule in rules:
        lines = _lines(rule.message, 373, 3.5)
        source = _lines(f"{STATUS_LABELS[rule.status]} · {rule.clause}", 373, 3.5)
        # Keep readable 3.5 mm text; avoid a nearly empty continuation sheet
        # by reducing only the inter-block whitespace, not the type size.
        gap = 5
        height = (len(source) + len(lines))*5.5 + gap
        if height > 180:
            raise ValueError("Описание условия ВУ слишком длинное для листа")
        if not content or y + height > 228:
            if content:
                content.append(table_grid_sides((27,407),42,y-4,kind='rules'))
                pages.append("".join(content))
            content = [_text(28,17,"Условия компоновки водомерного узла",5),
                       _text(28,27,"Общедомовой узел ХВС · СП 30.13330.2020 с изменениями № 1–5",3.5),
                       _text(28,35,"Проверки не заменяют расчёт водомера, паспорт изделия и монтажную привязку.",3.5)]
            y = 46
        content.append(f'<g data-meter-rule="{rule.code}" data-status="{rule.status}">')
        content.append(_line(27,y-4,407,y-4,.25))
        for line in source + lines:
            content.append(_text(28,y,line,3.5))
            y += 5.5
        content.append('</g>')
        y += gap
    if content:
        content.append(table_grid_sides((27,407),42,y-4,kind='rules'))
        pages.append("".join(content))
    return pages
