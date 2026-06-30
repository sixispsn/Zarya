"""
app/pz/ugo.py — библиотека условных графических обозначений (УГО)
для принципиальной схемы водоснабжения. Стиль: ЧЁРНО-БЕЛЫЙ, как в реальном
проекте Антона (том В, «Конференц-зал»). Системы различаются БУКВЕННЫМИ
метками на трубах (В1/Т3/Т4/В2), НЕ цветом.

Каждая функция возвращает строку SVG-элементов. Координаты (x,y) — точка
присоединения/центр, описана в docstring. Все символы приняты Антоном
поэлементной сверкой с DWG.

СЕМЕЙСТВО «БАНТИК» (два равнобедренных треугольника вершинами в центр,
основания снаружи; bowtie/песочные часы). Отличия по центральному элементу:
  • пустой кружок (большой)            → запорный вентиль
  • вертикальный отрезок (чуть длиннее)→ задвижка
  • один треугольник чёрный            → обратный клапан (поток белый→чёрный)
  • шток вверх + «шляпа гриба» + импульс→ редуктор давления
  • шток + ПУСТОЙ кружок на конце       → балансировочный клапан
"""
from __future__ import annotations

BLK = "#000"


# ───────── ПРИБОРЫ ─────────
def washbasin(x, y, s=34, w=2.0, side="right"):
    """Умывальник/Мойка (одинаковое УГО): ромб с вертикалью внутри +
    некрупный закрашенный круг-сифон снизу + носик ВНИЗ-вбок (side right/left)
    + толстый отвод вниз. (x,y) — центр ромба."""
    out = []
    out.append(f'<path d="M{x},{y-s} L{x+s},{y} L{x},{y+s} L{x-s},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<line x1="{x}" y1="{y-s}" x2="{x}" y2="{y+s}" stroke="{BLK}" stroke-width="{w}"/>')
    r = s * 0.32
    cy = y + s + r
    out.append(f'<circle cx="{x}" cy="{cy}" r="{r}" fill="{BLK}"/>')
    ndx = r * 2.2 if side == "right" else -r * 2.2
    out.append(f'<line x1="{x}" y1="{cy}" x2="{x+ndx}" y2="{cy+r*2.2}" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<line x1="{x}" y1="{cy+r}" x2="{x}" y2="{cy+r+s*1.5}" stroke="{BLK}" stroke-width="{w*1.8}"/>')
    return "".join(out)


