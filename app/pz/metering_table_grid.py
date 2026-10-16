"""Close SVG schedules at their actual bounds, including continuation sheets."""


def table_grid_sides(columns, top, bottom, *, kind):
    """Row/header horizontal rules are drawn by the caller; close their ends."""
    from app.pz.metering_detail import _line
    if bottom <= top:
        raise ValueError("Неверная высота таблицы ВУ")
    if len(columns) < 2 or any(a >= b for a, b in zip(columns, columns[1:])):
        raise ValueError("Неверные границы граф таблицы ВУ")
    from html import escape
    return (f'<g data-vu-table-grid="{escape(kind, quote=True)}">'
            + ''.join(_line(x, top, x, bottom, .25) for x in columns)
            + _line(columns[0], bottom, columns[-1], bottom, .25) + '</g>')


def parameter_table(rows, *, columns=(291, 354, 410), top=42):
    """A real two-column table: metric wrapping and a fully closed grid."""
    from app.pz.metering_detail import _line, _lines, _text
    height, leading, padding = 3.5, 5.5, 2
    y = top
    g = ['<g data-vu-parameter-table="true">']
    for index, row in enumerate([('Параметр', 'Значение'), *rows]):
        wrapped = [_lines(value, columns[i+1]-columns[i]-2*padding, height)
                   for i, value in enumerate(row)]
        row_height = max(9, 2*padding+height+(max(map(len, wrapped))-1)*leading)
        g.append(_line(columns[0], y, columns[-1], y, .25))
        for col, lines in enumerate(wrapped):
            g.append(f'<g data-vu-parameter-cell="{index}-{col}" '
                     f'data-left="{columns[col]:g}" data-right="{columns[col+1]:g}" '
                     f'data-top="{y:g}" data-bottom="{y+row_height:g}">')
            for n, line in enumerate(lines):
                g.append(_text(columns[col]+padding, y+padding+height+n*leading, line, height))
            g.append('</g>')
        y += row_height
    g.append(table_grid_sides(columns, top, y, kind='parameters'))
    g.append('</g>')
    return ''.join(g), y
