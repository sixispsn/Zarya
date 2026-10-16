"""Readable per-section pipe schedule; deliberately not a fabrication BOM."""
from app.pz.metering_pipes import PIPE_ROLES, MATERIALS, JOINING, pipe_checks, support_pipe
from app.pz.metering_table_grid import table_grid_sides


def pipe_contents(project, state):
    from app.pz.metering_detail import _text, _line, _lines
    d = project.metering_detail
    errors, pending = pipe_checks(d, bypass=state.bypass, fire_branch=state.fire_branch,
                                 meter_dn=state.meter.dn if state.meter else None)
    errors += support_pipe(d)[2]
    pages, content, y = [], [], 0
    columns = (27, 102, 195, 255, 407)
    def start():
        g = [_text(28,17,"Трубы водомерного узла по участкам",5),
             _text(28,26,"У1-У6 - марки участков на схеме. Материалы не назначаются всему узлу автоматически.",3.5)]
        for x, title in zip(columns, ("Участок", "Материал / серия", "Размеры, мм", "Соединение / источник размеров")):
            g.append(_text(x+2,38,title,3.5))
        g.append(_line(27,31,407,31,.25))
        g.append(_line(27,42,407,42,.25))
        return g, 42
    for role, (ident, title) in PIPE_ROLES.items():
        active = state.bypass if role == "bypass" else state.fire_branch if role == "fire_branch" else True
        if not active and role not in d.pipe_sections:
            continue
        pipe = d.pipe_sections.get(role)
        cells = [f"{ident}. {title}", "Не задано", "Не заданы", "Нужны данные"]
        if pipe:
            def number(value):
                return f"{value:g}".replace(".", ",") if value is not None else "?"
            cells = [cells[0], MATERIALS[pipe.material] + (f"; {pipe.series}" if pipe.series else ""),
                     f"Ø{number(pipe.outer_diameter_mm)}×{number(pipe.wall_thickness_mm)}; "
                     f"dвн {number(pipe.inner_diameter_mm)}" + (f"; DN{pipe.nominal_dn}" if pipe.nominal_dn else ""),
                     JOINING[pipe.joining] + ". " + (pipe.geometry_source or "Источник не задан")]
        wrapped = [_lines(cell, columns[i+1]-columns[i]-4,3.5) for i, cell in enumerate(cells)]
        height = max(map(len, wrapped))*5.5+5
        if height > 180:
            raise ValueError("Описание трубы слишком длинное для листа ВУ")
        if not content or y+height > 222:
            if content:
                content.append(table_grid_sides(columns,31,y,kind='pipes'))
                pages.append("".join(content))
            content, y = start()
        content.append(f'<g data-pipe-row="{role}">')
        for i, lines in enumerate(wrapped):
            for n, line in enumerate(lines):
                content.append(_text(columns[i]+2,y+6+n*5.5,line,3.5))
        y += height
        content.extend((_line(27,y,407,y,.25), '</g>'))
    if content:
        content.append(table_grid_sides(columns,31,y,kind='pipes'))
    notes = ["Геометрия: dвн = Dн - 2s. Размеры номинальные, без учёта производственных допусков. "
             "Это ведомость заданных труб, не подтверждение монтажной совместимости."]
    notes += ["Несоответствие: " + error for error in errors]
    notes += list(pending)
    notes.append("Гидравлика, расход и потери водомера сохранены из расчётного ядра. "
                 "Длины, количество соединителей и опор из условной геометрии схемы не определяются.")
    y += 10
    for note in notes:
        lines = _lines(note,374,3.5)
        height = len(lines)*5.5+3
        if height > 180:
            raise ValueError("Примечание по трубам слишком длинное для листа ВУ")
        if y+height > 228:
            pages.append("".join(content))
            content = [_text(28,17,"Трубы водомерного узла - условия привязки",5)]
            y = 32
        for line in lines:
            content.append(_text(28,y,line,3.5))
            y += 5.5
        y += 3
    if content:
        pages.append("".join(content))
    return pages