def shower(x, y, s=34, w=1.6, side="right"):
    """Душ: как умывальник (ромб+вертикаль+сифон+носик+отвод) +
    шланг РОВНЫМ полукругом (R=1.35*s) над прибором + лейка-треугольник
    вершиной ВВЕРХ (основание внизу) на конце дуги. side — куда шланг."""
    out = []
    out.append(f'<path d="M{x},{y-s} L{x+s},{y} L{x},{y+s} L{x-s},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<line x1="{x}" y1="{y-s}" x2="{x}" y2="{y+s}" stroke="{BLK}" stroke-width="{w}"/>')
    r = s * 0.32
    cy = y + s + r
    out.append(f'<circle cx="{x}" cy="{cy}" r="{r}" fill="{BLK}"/>')
    ndx = r * 2.2 if side == "right" else -r * 2.2
    out.append(f'<line x1="{x}" y1="{cy}" x2="{x+ndx}" y2="{cy+r*2.2}" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<line x1="{x}" y1="{cy+r}" x2="{x}" y2="{cy+r+s*1.5}" stroke="{BLK}" stroke-width="{w*2.0}"/>')
    sgn = 1 if side == "right" else -1
    R = s * 1.35
    start_x, start_y = x, y - s
    end_x = start_x + sgn * 2 * R
    sweep = 1 if side == "right" else 0
    out.append(f'<path d="M{start_x},{start_y} A {R},{R} 0 0 {sweep} {end_x},{start_y}" fill="none" stroke="{BLK}" stroke-width="{w}"/>')
    tw = s * 0.5; th = s * 0.95
    out.append(f'<path d="M{end_x},{start_y} L{end_x-tw},{start_y+th} L{end_x+tw},{start_y+th} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    return "".join(out)


def toilet(cx, top_y, w=2.0):
    """Унитаз: вытянутый прямоугольник-бачок (ширина 150 > высота 75) +
    отвод ближе к КРАЮ (px = cx + bw*0.32) + вентиль-бабочка с кругом на отводе.
    (cx, top_y) — центр по X и верх прямоугольника."""
    out = []
    bw, bh = 150, 75
    out.append(f'<rect x="{cx-bw/2}" y="{top_y}" width="{bw}" height="{bh}" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    px = cx + bw * 0.32
    sy = 27
    vy = top_y + bh + 80
    out.append(f'<line x1="{px}" y1="{top_y+bh}" x2="{px}" y2="{vy-sy}" stroke="{BLK}" stroke-width="{w*3}"/>')
    out.append(_bowtie_circle_v(px, vy, 18, sy, 0.32, w))
    out.append(f'<line x1="{px}" y1="{vy+sy}" x2="{px}" y2="{vy+sy+60}" stroke="{BLK}" stroke-width="{w*3}"/>')
    return "".join(out)


def _bowtie_circle_v(x, y, sx, sy, rk, w):
    """Вспом.: вытянутый вертикальный бантик + малый круг (для отвода унитаза)."""
    out = []
    out.append(f'<path d="M{x-sx},{y-sy} L{x+sx},{y-sy} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<path d="M{x-sx},{y+sy} L{x+sx},{y+sy} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<circle cx="{x}" cy="{y}" r="{sx*rk}" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    return "".join(out)


# ───────── АРМАТУРА (семейство «бантик») ─────────
def valve_h(x, y, tri=26, dot=12, w=2.4):
    """Запорный вентиль, ГОРИЗ. труба: бантик + БОЛЬШОЙ ПУСТОЙ кружок в центре."""
    out = [
        f'<path d="M{x-tri},{y-tri} L{x-tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x+tri},{y-tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<circle cx="{x}" cy="{y}" r="{dot}" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
    ]
    return "".join(out)


def valve_v(x, y, tri=26, dot=12, w=2.4):
    """Запорный вентиль, ВЕРТ. труба."""
    out = [
        f'<path d="M{x-tri},{y-tri} L{x+tri},{y-tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x-tri},{y+tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<circle cx="{x}" cy="{y}" r="{dot}" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
    ]
    return "".join(out)


def gate_h(x, y, tri=26, bar=15, w=2.4):
    """Задвижка, ГОРИЗ. труба: бантик + вертикальный отрезок в центре (2*bar=30,
    чуть длиннее диаметра кружка вентиля)."""
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x-tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x+tri},{y-tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<line x1="{x}" y1="{y-bar}" x2="{x}" y2="{y+bar}" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def gate_v(x, y, tri=26, bar=15, w=2.4):
    """Задвижка, ВЕРТ. труба: вертикальный бантик + ПОПЕРЕЧНЫЙ (гориз.) отрезок."""
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x+tri},{y-tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x-tri},{y+tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<line x1="{x-bar}" y1="{y}" x2="{x+bar}" y2="{y}" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def check_h(x, y, tri=26, flow="right", w=2.4):
    """Обратный клапан, ГОРИЗ.: один треугольник ЧЁРНЫЙ. Поток белый→чёрный.
    flow='right' → правый чёрный (поток вправо)."""
    left = BLK if flow == "left" else "white"
    right = BLK if flow == "right" else "white"
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x-tri},{y+tri} L{x},{y} Z" fill="{left}" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x+tri},{y-tri} L{x+tri},{y+tri} L{x},{y} Z" fill="{right}" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def check_v(x, y, tri=26, flow="down", w=2.4):
    """Обратный клапан, ВЕРТ.: flow='down' → нижний чёрный (поток вниз)."""
    top = BLK if flow == "up" else "white"
    bot = BLK if flow == "down" else "white"
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x+tri},{y-tri} L{x},{y} Z" fill="{top}" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x-tri},{y+tri} L{x+tri},{y+tri} L{x},{y} Z" fill="{bot}" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def reducer_h(x, y, tri=26, w=2.4):
    """Редуктор давления, ГОРИЗ.: бантик + шток вверх + «шляпа гриба» (полукруг,
    снизу замкнут прямой = мембрана) + импульсная линия (вверх→вправо короткий→
    вниз) с крупной стрелкой к выходной трубе. Возвращает (svg, imp_x)."""
    out = []
    out.append(f'<path d="M{x-tri},{y-tri} L{x-tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    out.append(f'<path d="M{x+tri},{y-tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    cap_y = y - 34
    out.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{cap_y}" stroke="{BLK}" stroke-width="1.6"/>')
    rcap = 11
    out.append(f'<path d="M{x-rcap},{cap_y} A {rcap},{rcap} 0 0 1 {x+rcap},{cap_y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>')
    top_cap = cap_y - rcap
    imp_top = top_cap - 16
    imp_x = x + tri + 30
    out.append(f'<line x1="{x}" y1="{top_cap}" x2="{x}" y2="{imp_top}" stroke="{BLK}" stroke-width="1.4"/>')
    out.append(f'<line x1="{x}" y1="{imp_top}" x2="{imp_x}" y2="{imp_top}" stroke="{BLK}" stroke-width="1.4"/>')
    out.append(f'<line x1="{imp_x}" y1="{imp_top}" x2="{imp_x}" y2="{y-26}" stroke="{BLK}" stroke-width="1.4"/>')
    out.append(f'<path d="M{imp_x},{y} L{imp_x-9},{y-26} L{imp_x+9},{y-26} Z" fill="{BLK}"/>')
    return "".join(out), imp_x


def balance_h(x, y, tri=26, stem=30, rk=9, w=2.4):
    """Балансировочный клапан, ГОРИЗ.: бантик + шток вверх + ПУСТОЙ кружок на конце."""
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x-tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x+tri},{y-tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y-stem}" stroke="{BLK}" stroke-width="1.6"/>',
        f'<circle cx="{x}" cy="{y-stem-rk}" r="{rk}" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def balance_v(x, y, tri=26, stem=30, rk=9, w=2.4):
    """Балансировочный клапан, ВЕРТ.: шток вбок + пустой кружок."""
    return ("".join([
        f'<path d="M{x-tri},{y-tri} L{x+tri},{y-tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x-tri},{y+tri} L{x+tri},{y+tri} L{x},{y} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
        f'<line x1="{x}" y1="{y}" x2="{x+stem}" y2="{y}" stroke="{BLK}" stroke-width="1.6"/>',
        f'<circle cx="{x+stem+rk}" cy="{y}" r="{rk}" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


def air_valve(x, y, stem=26, tw=11, th=18, w=2.4):
    """Воздушный клапан/воздухоотводчик: короткая вертикальная линия от трубы +
    треугольник вершиной ВВЕРХ (основание внизу) на конце. (x,y) — точка на трубе."""
    top = y - stem
    return ("".join([
        f'<line x1="{x}" y1="{y}" x2="{x}" y2="{top}" stroke="{BLK}" stroke-width="{w}"/>',
        f'<path d="M{x-tw},{top} L{x+tw},{top} L{x},{top-th} Z" fill="white" stroke="{BLK}" stroke-width="{w}"/>',
    ]))


# ───────── ЕЩЁ НЕ НАРИСОВАНО (ждут описания Антона) ─────────
# fnet(x,y)    — фильтр сетчатый
# meter(x,y)   — счётчик воды
# pump(x,y)    — насос
# pk(x,y)      — пожарный кран ПК (шкаф)
# riser(...)   — стояк (штрихпунктир + буквенные метки В1/Т3/Т4 вдоль линии)
